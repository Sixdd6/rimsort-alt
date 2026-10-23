from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QPushButton, QWidget

# Icons are drawn on a 16x16 grid and scaled to the button's icon size.
_ICON_GRID = 16.0


def _draw_checkmark(painter: QPainter, color: QColor) -> None:
    pen = QPen(color, 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    path = QPainterPath(QPointF(2.5, 8.5))
    path.lineTo(6.5, 12.5)
    path.lineTo(13.5, 4.0)
    painter.drawPath(path)


def _draw_floppy_disk(painter: QPainter, color: QColor) -> None:
    pen = QPen(color, 1.5)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    body = QPainterPath(QPointF(2.0, 2.0))
    body.lineTo(11.5, 2.0)
    body.lineTo(14.0, 4.5)
    body.lineTo(14.0, 14.0)
    body.lineTo(2.0, 14.0)
    body.closeSubpath()
    painter.drawPath(body)
    # Metal shutter at the top and the label at the bottom
    painter.drawRect(QRectF(5.0, 2.0, 5.0, 3.5))
    painter.drawRect(QRectF(4.5, 9.0, 7.0, 5.0))


class SaveButton(QPushButton):
    """
    Push button that shows whether the active mods list has unsaved changes.

    A floppy disk icon means there are changes to save; a checkmark means the
    list matches the last save. Icons follow the button's text colour so they
    suit every theme.
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._unsaved_changes = False
        self._update_icon()

    @property
    def unsaved_changes(self) -> bool:
        return self._unsaved_changes

    def set_unsaved_changes(self, unsaved: bool) -> None:
        """
        Switch between the unsaved-changes and saved icons.

        :param unsaved: True when the active list differs from the last save.
        """
        if unsaved == self._unsaved_changes:
            return
        self._unsaved_changes = unsaved
        self._update_icon()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            self._update_icon()

    def _update_icon(self) -> None:
        if self._unsaved_changes:
            self.setToolTip(self.tr("The active mods list has unsaved changes"))
        else:
            self.setToolTip(self.tr("The active mods list is saved"))
        self.setIcon(self._build_icon())

    def _build_icon(self) -> QIcon:
        size = self.iconSize()
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(round(size.width() * ratio), round(size.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size.width() / _ICON_GRID, size.height() / _ICON_GRID)
        if self._unsaved_changes:
            _draw_floppy_disk(painter, color)
        else:
            _draw_checkmark(painter, color)
        painter.end()
        return QIcon(pixmap)
