"""
Update Log: Workshop mods grouped by when their installed version was published.

Replaces the ACF Log Reader. Reads the SteamCMD and Steam Workshop ACF files,
groups every installed Workshop item into Today / This Week / This Month+ by
the publish time of the version on disk, and shows at a glance which mods are
active and which have a newer version waiting on the Workshop.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from loguru import logger
from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QHideEvent,
    QImage,
    QMouseEvent,
    QPainter,
    QPalette,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QStandardItem,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
)

from app.controllers.metadata_controller import MetadataController
from app.models.metadata.metadata_structure import AboutXmlMod
from app.utils.csv_export_utils import export_to_csv
from app.utils.event_bus import EventBus
from app.utils.generic import get_relative_time, platform_specific_open
from app.utils.mod_info import ModInfo
from app.utils.preview_image_loader import PreviewImageLoader
from app.windows.base_mods_panel import BaseModsPanel, ColumnIndex, HeaderColumn

STATUS_COLUMN = ColumnIndex.WORKSHOP_PAGE.value + 1
# Workshop previews are mostly 16:9, so the thumbnail box is landscape
THUMBNAIL_WIDTH = 128
THUMBNAIL_HEIGHT = 72
ROW_HEIGHT = 80
# Width of the full preview shown in the hover popup
PREVIEW_POPUP_WIDTH = 400
# Gap between the hovered Mod cell and the preview popup
_PREVIEW_POPUP_GAP = 12
_PREVIEW_HOVER_DELAY_MS = 250
GROUP_ROW_HEIGHT = 30
_CELL_PADDING = 6
# Rows past the viewport edge that also get thumbnails, so scrolling stays smooth
_THUMBNAIL_LOOKAHEAD_ROWS = 10

# Item roles stored on the name cell of each row
GROUP_ROLE = Qt.ItemDataRole.UserRole + 1  # True on a group header row
TIMESTAMP_ROLE = Qt.ItemDataRole.UserRole + 2  # epoch of the installed version
ACTIVE_ROLE = Qt.ItemDataRole.UserRole + 3  # mod is in the active list
UPDATE_AVAILABLE_ROLE = Qt.ItemDataRole.UserRole + 4  # newer version on Workshop
THUMBNAIL_PATH_ROLE = Qt.ItemDataRole.UserRole + 5  # preview image to load lazily
IDENTIFIERS_ROLE = Qt.ItemDataRole.UserRole + 6  # lines shown in the hover popup


class UpdateBucket(Enum):
    """Recency groups, in display order."""

    TODAY = "Today"
    THIS_WEEK = "This Week"
    THIS_MONTH_PLUS = "This Month+"
    UNKNOWN = "Unknown"


def bucket_for(timestamp: int | None, now: float) -> UpdateBucket:
    """Place an update time into a recency group.

    "Today" is the local calendar day of ``now``; "This Week" is the seven days
    before that; everything older is "This Month+".

    :param timestamp: Epoch seconds of the update, or None/0 when unknown.
    :param now: Epoch seconds to measure recency against.
    :return: The group the timestamp belongs to.
    """
    if not timestamp or timestamp <= 0:
        return UpdateBucket.UNKNOWN
    then = time.localtime(timestamp)
    today = time.localtime(now)
    if then[:3] >= today[:3]:
        return UpdateBucket.TODAY
    if now - timestamp < 7 * 86400:
        return UpdateBucket.THIS_WEEK
    return UpdateBucket.THIS_MONTH_PLUS


@dataclass
class UpdateEntry:
    """One Workshop item as recorded in an ACF file."""

    pfid: str
    source: str
    time_updated: int | None
    latest_time_updated: int | None

    @property
    def update_available(self) -> bool:
        """Whether the Workshop has a newer version than the one installed."""
        return bool(
            self.time_updated
            and self.latest_time_updated
            and self.latest_time_updated > self.time_updated
        )


def _as_epoch(value: Any) -> int | None:
    try:
        epoch = int(value)
    except TypeError, ValueError:
        return None
    return epoch if epoch > 0 else None


def _entries_from_acf(acf_data: dict[str, Any], source: str) -> list[UpdateEntry]:
    app_workshop = acf_data.get("AppWorkshop", {}) if acf_data else {}
    details = app_workshop.get("WorkshopItemDetails", {}) or {}
    installed = app_workshop.get("WorkshopItemsInstalled", {}) or {}
    entries: list[UpdateEntry] = []
    for pfid in dict.fromkeys([*details, *installed]):
        detail = details.get(pfid)
        detail = detail if isinstance(detail, dict) else {}
        install = installed.get(pfid)
        install = install if isinstance(install, dict) else {}
        time_updated = _as_epoch(detail.get("timeupdated")) or _as_epoch(
            install.get("timeupdated")
        )
        entries.append(
            UpdateEntry(
                pfid=str(pfid),
                source=source,
                time_updated=time_updated,
                latest_time_updated=_as_epoch(detail.get("latest_timeupdated")),
            )
        )
    return entries


def extract_update_entries(
    steamcmd_acf_data: dict[str, Any], workshop_acf_data: dict[str, Any]
) -> list[UpdateEntry]:
    """Collect Workshop items from both ACF files, SteamCMD taking precedence.

    :param steamcmd_acf_data: Parsed SteamCMD ``appworkshop_294100.acf``.
    :param workshop_acf_data: Parsed Steam client ``appworkshop_294100.acf``.
    :return: One entry per published file ID.
    """
    entries = _entries_from_acf(steamcmd_acf_data, "SteamCMD")
    seen = {entry.pfid for entry in entries}
    entries.extend(
        entry
        for entry in _entries_from_acf(workshop_acf_data, "Steam")
        if entry.pfid not in seen
    )
    return entries


def preview_popup_position(cell: QRect, size: QSize, screen: QRect) -> QPoint:
    """Place a popup beside a hovered cell, never under the pointer.

    The popup goes to the right of the cell, centred on its row, and flips to
    the left when there is no room; it is then clamped to the screen.

    :param cell: The hovered cell in global coordinates.
    :param size: Size of the popup.
    :param screen: Available geometry of the screen showing the cell.
    :return: Top-left corner for the popup, in global coordinates.
    """
    x = cell.right() + _PREVIEW_POPUP_GAP
    if x + size.width() > screen.left() + screen.width():
        x = cell.left() - _PREVIEW_POPUP_GAP - size.width()
    x = max(screen.left(), x)
    y = cell.center().y() - size.height() // 2
    y = max(screen.top(), min(y, screen.top() + screen.height() - size.height()))
    return QPoint(x, y)


class _PreviewPopup(QFrame):
    """Frameless tooltip-style window showing a mod's preview and identifiers."""

    def __init__(self) -> None:
        super().__init__(
            None, Qt.WindowType.ToolTip | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        # Themes style this name like their tooltips (see themes/*/style.qss)
        self.setObjectName("updateLogPreviewPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFrameShape(QFrame.Shape.Box)
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.ColorRole.ToolTipBase)
        self.setForegroundRole(QPalette.ColorRole.ToolTipText)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text = QLabel()
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.image)
        layout.addWidget(self.text)

    def set_content(self, pixmap: QPixmap | None, lines: list[str]) -> None:
        self.image.setVisible(pixmap is not None)
        if pixmap is not None:
            self.image.setPixmap(pixmap)
        self.text.setText("\n".join(lines))
        self.adjustSize()


class UpdateLog(BaseModsPanel):
    """
    Update Log tab: every installed Workshop mod, newest update first, grouped
    by Today / This Week / This Month+.

    The table keeps BaseModsPanel's standard columns (so its selection, Steam,
    SteamCMD, delete and CSV export plumbing keep working) and hides the ones
    that are noise at a glance. The visible columns are Mod (thumbnail, name,
    author), Updated, Status, Versions, Source and Workshop.
    """

    persistent_view = True

    # Columns to search in the search bar
    SEARCHABLE_COLUMNS = [  # noqa: RUF012
        ColumnIndex.NAME.value,
        ColumnIndex.AUTHOR.value,
        ColumnIndex.PACKAGE_ID.value,
        ColumnIndex.PUBLISHED_FILE_ID.value,
    ]
    HIDDEN_COLUMNS = (
        ColumnIndex.AUTHOR.value,
        ColumnIndex.PACKAGE_ID.value,
        ColumnIndex.PUBLISHED_FILE_ID.value,
        ColumnIndex.MOD_DOWNLOADED.value,
        ColumnIndex.PATH.value,
    )
    VISIBLE_ORDER = (
        ColumnIndex.CHECKBOX.value,
        ColumnIndex.NAME.value,
        ColumnIndex.UPDATED_ON_WORKSHOP.value,
        STATUS_COLUMN,
        ColumnIndex.SUPPORTED_VERSIONS.value,
        ColumnIndex.SOURCE.value,
        ColumnIndex.WORKSHOP_PAGE.value,
    )

    def __init__(
        self,
        metadata_controller: MetadataController,
        active_mods_list: object | None = None,
    ) -> None:
        """
        :param metadata_controller: Source of mod metadata and ACF data.
        :param active_mods_list: The active mod list widget, used to flag active mods.
        """
        self.active_mods_list = active_mods_list
        self.metadata_controller = metadata_controller
        self.active_pfids: set[str] = set()
        self.search_column_index = -1
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._perform_search)
        # Population is coalesced so refresh signals that fire together fill once
        self._populate_timer = QTimer()
        self._populate_timer.setSingleShot(True)
        self._populate_timer.timeout.connect(self._populate_now)
        # Set when metadata changed while hidden; the table is filled on show
        self._populate_pending = False
        self._group_rows: list[int] = []
        # Rows waiting for a thumbnail, keyed by preview image path
        self._thumbnail_rows: dict[str, list[int]] = {}
        self._thumbnail_loader = PreviewImageLoader(
            cache_size=1024, max_side=THUMBNAIL_WIDTH * 2, cancel_pending=False
        )
        self._thumbnail_loader.image_ready.connect(self._on_thumbnail_ready)
        self._thumbnail_timer = QTimer()
        self._thumbnail_timer.setSingleShot(True)
        self._thumbnail_timer.timeout.connect(self._request_visible_thumbnails)
        # Hover preview: latest-wins decoding at popup size, shown beside the row
        self._preview_loader = PreviewImageLoader(
            cache_size=64, max_side=PREVIEW_POPUP_WIDTH, cancel_pending=True
        )
        self._preview_loader.image_ready.connect(self._on_preview_ready)
        self._preview_popup = _PreviewPopup()
        self._hover_row = -1
        self._hover_timer = QTimer()
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(_PREVIEW_HOVER_DELAY_MS)
        self._hover_timer.timeout.connect(self._show_preview_popup)

        super().__init__(
            object_name="UpdateLog",
            window_title=self.tr("Update Log"),
            title_text=self.tr("Mod Update Log"),
            details_text=self.tr(
                "Workshop mods grouped by when the installed version was published. "
                "Newest first; a mod shows 'Update available' when the Workshop has "
                "a newer version than the one on disk."
            ),
            additional_columns=self._columns(),
            metadata_controller=self.metadata_controller,
        )
        # Embedded in a tab: there is nothing to exit
        self.ui_elements.editor_cancel_button.hide()

        button_configs = self._get_base_button_configs()
        self._extend_button_configs_with_steam_actions(button_configs)
        button_configs.append(
            self._create_delete_button_config(self.tr("Delete Selected Mods"))
        )
        self._setup_buttons_from_config(button_configs)

        self._setup_toolbar()
        self._setup_columns()
        self.editor_table_view.setItemDelegate(UpdateLogDelegate(self))
        self.editor_table_view.verticalScrollBar().valueChanged.connect(
            self._on_scrolled
        )
        self.editor_table_view.setMouseTracking(True)
        self.editor_table_view.viewport().installEventFilter(self)
        EventBus().refresh_finished.connect(self._populate_from_metadata)

    # ------------------------------------------------------------------ setup
    def _columns(self) -> list[HeaderColumn]:
        fit = QHeaderView.ResizeMode.ResizeToContents
        return [
            (self.tr("Mod"), QHeaderView.ResizeMode.Stretch),
            self.tr("Author"),
            self.tr("Package ID"),
            self.tr("Published File Id"),
            (self.tr("Versions"), fit),
            self.tr("Downloaded"),
            (self.tr("Updated"), fit),
            (self.tr("Source"), fit),
            self.tr("Path"),
            (self.tr("Workshop"), fit),
            (self.tr("Status"), fit),
        ]

    def _setup_columns(self) -> None:
        header = self.editor_table_view.horizontalHeader()
        for column in self.HIDDEN_COLUMNS:
            self.editor_table_view.setColumnHidden(column, True)
        for position, column in enumerate(self.VISIBLE_ORDER):
            header.moveSection(header.visualIndex(column), position)
        vertical = self.editor_table_view.verticalHeader()
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical.setDefaultSectionSize(ROW_HEIGHT)
        vertical.hide()
        self.editor_table_view.setShowGrid(False)
        self.editor_table_view.setSortingEnabled(False)

    def _setup_toolbar(self) -> None:
        toolbar = QHBoxLayout()
        self.import_acf_btn = QPushButton(self.tr("Import ACF Data"))
        self.import_acf_btn.clicked.connect(lambda: EventBus().do_import_acf.emit())
        toolbar.addWidget(self.import_acf_btn)
        self.export_acf_btn = QPushButton(self.tr("Export ACF Data"))
        self.export_acf_btn.clicked.connect(lambda: EventBus().do_export_acf.emit())
        toolbar.addWidget(self.export_acf_btn)
        self.export_csv_btn = QPushButton(self.tr("Export to CSV"))
        self.export_csv_btn.clicked.connect(lambda: export_to_csv(self))
        toolbar.addWidget(self.export_csv_btn)
        toolbar.addStretch()
        toolbar.addWidget(QLabel(self.tr("Search:")))
        self.search_column_filter = QComboBox()
        self.search_column_filter.addItem(self.tr("All Searchable Columns"), -1)
        for column, label in (
            (ColumnIndex.NAME.value, self.tr("Name")),
            (ColumnIndex.AUTHOR.value, self.tr("Author")),
            (ColumnIndex.PACKAGE_ID.value, self.tr("Package ID")),
            (ColumnIndex.PUBLISHED_FILE_ID.value, self.tr("Published File Id")),
        ):
            self.search_column_filter.addItem(label, column)
        self.search_column_filter.currentIndexChanged.connect(
            self._on_search_column_changed
        )
        toolbar.addWidget(self.search_column_filter)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            self.tr("Filter by name, author, package ID or published file ID")
        )
        self.search_input.textChanged.connect(self._on_search_text_changed)
        toolbar.addWidget(self.search_input, 1)
        self.layouts.editor_layout.insertLayout(0, toolbar)

    # ------------------------------------------------------------- population
    def _populate_from_metadata(self) -> None:
        """Fill the table once the current refresh has settled.

        Called from both ``metadata_refreshed`` and ``refresh_finished``; the
        single-shot timer merges them, and a hidden tab waits until shown.
        """
        if not self.isVisible():
            self._populate_pending = True
            return
        self._populate_timer.start(0)

    def showEvent(self, event: QShowEvent) -> None:
        """Fill the table if metadata changed while the tab was hidden."""
        super().showEvent(event)
        if self._populate_pending:
            self._populate_pending = False
            self._populate_timer.start(0)
        else:
            self._refresh_active_flags()
            self._thumbnail_timer.start(0)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._thumbnail_timer.start(0)

    def _populate_now(self) -> None:
        self._populate_pending = False
        started = time.time()
        self._update_active_pfids()
        entries = extract_update_entries(
            self.metadata_controller.steamcmd_acf_data,
            self.metadata_controller.workshop_acf_data,
        )
        mods_by_pfid = self._get_mods_for_pfids({entry.pfid for entry in entries})
        now = time.time()
        grouped: dict[UpdateBucket, list[tuple[UpdateEntry, int | None]]] = {
            bucket: [] for bucket in UpdateBucket
        }
        for entry in entries:
            metadata = mods_by_pfid.get(entry.pfid)
            timestamp = entry.time_updated or (
                _as_epoch(metadata["external_time_updated"]) if metadata else None
            )
            grouped[bucket_for(timestamp, now)].append((entry, timestamp))
        for rows in grouped.values():
            rows.sort(key=lambda row: row[1] or 0, reverse=True)

        self._hide_preview_popup()
        self.editor_table_view.setUpdatesEnabled(False)
        try:
            self._clear_table_model()
            self.editor_table_view.clearSpans()
            self._group_rows = []
            self._thumbnail_rows = {}
            for bucket, rows in grouped.items():
                if not rows:
                    continue
                self._add_group_row(bucket, len(rows))
                for entry, timestamp in rows:
                    self._add_update_row(entry, timestamp, mods_by_pfid.get(entry.pfid))
        finally:
            self.editor_table_view.setUpdatesEnabled(True)
        self.apply_search_filter(self.search_input.text())
        self._thumbnail_timer.start(0)
        logger.info(
            f"Update Log: listed {len(entries)} Workshop items in "
            f"{time.time() - started:.3f}s"
        )

    def _bucket_label(self, bucket: UpdateBucket) -> str:
        return {
            UpdateBucket.TODAY: self.tr("Today"),
            UpdateBucket.THIS_WEEK: self.tr("This Week"),
            UpdateBucket.THIS_MONTH_PLUS: self.tr("This Month+"),
            UpdateBucket.UNKNOWN: self.tr("Unknown update time"),
        }[bucket]

    def _add_group_row(self, bucket: UpdateBucket, count: int) -> None:
        items = [QStandardItem() for _ in range(self.editor_model.columnCount())]
        header = items[ColumnIndex.NAME.value]
        header.setText(f"{self._bucket_label(bucket)}  ·  {count}")
        header.setData(True, GROUP_ROLE)
        for item in items:
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.editor_model.appendRow(items)
        row = self.editor_model.rowCount() - 1
        self.editor_table_view.setSpan(row, 0, 1, self.editor_model.columnCount())
        self.editor_table_view.setRowHeight(row, GROUP_ROW_HEIGHT)
        self._group_rows.append(row)

    def _add_update_row(
        self, entry: UpdateEntry, timestamp: int | None, metadata: dict[str, Any] | None
    ) -> None:
        pfid = entry.pfid
        name = (
            metadata["name"]
            if metadata
            else self.tr("Unknown mod ({pfid})").format(pfid=pfid)
        )
        authors = metadata["authors"] if metadata else ""
        package_id = metadata["packageid"] if metadata else ""
        path = metadata["path"] if metadata else ""
        versions = ModInfo._parse_supported_versions_static(
            metadata["supportedversions"] if metadata else None
        )
        active = pfid in self.active_pfids

        name_item = QStandardItem(name)
        if metadata:
            name_item.setData(metadata["key"], Qt.ItemDataRole.UserRole)
            if metadata["preview"]:
                name_item.setData(metadata["preview"], THUMBNAIL_PATH_ROLE)
        name_item.setData(timestamp, TIMESTAMP_ROLE)
        name_item.setData(active, ACTIVE_ROLE)
        name_item.setData(entry.update_available, UPDATE_AVAILABLE_ROLE)
        name_item.setData(
            self._identifier_lines(package_id, pfid, path), IDENTIFIERS_ROLE
        )

        updated_item = QStandardItem(
            get_relative_time(timestamp) if timestamp else self.tr("Unknown")
        )
        if timestamp:
            updated_item.setToolTip(
                time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))
            )
        updated_item.setData(timestamp, TIMESTAMP_ROLE)

        status_parts = []
        if entry.update_available:
            status_parts.append(self.tr("Update available"))
        if active:
            status_parts.append(self.tr("Active"))
        status_item = QStandardItem(", ".join(status_parts))

        check_item = QStandardItem()
        check_item.setCheckable(True)
        check_item.setCheckState(Qt.CheckState.Unchecked)
        self.editor_model.appendRow(
            [
                check_item,
                name_item,
                QStandardItem(authors),
                QStandardItem(package_id),
                QStandardItem(pfid),
                QStandardItem(versions),
                QStandardItem(""),
                updated_item,
                QStandardItem(entry.source),
                QStandardItem(path),
                QStandardItem(ModInfo._generate_workshop_url(pfid)),
                status_item,
            ]
        )
        if metadata and metadata["preview"]:
            row = self.editor_model.rowCount() - 1
            self._thumbnail_rows.setdefault(metadata["preview"], []).append(row)

    # Rows use checkable items instead of a QCheckBox widget per row, which keeps
    # filling ~1000 rows fast; BaseModsPanel's selection helpers read them here.
    def _row_is_checked(self, row: int) -> bool:
        item = self.editor_model.item(row, ColumnIndex.CHECKBOX.value)
        return item is not None and item.checkState() == Qt.CheckState.Checked

    def _set_all_checkbox_rows(self, value: bool) -> None:
        state = Qt.CheckState.Checked if value else Qt.CheckState.Unchecked
        for row in range(self.editor_model.rowCount()):
            item = self.editor_model.item(row, ColumnIndex.CHECKBOX.value)
            if item is not None and item.isCheckable():
                item.setCheckState(state)

    def _identifier_lines(self, package_id: str, pfid: str, path: str) -> list[str]:
        lines = [
            self.tr("Package ID: {package_id}").format(package_id=package_id),
            self.tr("Published File ID: {pfid}").format(pfid=pfid),
        ]
        if path:
            lines.append(self.tr("Path: {path}").format(path=path))
        return lines

    # ---------------------------------------------------------- hover preview
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # BaseModsPanel installs this filter before the table exists
        view = getattr(self, "editor_table_view", None)
        if view is not None and watched is view.viewport():
            if event.type() == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
                self._on_hover(view.indexAt(event.position().toPoint()))
            elif event.type() == QEvent.Type.Leave:
                self._hide_preview_popup()
        return super().eventFilter(watched, event)

    def _on_hover(self, index: QModelIndex) -> None:
        """Arm the preview popup for the Mod cell under the pointer."""
        name_item = (
            self.editor_model.item(index.row(), ColumnIndex.NAME.value)
            if index.isValid() and index.column() == ColumnIndex.NAME.value
            else None
        )
        if name_item is None or name_item.data(GROUP_ROLE):
            self._hide_preview_popup()
            return
        if index.row() == self._hover_row:
            return
        self._hover_row = index.row()
        if self._preview_popup.isVisible():
            self._show_preview_popup()
        else:
            self._hover_timer.start()

    def _show_preview_popup(self) -> None:
        name_item = self.editor_model.item(self._hover_row, ColumnIndex.NAME.value)
        if name_item is None or not self.isVisible():
            return
        preview = name_item.data(THUMBNAIL_PATH_ROLE)
        image = self._preview_loader.load(preview) if preview else None
        if preview and image is None:
            # Decoding; _on_preview_ready places the popup when it lands
            return
        self._place_preview_popup(name_item, image)

    def _on_preview_ready(self, preview: str, image: QImage) -> None:
        name_item = self.editor_model.item(self._hover_row, ColumnIndex.NAME.value)
        if name_item is not None and name_item.data(THUMBNAIL_PATH_ROLE) == preview:
            self._place_preview_popup(name_item, image)

    def _place_preview_popup(
        self, name_item: QStandardItem, image: QImage | None
    ) -> None:
        pixmap = (
            QPixmap.fromImage(image)
            if image is not None and not image.isNull()
            else None
        )
        self._preview_popup.set_content(pixmap, name_item.data(IDENTIFIERS_ROLE) or [])
        view = self.editor_table_view
        cell = view.visualRect(name_item.index())
        cell.moveTopLeft(view.viewport().mapToGlobal(cell.topLeft()))
        screen = QApplication.screenAt(cell.center()) or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else cell
        self._preview_popup.move(
            preview_popup_position(cell, self._preview_popup.size(), available)
        )
        self._preview_popup.show()

    def _hide_preview_popup(self) -> None:
        self._hover_timer.stop()
        self._hover_row = -1
        self._preview_popup.hide()

    def _on_scrolled(self, _value: int) -> None:
        self._hide_preview_popup()
        self._thumbnail_timer.start(0)

    def hideEvent(self, event: QHideEvent) -> None:
        self._hide_preview_popup()
        super().hideEvent(event)

    def _get_mods_for_pfids(self, pfids: set[str]) -> dict[str, dict[str, Any]]:
        """Describe the installed mods behind a set of published file IDs.

        :param pfids: Published file IDs from the ACF files.
        :return: Per PFID: key, name, authors, packageid, path, supportedversions,
            preview and external_time_updated.
        """
        matching = [
            (path, mod)
            for path, mod in self.metadata_controller.mods_metadata.items()
            if mod.published_file_id and mod.published_file_id in pfids
        ]
        aux_db_controller = self.metadata_controller.metadata_db_controller
        with aux_db_controller.Session() as session:
            aux_entries = aux_db_controller.get_many(
                session, [path for path, _ in matching]
            )
        result: dict[str, dict[str, Any]] = {}
        for path, mod in matching:
            pfid = mod.published_file_id
            if not pfid:
                continue
            authors = ""
            package_id = ""
            preview = None
            if isinstance(mod, AboutXmlMod):
                authors = ", ".join(mod.authors) if mod.authors else ""
                package_id = str(mod.package_id)
                preview = mod.preview_img_path
            aux_entry = aux_entries.get(path)
            result[pfid] = {
                "key": path,
                "name": mod.name,
                "authors": authors,
                "packageid": package_id,
                "path": str(mod.mod_path) if mod.mod_path else "",
                "supportedversions": mod.supported_versions,
                "preview": str(preview) if preview else "",
                "external_time_updated": getattr(
                    aux_entry, "external_time_updated", None
                ),
            }
        return result

    # ------------------------------------------------------------ active mods
    def _update_active_pfids(self) -> None:
        self.active_pfids.clear()
        for path in getattr(self.active_mods_list, "paths", None) or []:
            mod = self.metadata_controller.get_mod(path)
            if mod is not None and mod.published_file_id:
                self.active_pfids.add(mod.published_file_id)

    def _refresh_active_flags(self) -> None:
        """Re-derive the Active flag of every row from the current active list."""
        self._update_active_pfids()
        for row in range(self.editor_model.rowCount()):
            name_item = self.editor_model.item(row, ColumnIndex.NAME.value)
            if name_item is None or name_item.data(GROUP_ROLE):
                continue
            pfid = self.editor_model.item(row, ColumnIndex.PUBLISHED_FILE_ID.value)
            active = pfid is not None and pfid.text() in self.active_pfids
            if bool(name_item.data(ACTIVE_ROLE)) == active:
                continue
            name_item.setData(active, ACTIVE_ROLE)
            parts = []
            if name_item.data(UPDATE_AVAILABLE_ROLE):
                parts.append(self.tr("Update available"))
            if active:
                parts.append(self.tr("Active"))
            status = self.editor_model.item(row, STATUS_COLUMN)
            if status is not None:
                status.setText(", ".join(parts))
        self.editor_table_view.viewport().update()

    # ------------------------------------------------------------- thumbnails
    def _visible_rows(self) -> list[int]:
        """Rows in the viewport plus a lookahead on both sides, hidden rows skipped.

        The viewport is walked by position so filtered-out rows cost nothing.
        Before the view has laid out its rows ``rowAt`` answers -1 everywhere,
        so the rows are then estimated from the scrollbar and viewport height.
        """
        view = self.editor_table_view
        height = view.viewport().height()
        lookahead = _THUMBNAIL_LOOKAHEAD_ROWS * ROW_HEIGHT
        max_rows = height // GROUP_ROW_HEIGHT + 2 * _THUMBNAIL_LOOKAHEAD_ROWS + 1
        rows: list[int] = []
        y = -lookahead
        while y < height + lookahead and len(rows) < max_rows:
            row = view.rowAt(y)
            if row < 0:
                y += GROUP_ROW_HEIGHT
                continue
            if not rows or rows[-1] != row:
                rows.append(row)
            y = view.rowViewportPosition(row) + view.rowHeight(row)
        if rows or self.editor_model.rowCount() == 0:
            return rows
        first = view.verticalScrollBar().value()
        return [
            row
            for row in range(first, min(self.editor_model.rowCount(), first + max_rows))
            if not view.isRowHidden(row)
        ]

    def _request_visible_thumbnails(self) -> None:
        """Ask the loader for the previews of rows in (or near) the viewport."""
        if not self.isVisible():
            return
        for row in self._visible_rows():
            name_item = self.editor_model.item(row, ColumnIndex.NAME.value)
            if name_item is None:
                continue
            preview = name_item.data(THUMBNAIL_PATH_ROLE)
            if not preview or name_item.data(Qt.ItemDataRole.DecorationRole):
                continue
            image = self._thumbnail_loader.load(preview)
            if image is not None:
                self._set_thumbnail(name_item, image)

    def _on_thumbnail_ready(self, preview: str, image: QImage) -> None:
        for row in self._thumbnail_rows.get(preview, ()):
            name_item = self.editor_model.item(row, ColumnIndex.NAME.value)
            if name_item is not None and name_item.data(THUMBNAIL_PATH_ROLE) == preview:
                self._set_thumbnail(name_item, image)

    @staticmethod
    def _set_thumbnail(name_item: QStandardItem, image: QImage) -> None:
        if image.isNull():
            # Unreadable file: stop asking for it
            name_item.setData("", THUMBNAIL_PATH_ROLE)
            return
        pixmap = QPixmap.fromImage(image).scaled(
            THUMBNAIL_WIDTH,
            THUMBNAIL_HEIGHT,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        name_item.setData(pixmap, Qt.ItemDataRole.DecorationRole)

    # ----------------------------------------------------------------- search
    def _on_search_column_changed(self, index: int) -> None:
        self.search_column_index = self.search_column_filter.currentData()
        self._perform_search()

    def _on_search_text_changed(self, text: str) -> None:
        self.search_timer.stop()
        if not text.strip():
            self._perform_search()
        else:
            self.search_timer.start(300)

    def _perform_search(self) -> None:
        self.apply_search_filter(self.search_input.text())

    def apply_search_filter(self, pattern: str) -> None:
        """Show only rows matching ``pattern`` and hide groups left empty.

        :param pattern: Case-insensitive substring; empty shows everything.
        """
        pattern_lower = pattern.lower().strip()
        columns = (
            self.SEARCHABLE_COLUMNS
            if self.search_column_index == -1
            else [self.search_column_index]
        )
        view = self.editor_table_view
        view.setUpdatesEnabled(False)
        try:
            group_has_rows: dict[int, bool] = {}
            current_group = -1
            for row in range(self.editor_model.rowCount()):
                name_item = self.editor_model.item(row, ColumnIndex.NAME.value)
                if name_item is not None and name_item.data(GROUP_ROLE):
                    current_group = row
                    group_has_rows[row] = False
                    continue
                matches = not pattern_lower or any(
                    pattern_lower in (self.editor_model.item(row, col).text().lower())
                    for col in columns
                    if self.editor_model.item(row, col) is not None
                )
                view.setRowHidden(row, not matches)
                if matches and current_group >= 0:
                    group_has_rows[current_group] = True
            for group_row, has_rows in group_has_rows.items():
                view.setRowHidden(group_row, not has_rows)
        finally:
            view.setUpdatesEnabled(True)
        self._thumbnail_timer.start(0)


class UpdateLogDelegate(QStyledItemDelegate):
    """Paints group bands, the thumbnail + name + author cell and the status cell."""

    ACTIVE_COLOR = QColor(46, 125, 50)

    def __init__(self, panel: UpdateLog) -> None:
        super().__init__(panel)
        self._panel = panel

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        size = super().sizeHint(option, index)
        name_index = index.sibling(index.row(), ColumnIndex.NAME.value)
        height = GROUP_ROW_HEIGHT if name_index.data(GROUP_ROLE) else ROW_HEIGHT
        width = size.width()
        if index.column() == STATUS_COLUMN:
            # Status is painted bold, so measure it that way
            font = QFont(option.font)
            font.setBold(True)
            text = str(index.data() or "")
            width = QFontMetrics(font).horizontalAdvance(text) + 2 * _CELL_PADDING + 2
        elif index.column() == ColumnIndex.WORKSHOP_PAGE.value:
            # The cell text is the URL (for CSV export); it is painted as a link
            width = (
                QFontMetrics(option.font).horizontalAdvance(self._link_text())
                + 2 * _CELL_PADDING
                + 2
            )
        return QSize(width, height)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        # Clicking a row makes a cell "current"; the style would frame it, which
        # on the narrow check column shows as a tall outlined bar
        option = QStyleOptionViewItem(option)
        option.state = option.state & ~QStyle.StateFlag.State_HasFocus
        name_index = index.sibling(index.row(), ColumnIndex.NAME.value)
        if name_index.data(GROUP_ROLE):
            # The row is one spanned cell starting at column 0
            text = str(name_index.data() or "") if index.column() == 0 else ""
            self._paint_group(painter, option, text)
            return
        if name_index.data(ACTIVE_ROLE):
            tint = QColor(self.ACTIVE_COLOR)
            tint.setAlpha(36)
            painter.fillRect(option.rect, tint)
        column = index.column()
        if column == ColumnIndex.NAME.value:
            self._paint_mod(painter, option, index)
        elif column == STATUS_COLUMN:
            self._paint_status(painter, option, index, name_index)
        elif column == ColumnIndex.WORKSHOP_PAGE.value:
            self._paint_link(painter, option)
        else:
            super().paint(painter, option, index)

    def _paint_group(
        self, painter: QPainter, option: QStyleOptionViewItem, text: str
    ) -> None:
        painter.save()
        palette = option.palette
        painter.fillRect(option.rect, palette.color(QPalette.ColorRole.AlternateBase))
        font = option.font
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        painter.drawText(
            option.rect.adjusted(_CELL_PADDING, 0, -_CELL_PADDING, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )
        line = palette.color(QPalette.ColorRole.Mid)
        painter.setPen(line)
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()

    def _paint_mod(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.save()
        rect = option.rect.adjusted(_CELL_PADDING, 0, -_CELL_PADDING, 0)
        thumb_box = QRect(
            rect.left(),
            rect.top() + (rect.height() - THUMBNAIL_HEIGHT) // 2,
            THUMBNAIL_WIDTH,
            THUMBNAIL_HEIGHT,
        )
        pixmap = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            target = QRect(0, 0, pixmap.width(), pixmap.height())
            target.moveCenter(thumb_box.center())
            painter.drawPixmap(target, pixmap)
        else:
            placeholder = option.palette.color(QPalette.ColorRole.AlternateBase)
            painter.fillRect(thumb_box, placeholder)
        text_rect = rect.adjusted(THUMBNAIL_WIDTH + _CELL_PADDING * 2, 0, 0, 0)
        half = text_rect.height() // 2
        name_rect = QRect(text_rect.left(), text_rect.top(), text_rect.width(), half)
        author_rect = QRect(
            text_rect.left(), text_rect.top() + half, text_rect.width(), half
        )
        metrics = option.fontMetrics
        name_font = option.font
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(option.palette.color(QPalette.ColorRole.Text))
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
            metrics.elidedText(
                str(index.data() or ""), Qt.TextElideMode.ElideRight, name_rect.width()
            ),
        )
        author = str(index.sibling(index.row(), ColumnIndex.AUTHOR.value).data() or "")
        if author:
            painter.setFont(option.font)
            painter.setPen(option.palette.color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(
                author_rect,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                metrics.elidedText(
                    author, Qt.TextElideMode.ElideRight, author_rect.width()
                ),
            )
        painter.restore()

    def _link_text(self) -> str:
        return self.tr("Open Page")

    def _paint_link(self, painter: QPainter, option: QStyleOptionViewItem) -> None:
        painter.save()
        font = option.font
        font.setUnderline(True)
        painter.setFont(font)
        # Themes style the text colour but not the palette's Link role, so the
        # underline alone marks this as a link
        painter.setPen(option.palette.color(QPalette.ColorRole.Text))
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, self._link_text())
        painter.restore()

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        """Open the Workshop page when its link cell is clicked."""
        if (
            index.column() == ColumnIndex.WORKSHOP_PAGE.value
            and event.type() == QEvent.Type.MouseButtonRelease
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
            and not index.sibling(index.row(), ColumnIndex.NAME.value).data(GROUP_ROLE)
        ):
            url = str(index.data() or "")
            if url:
                platform_specific_open(url)
            return True
        return super().editorEvent(event, model, option, index)

    def _paint_status(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
        name_index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        text = str(index.data() or "")
        if not text:
            return
        painter.save()
        font = option.font
        font.setBold(True)
        painter.setFont(font)
        if name_index.data(UPDATE_AVAILABLE_ROLE):
            painter.setPen(option.palette.color(QPalette.ColorRole.Highlight))
        else:
            painter.setPen(self.ACTIVE_COLOR)
        painter.drawText(
            option.rect.adjusted(_CELL_PADDING, 0, -_CELL_PADDING, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )
        painter.restore()


__all__ = [
    "IDENTIFIERS_ROLE",
    "UpdateBucket",
    "UpdateEntry",
    "UpdateLog",
    "UpdateLogDelegate",
    "bucket_for",
    "extract_update_entries",
    "preview_popup_position",
]
