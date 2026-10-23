from PySide6.QtCore import QObject, Slot

from app.controllers.metadata_controller import MetadataController
from app.models.divider import is_divider_uuid
from app.utils.event_bus import EventBus
from app.views.main_window import MainWindow


class MainWindowController(QObject):
    def __init__(self, view: MainWindow) -> None:
        super().__init__()

        self.main_window = view
        self.metadata_controller = MetadataController.instance()

        # Create a list of buttons
        self.buttons = [
            self.main_window.refresh_button,
            self.main_window.clear_button,
            self.main_window.restore_button,
            self.main_window.sort_button,
            self.main_window.save_button,
            self.main_window.run_button,
        ]

        # Connect signals to slots
        self.connect_signals()

    def connect_signals(self) -> None:
        # Connect buttons to EventBus signals
        for button, signal in zip(
            self.buttons,
            [
                EventBus().do_refresh_mods_lists,
                EventBus().do_clear_active_mods_list,
                EventBus().do_restore_active_mods_list,
                EventBus().do_sort_active_mods_list,
                EventBus().do_save_active_mods_list,
                EventBus().do_run_game,
            ],
        ):
            button.clicked.connect(signal.emit)

        # Connect EventBus signals to slots
        EventBus().do_update_save_button_state.connect(self.on_update_save_button_state)
        EventBus().list_updated_signal.connect(self.on_update_save_button_state)
        EventBus().refresh_started.connect(self.on_refresh_started)
        EventBus().refresh_finished.connect(self.on_refresh_finished)

    @Slot()
    def on_refresh_started(self) -> None:
        self.set_buttons_enabled(False)

    @Slot()
    def on_refresh_finished(self) -> None:
        self.set_buttons_enabled(True)
        self.main_window.game_version_label.setText(
            "RimWorld version " + self.metadata_controller.game_version
        )

    @Slot()
    def on_update_save_button_state(self) -> None:
        """Show whether the active mods list differs from the last save."""
        current_mod_uuids = [
            u
            for u in self.main_window.main_content_panel.mods_panel.active_mods_list.paths
            if not is_divider_uuid(u)
        ]
        self.main_window.save_button.set_unsaved_changes(
            current_mod_uuids
            != self.main_window.main_content_panel.active_mods_uuids_last_save
        )

    def set_buttons_enabled(self, enabled: bool) -> None:
        for btn in self.buttons:
            btn.setEnabled(enabled)
