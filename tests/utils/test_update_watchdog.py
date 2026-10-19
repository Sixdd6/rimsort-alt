"""The file watchdog is stopped for an update and comes back if the launch fails."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.utils.update_utils import UpdateManager, UpdateScriptLaunchError
from app.views.main_window import MainWindow


def _manager() -> UpdateManager:
    manager = UpdateManager(MagicMock(), MagicMock(), None)
    manager._system = "Linux"
    return manager


def test_failed_script_launch_restarts_the_watchdog() -> None:
    manager = _manager()
    manager._get_script_info = MagicMock(side_effect=OSError("no script"))  # type: ignore[method-assign]

    with pytest.raises(UpdateScriptLaunchError):
        manager._launch_update_script(Path("/tmp/upd"), Path("/tmp/log"), False)

    manager.main_content.stop_watchdog_signal.emit.assert_called_once()
    manager.main_content.start_watchdog_signal.emit.assert_called_once()


def test_msi_on_the_wrong_platform_restarts_the_watchdog() -> None:
    manager = _manager()

    with pytest.raises(UpdateScriptLaunchError):
        manager._launch_update_script(
            Path("/tmp/x.msi"), Path("/tmp/log"), False, is_msi=True
        )

    manager.main_content.start_watchdog_signal.emit.assert_called_once()


def test_resume_watchdog_only_when_enabled_and_stopped() -> None:
    window = MagicMock()
    window.settings.watchdog_toggle = True
    window.watchdog_event_handler = None

    MainWindow.resume_watchdog(window)
    window.initialize_watchdog.assert_called_once()

    window.watchdog_event_handler = object()
    MainWindow.resume_watchdog(window)
    window.initialize_watchdog.assert_called_once()

    window.watchdog_event_handler = None
    window.settings.watchdog_toggle = False
    MainWindow.resume_watchdog(window)
    window.initialize_watchdog.assert_called_once()
