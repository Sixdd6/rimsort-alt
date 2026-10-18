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
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QHideEvent,
    QPalette,
    QResizeEvent,
    QShowEvent,
    QStandardItem,
)
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from app.controllers.metadata_controller import MetadataController
from app.models.metadata.metadata_structure import AboutXmlMod
from app.utils.csv_export_utils import export_to_csv
from app.utils.event_bus import EventBus
from app.utils.generic import get_relative_time
from app.utils.mod_info import ModInfo
from app.views.mod_table import (
    ACTIVE_COLOR,
    ACTIVE_ROLE,
    GROUP_ROLE,
    IDENTIFIERS_ROLE,
    STATUS_COLUMN,
    THUMBNAIL_PATH_ROLE,
    ModTableDelegate,
    ModTableThumbnails,
    add_group_row,
    append_mod_row,
    configure_mod_table,
    identifier_lines,
    mod_table_columns,
    row_is_checked,
    set_rows_checked,
)
from app.windows.base_mods_panel import BaseModsPanel, ColumnIndex

# Item roles stored on the name cell of each row (shared ones live in mod_table)
TIMESTAMP_ROLE = Qt.ItemDataRole.UserRole + 2  # epoch of the installed version
UPDATE_AVAILABLE_ROLE = Qt.ItemDataRole.UserRole + 4  # newer version on Workshop


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

        super().__init__(
            object_name="UpdateLog",
            window_title=self.tr("Update Log"),
            title_text=self.tr("Mod Update Log"),
            details_text=self.tr(
                "Workshop mods grouped by when the installed version was published. "
                "Newest first; a mod shows 'Update available' when the Workshop has "
                "a newer version than the one on disk."
            ),
            additional_columns=mod_table_columns(),
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
        configure_mod_table(
            self.editor_table_view, self.HIDDEN_COLUMNS, self.VISIBLE_ORDER
        )
        self.editor_table_view.setItemDelegate(ModTableDelegate(self))
        self._thumbnails = ModTableThumbnails(
            self, self.editor_table_view, self.editor_model
        )
        EventBus().refresh_finished.connect(self._populate_from_metadata)

    # ------------------------------------------------------------------ setup
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

    # Rows use checkable items instead of a QCheckBox widget per row, which keeps
    # filling ~1000 rows fast; BaseModsPanel's selection helpers read them here.
    def _row_is_checked(self, row: int) -> bool:
        return row_is_checked(self.editor_model, row)

    def _set_all_checkbox_rows(self, value: bool) -> None:
        set_rows_checked(self.editor_model, lambda _row: value)

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
            self._thumbnails.schedule()

    def hideEvent(self, event: QHideEvent) -> None:
        self._thumbnails.hide_popup()
        super().hideEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._thumbnails.schedule()

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

        self._thumbnails.reset()
        self.editor_table_view.setUpdatesEnabled(False)
        try:
            self._clear_table_model()
            self.editor_table_view.clearSpans()
            self._group_rows = []
            for bucket, rows in grouped.items():
                if not rows:
                    continue
                self._group_rows.append(
                    add_group_row(
                        self.editor_model,
                        self.editor_table_view,
                        f"{self._bucket_label(bucket)}  ·  {len(rows)}",
                    )
                )
                for entry, timestamp in rows:
                    self._add_update_row(entry, timestamp, mods_by_pfid.get(entry.pfid))
        finally:
            self.editor_table_view.setUpdatesEnabled(True)
        self.apply_search_filter(self.search_input.text())
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

    def _status(
        self, update_available: bool, active: bool
    ) -> tuple[str, QColor | None]:
        """Status cell text and colour for a row."""
        parts = []
        if update_available:
            parts.append(self.tr("Update available"))
        if active:
            parts.append(self.tr("Active"))
        colour: QColor | None = None
        if update_available:
            colour = self.palette().color(QPalette.ColorRole.Highlight)
        elif active:
            colour = ACTIVE_COLOR
        return ", ".join(parts), colour

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
        name_item.setData(identifier_lines(package_id, pfid, path), IDENTIFIERS_ROLE)

        updated_item = QStandardItem(
            get_relative_time(timestamp) if timestamp else self.tr("Unknown")
        )
        if timestamp:
            updated_item.setToolTip(
                time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))
            )
        updated_item.setData(timestamp, TIMESTAMP_ROLE)

        status_text, status_colour = self._status(entry.update_available, active)
        status_item = QStandardItem(status_text)
        if status_colour is not None:
            status_item.setForeground(status_colour)

        row = append_mod_row(
            self.editor_model,
            name_item=name_item,
            authors=authors,
            package_id=package_id,
            pfid=pfid,
            versions=versions,
            source=entry.source,
            path=path,
            workshop_url=ModInfo._generate_workshop_url(pfid),
            status_item=status_item,
            updated_item=updated_item,
        )
        if metadata and metadata["preview"]:
            self._thumbnails.register_row(metadata["preview"], row)

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
            status = self.editor_model.item(row, STATUS_COLUMN)
            if status is not None:
                text, colour = self._status(
                    bool(name_item.data(UPDATE_AVAILABLE_ROLE)), active
                )
                status.setText(text)
                status.setForeground(colour or self.palette().text())
        self.editor_table_view.viewport().update()

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
        self._thumbnails.schedule()


__all__ = [
    "TIMESTAMP_ROLE",
    "UPDATE_AVAILABLE_ROLE",
    "UpdateBucket",
    "UpdateEntry",
    "UpdateLog",
    "bucket_for",
    "extract_update_entries",
]
