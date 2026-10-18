"""
Shared pieces for mod tables built on BaseModsPanel: thumbnail loading,
the hover preview popup, group bands, and the delegate that paints the
"Mod" (thumbnail, name, author), "Status" and "Workshop" cells.

Used by the Update Log and the Use This Instead panel.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QAbstractItemModel,
    QCoreApplication,
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
    QImage,
    QMouseEvent,
    QPainter,
    QPalette,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHeaderView,
    QLabel,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.utils.generic import platform_specific_open
from app.utils.preview_image_loader import PreviewImageLoader
from app.windows.base_mods_panel import ColumnIndex, HeaderColumn

STATUS_COLUMN = ColumnIndex.WORKSHOP_PAGE.value + 1
# Workshop previews are mostly 16:9, so the thumbnail box is landscape
THUMBNAIL_WIDTH = 128
THUMBNAIL_HEIGHT = 72
ROW_HEIGHT = 80
GROUP_ROW_HEIGHT = 30
CELL_PADDING = 6
# Width of the full preview shown in the hover popup
PREVIEW_POPUP_WIDTH = 400
# Gap between the hovered Mod cell and the preview popup
_PREVIEW_POPUP_GAP = 12
_PREVIEW_HOVER_DELAY_MS = 250
# Rows past the viewport edge that also get thumbnails, so scrolling stays smooth
_THUMBNAIL_LOOKAHEAD_ROWS = 10

# Item roles stored on the name cell of each row
GROUP_ROLE = Qt.ItemDataRole.UserRole + 1  # True on a group header row
ACTIVE_ROLE = Qt.ItemDataRole.UserRole + 3  # mod is in the active list (row tint)
THUMBNAIL_PATH_ROLE = Qt.ItemDataRole.UserRole + 5  # preview image to load lazily
IDENTIFIERS_ROLE = Qt.ItemDataRole.UserRole + 6  # lines shown in the hover popup

ACTIVE_COLOR = QColor(46, 125, 50)


def mod_table_columns() -> list[HeaderColumn]:
    """BaseModsPanel's standard columns plus Status, with mod-table resize modes."""
    fit = QHeaderView.ResizeMode.ResizeToContents
    translate = QCoreApplication.translate
    return [
        (translate("ModTable", "Mod"), QHeaderView.ResizeMode.Stretch),
        translate("ModTable", "Author"),
        translate("ModTable", "Package ID"),
        translate("ModTable", "Published File Id"),
        (translate("ModTable", "Versions"), fit),
        translate("ModTable", "Downloaded"),
        (translate("ModTable", "Updated"), fit),
        (translate("ModTable", "Source"), fit),
        translate("ModTable", "Path"),
        (translate("ModTable", "Workshop"), fit),
        (translate("ModTable", "Status"), fit),
    ]


def identifier_lines(package_id: str, pfid: str, path: str) -> list[str]:
    """The identifier text shown under a mod's preview in the hover popup."""
    translate = QCoreApplication.translate
    lines = [
        translate("ModTable", "Package ID: {package_id}").format(package_id=package_id),
        translate("ModTable", "Published File ID: {pfid}").format(pfid=pfid),
    ]
    if path:
        lines.append(translate("ModTable", "Path: {path}").format(path=path))
    return lines


def append_mod_row(
    model: QStandardItemModel,
    *,
    name_item: QStandardItem,
    authors: str,
    package_id: str,
    pfid: str,
    versions: str,
    source: str,
    path: str,
    workshop_url: str,
    status_item: QStandardItem,
    updated_item: QStandardItem | None = None,
) -> int:
    """Append a mod row in BaseModsPanel's column layout plus Status.

    :return: The new row.
    """
    model.appendRow(
        [
            checkable_item(),
            name_item,
            QStandardItem(authors),
            QStandardItem(package_id),
            QStandardItem(pfid),
            QStandardItem(versions),
            QStandardItem(""),
            updated_item if updated_item is not None else QStandardItem(""),
            QStandardItem(source),
            QStandardItem(path),
            QStandardItem(workshop_url),
            status_item,
        ]
    )
    return model.rowCount() - 1


def configure_mod_table(
    view: QTableView, hidden_columns: tuple[int, ...], visible_order: tuple[int, ...]
) -> None:
    """Hide noisy columns, order the visible ones, and fix the row height.

    :param view: The table view.
    :param hidden_columns: Logical columns to hide.
    :param visible_order: Logical columns in the order they should appear.
    """
    header = view.horizontalHeader()
    for column in hidden_columns:
        view.setColumnHidden(column, True)
    for position, column in enumerate(visible_order):
        header.moveSection(header.visualIndex(column), position)
    vertical = view.verticalHeader()
    vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    vertical.setDefaultSectionSize(ROW_HEIGHT)
    vertical.hide()
    view.setShowGrid(False)
    view.setSortingEnabled(False)


def add_group_row(model: QStandardItemModel, view: QTableView, text: str) -> int:
    """Append a group band spanning the whole table.

    :param model: The table model.
    :param view: The table view, which holds the span.
    :param text: Band label.
    :return: The band's row.
    """
    items = [QStandardItem() for _ in range(model.columnCount())]
    header = items[ColumnIndex.NAME.value]
    header.setText(text)
    header.setData(True, GROUP_ROLE)
    for item in items:
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
    model.appendRow(items)
    row = model.rowCount() - 1
    view.setSpan(row, 0, 1, model.columnCount())
    view.setRowHeight(row, GROUP_ROW_HEIGHT)
    return row


def checkable_item() -> QStandardItem:
    """A check column item; replaces a QCheckBox widget per row."""
    item = QStandardItem()
    item.setCheckable(True)
    item.setCheckState(Qt.CheckState.Unchecked)
    return item


def row_is_checked(model: QStandardItemModel, row: int) -> bool:
    item = model.item(row, ColumnIndex.CHECKBOX.value)
    return item is not None and item.checkState() == Qt.CheckState.Checked


def set_rows_checked(model: QStandardItemModel, checked: Callable[[int], bool]) -> None:
    """Set every checkable row's state from ``checked(row)``."""
    for row in range(model.rowCount()):
        item = model.item(row, ColumnIndex.CHECKBOX.value)
        if item is not None and item.isCheckable():
            item.setCheckState(
                Qt.CheckState.Checked if checked(row) else Qt.CheckState.Unchecked
            )


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


class PreviewPopup(QFrame):
    """Frameless tooltip-style window showing a mod's preview and identifiers.

    The popup needs a parent widget: Wayland only positions tooltip windows
    relative to a transient parent, so a parentless popup lands anywhere.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(
            parent, Qt.WindowType.ToolTip | Qt.WindowType.WindowDoesNotAcceptFocus
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


class ModTableThumbnails(QObject):
    """Lazy thumbnails and the hover preview popup for a mod table.

    Rows register their preview path on the name item (``THUMBNAIL_PATH_ROLE``)
    and through :meth:`register_row`. Thumbnails are decoded on a background
    thread only for rows near the viewport; hovering a Mod cell shows the full
    preview beside the row.
    """

    def __init__(self, panel: QWidget, view: QTableView, model: QStandardItemModel):
        super().__init__(panel)
        self._panel = panel
        self._view = view
        self._model = model
        # Rows waiting for a thumbnail, keyed by preview image path
        self._rows: dict[str, list[int]] = {}
        self._thumbnail_loader = PreviewImageLoader(
            cache_size=1024, max_side=THUMBNAIL_WIDTH * 2, cancel_pending=False
        )
        self._thumbnail_loader.image_ready.connect(self._on_thumbnail_ready)
        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._request_timer.timeout.connect(self.request_visible)
        # Hover preview: latest-wins decoding at popup size, shown beside the row
        self._preview_loader = PreviewImageLoader(
            cache_size=64, max_side=PREVIEW_POPUP_WIDTH, cancel_pending=True
        )
        self._preview_loader.image_ready.connect(self._on_preview_ready)
        self.popup = PreviewPopup(panel)
        self._hover_row = -1
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(_PREVIEW_HOVER_DELAY_MS)
        self._hover_timer.timeout.connect(self._show_popup)
        view.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        view.setMouseTracking(True)
        view.viewport().installEventFilter(self)

    # ------------------------------------------------------------ thumbnails
    def reset(self) -> None:
        """Forget registered rows; call before the table is refilled."""
        self.hide_popup()
        self._rows = {}

    def register_row(self, preview: str, row: int) -> None:
        self._rows.setdefault(preview, []).append(row)

    def schedule(self) -> None:
        """Request thumbnails for the visible rows on the next event loop pass."""
        self._request_timer.start(0)

    def visible_rows(self) -> list[int]:
        """Rows in the viewport plus a lookahead on both sides, hidden rows skipped.

        The viewport is walked by position so filtered-out rows cost nothing.
        Before the view has laid out its rows ``rowAt`` answers -1 everywhere,
        so the rows are then estimated from the scrollbar and viewport height.
        """
        view = self._view
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
        if rows or self._model.rowCount() == 0:
            return rows
        first = view.verticalScrollBar().value()
        return [
            row
            for row in range(first, min(self._model.rowCount(), first + max_rows))
            if not view.isRowHidden(row)
        ]

    def request_visible(self) -> None:
        """Ask the loader for the previews of rows in (or near) the viewport."""
        if not self._panel.isVisible():
            return
        for row in self.visible_rows():
            name_item = self._model.item(row, ColumnIndex.NAME.value)
            if name_item is None:
                continue
            preview = name_item.data(THUMBNAIL_PATH_ROLE)
            if not preview or name_item.data(Qt.ItemDataRole.DecorationRole):
                continue
            image = self._thumbnail_loader.load(preview)
            if image is not None:
                self._set_thumbnail(name_item, image)

    def _on_thumbnail_ready(self, preview: str, image: QImage) -> None:
        for row in self._rows.get(preview, ()):
            name_item = self._model.item(row, ColumnIndex.NAME.value)
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

    # ---------------------------------------------------------- hover preview
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        try:
            viewport = self._view.viewport()
        except RuntimeError:
            # The view is being torn down; nothing left to track
            return False
        if watched is viewport:
            if event.type() == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
                self._on_hover(self._view.indexAt(event.position().toPoint()))
            elif event.type() == QEvent.Type.Leave:
                self.hide_popup()
        return super().eventFilter(watched, event)

    def _on_hover(self, index: QModelIndex) -> None:
        """Arm the preview popup for the Mod cell under the pointer."""
        name_item = (
            self._model.item(index.row(), ColumnIndex.NAME.value)
            if index.isValid() and index.column() == ColumnIndex.NAME.value
            else None
        )
        if name_item is None or name_item.data(GROUP_ROLE):
            self.hide_popup()
            return
        if index.row() == self._hover_row:
            return
        self._hover_row = index.row()
        if self.popup.isVisible():
            self._show_popup()
        else:
            self._hover_timer.start()

    def _show_popup(self) -> None:
        name_item = self._model.item(self._hover_row, ColumnIndex.NAME.value)
        if name_item is None or not self._panel.isVisible():
            return
        preview = name_item.data(THUMBNAIL_PATH_ROLE)
        image = self._preview_loader.load(preview) if preview else None
        if preview and image is None:
            # Decoding; _on_preview_ready places the popup when it lands
            return
        self._place_popup(name_item, image)

    def _on_preview_ready(self, preview: str, image: QImage) -> None:
        name_item = self._model.item(self._hover_row, ColumnIndex.NAME.value)
        if name_item is not None and name_item.data(THUMBNAIL_PATH_ROLE) == preview:
            self._place_popup(name_item, image)

    def _place_popup(self, name_item: QStandardItem, image: QImage | None) -> None:
        pixmap = (
            QPixmap.fromImage(image)
            if image is not None and not image.isNull()
            else None
        )
        self.popup.set_content(pixmap, name_item.data(IDENTIFIERS_ROLE) or [])
        view = self._view
        cell = view.visualRect(name_item.index())
        cell.moveTopLeft(view.viewport().mapToGlobal(cell.topLeft()))
        screen = QApplication.screenAt(cell.center()) or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else cell
        self.popup.move(preview_popup_position(cell, self.popup.size(), available))
        self.popup.show()

    def hide_popup(self) -> None:
        self._hover_timer.stop()
        self._hover_row = -1
        self.popup.hide()

    def _on_scrolled(self, _value: int) -> None:
        self.hide_popup()
        self.schedule()


class ModTableDelegate(QStyledItemDelegate):
    """Paints group bands, the thumbnail + name + author cell, the bold Status
    cell (coloured by its ForegroundRole) and the Workshop link cell."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        size = super().sizeHint(option, index)
        name_index = index.sibling(index.row(), ColumnIndex.NAME.value)
        height = GROUP_ROW_HEIGHT if name_index.data(GROUP_ROLE) else ROW_HEIGHT
        width = size.width()
        column = index.column()
        if column == STATUS_COLUMN:
            # Status is painted bold, so measure it that way
            font = QFont(option.font)
            font.setBold(True)
            text = str(index.data() or "")
            width = QFontMetrics(font).horizontalAdvance(text) + 2 * CELL_PADDING + 2
        elif column == ColumnIndex.WORKSHOP_PAGE.value:
            # The cell text is the URL (for CSV export); it is painted as a link
            width = (
                QFontMetrics(option.font).horizontalAdvance(self._link_text())
                + 2 * CELL_PADDING
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
        # on the narrow check column shows as a tall outlined bar. The per-cell
        # hover highlight is dropped too: the row tint is the meaningful signal.
        option = QStyleOptionViewItem(option)
        option.state = option.state & ~(
            QStyle.StateFlag.State_HasFocus | QStyle.StateFlag.State_MouseOver
        )
        name_index = index.sibling(index.row(), ColumnIndex.NAME.value)
        if name_index.data(GROUP_ROLE):
            # The row is one spanned cell starting at column 0
            text = str(name_index.data() or "") if index.column() == 0 else ""
            self._paint_group(painter, option, text)
            return
        if name_index.data(ACTIVE_ROLE):
            tint = QColor(ACTIVE_COLOR)
            tint.setAlpha(36)
            painter.fillRect(option.rect, tint)
        column = index.column()
        if column == ColumnIndex.NAME.value:
            self._paint_mod(painter, option, index)
        elif column == STATUS_COLUMN:
            self._paint_status(painter, option, index)
        elif column == ColumnIndex.WORKSHOP_PAGE.value and str(index.data() or ""):
            self._paint_link(painter, option)
        elif column == ColumnIndex.CHECKBOX.value:
            super().paint(painter, option, index)
        else:
            # Plain text cells are painted here rather than by the style, whose
            # themed item background would cover the active-row tint
            self._paint_text(painter, option, str(index.data() or ""))

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
            option.rect.adjusted(CELL_PADDING, 0, -CELL_PADDING, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )
        painter.setPen(palette.color(QPalette.ColorRole.Mid))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()

    def _paint_mod(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.save()
        rect = option.rect.adjusted(CELL_PADDING, 0, -CELL_PADDING, 0)
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
        text_rect = rect.adjusted(THUMBNAIL_WIDTH + CELL_PADDING * 2, 0, 0, 0)
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

    def _paint_text(
        self, painter: QPainter, option: QStyleOptionViewItem, text: str
    ) -> None:
        painter.save()
        painter.setFont(option.font)
        painter.setPen(option.palette.color(QPalette.ColorRole.Text))
        painter.drawText(
            option.rect.adjusted(CELL_PADDING, 0, -CELL_PADDING, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            option.fontMetrics.elidedText(
                text,
                Qt.TextElideMode.ElideRight,
                option.rect.width() - 2 * CELL_PADDING,
            ),
        )
        painter.restore()

    def _paint_status(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        text = str(index.data() or "")
        if not text:
            return
        painter.save()
        font = option.font
        font.setBold(True)
        painter.setFont(font)
        colour = index.data(Qt.ItemDataRole.ForegroundRole)
        painter.setPen(
            colour
            if isinstance(colour, QColor)
            else option.palette.color(QPalette.ColorRole.Text)
        )
        painter.drawText(
            option.rect.adjusted(CELL_PADDING, 0, -CELL_PADDING, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
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


__all__ = [
    "ACTIVE_COLOR",
    "ACTIVE_ROLE",
    "GROUP_ROLE",
    "GROUP_ROW_HEIGHT",
    "IDENTIFIERS_ROLE",
    "ROW_HEIGHT",
    "STATUS_COLUMN",
    "THUMBNAIL_PATH_ROLE",
    "ModTableDelegate",
    "ModTableThumbnails",
    "PreviewPopup",
    "add_group_row",
    "append_mod_row",
    "checkable_item",
    "configure_mod_table",
    "identifier_lines",
    "mod_table_columns",
    "preview_popup_position",
    "row_is_checked",
    "set_rows_checked",
]
