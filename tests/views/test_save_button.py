from unittest.mock import MagicMock

from PySide6.QtGui import QColor, QPalette
from pytestqt.qtbot import QtBot

from app.controllers.main_window_controller import MainWindowController
from app.models.divider import generate_divider_uuid
from app.views.save_button import SaveButton


def _icon_bytes(button: SaveButton) -> bytes:
    image = button.icon().pixmap(button.iconSize()).toImage()
    return bytes(image.constBits())


def test_save_button_starts_saved(qtbot: QtBot) -> None:
    button = SaveButton("Save")
    qtbot.addWidget(button)
    assert button.unsaved_changes is False
    assert not button.icon().isNull()
    assert button.toolTip() == "The active mods list is saved"


def test_unsaved_changes_switch_the_icon(qtbot: QtBot) -> None:
    button = SaveButton("Save")
    qtbot.addWidget(button)
    saved_icon = _icon_bytes(button)

    button.set_unsaved_changes(True)
    assert button.unsaved_changes is True
    assert button.toolTip() == "The active mods list has unsaved changes"
    assert _icon_bytes(button) != saved_icon

    button.set_unsaved_changes(False)
    assert _icon_bytes(button) == saved_icon


def test_icon_follows_the_button_text_colour(qtbot: QtBot) -> None:
    button = SaveButton("Save")
    qtbot.addWidget(button)
    palette = button.palette()
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#ff0000"))
    button.setPalette(palette)

    image = button.icon().pixmap(button.iconSize()).toImage()
    colours = {
        image.pixelColor(x, y).rgb()
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() == 255
    }
    assert colours == {QColor("#ff0000").rgb()}


def test_controller_compares_active_list_with_last_save(qtbot: QtBot) -> None:
    button = SaveButton("Save")
    qtbot.addWidget(button)
    controller = MagicMock()
    controller.main_window.save_button = button
    panel = controller.main_window.main_content_panel
    panel.active_mods_uuids_last_save = ["a", "b"]

    panel.mods_panel.active_mods_list.paths = ["a", "b", "c"]
    MainWindowController.on_update_save_button_state(controller)
    assert button.unsaved_changes is True

    panel.mods_panel.active_mods_list.paths = ["a", generate_divider_uuid(), "b"]
    MainWindowController.on_update_save_button_state(controller)
    assert button.unsaved_changes is False
