"""The release check runs off the GUI thread and stays quiet at start-up."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from app.utils import update_utils
from app.utils.update_utils import ReleaseProbe, UpdateManager

MODULE = "app.utils.update_utils"
RELEASE = {"tag_name": "v9.0.0", "assets": [{"name": "x", "browser_download_url": "u"}]}


@pytest.fixture
def compiled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RIMSORT_DISABLE_UPDATER", raising=False)
    monkeypatch.setattr(update_utils, "__compiled__", True, raising=False)


def _manager() -> UpdateManager:
    manager = UpdateManager(MagicMock(github_token=""), None, None)
    manager._check_needs_elevation = MagicMock(return_value=False)  # type: ignore[method-assign]
    manager._get_platform_download_url = MagicMock(  # type: ignore[method-assign]
        return_value={"url": "https://x/rimsort.zip"}
    )
    manager._handle_update_process = MagicMock()  # type: ignore[method-assign]
    return manager


def _settle(qtbot: QtBot, manager: UpdateManager) -> None:
    """Wait for the worker to finish and its queued result to be handled."""
    assert manager._release_check_thread is not None
    qtbot.waitUntil(lambda: not manager.is_checking, timeout=5000)
    qtbot.wait(50)


def _run(qtbot: QtBot, manager: UpdateManager, quiet: bool) -> None:
    manager.do_check_for_update(quiet=quiet)
    _settle(qtbot, manager)


def test_running_from_source_is_silent_at_startup_and_told_on_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RIMSORT_DISABLE_UPDATER", raising=False)
    monkeypatch.delattr(update_utils, "__compiled__", raising=False)
    manager = _manager()
    with patch(f"{MODULE}.dialogue.show_warning") as warn:
        manager.do_check_for_update(quiet=True)
        warn.assert_not_called()
        manager.do_check_for_update(quiet=False)
    assert warn.call_args.kwargs["text"] == "You are running from Python interpreter."
    assert manager._release_check_thread is None


@pytest.mark.usefixtures("compiled")
@pytest.mark.parametrize("quiet", [True, False])
def test_offline_only_nags_on_a_manual_check(qtbot: QtBot, quiet: bool) -> None:
    manager = _manager()
    with (
        patch(f"{MODULE}.probe_internet_connection", return_value=["https://a"]),
        patch(f"{MODULE}.http.get") as get,
        patch(f"{MODULE}.dialogue.show_internet_connection_error") as offline,
    ):
        _run(qtbot, manager, quiet)

    get.assert_not_called()
    assert offline.call_count == (0 if quiet else 1)


@pytest.mark.usefixtures("compiled")
def test_network_work_happens_off_the_gui_thread_and_the_prompt_on_it(
    qtbot: QtBot, qapp: Any
) -> None:
    manager = _manager()
    threads: dict[str, Any] = {}

    def fetch() -> dict[str, Any]:
        threads["fetch"] = QThread.currentThread()
        return RELEASE

    def prompt(**_kwargs: Any) -> Any:
        threads["prompt"] = QThread.currentThread()
        return QMessageBox.StandardButton.Yes

    with (
        patch(f"{MODULE}.probe_internet_connection", return_value=[]),
        patch.object(manager, "_fetch_release_data", side_effect=fetch),
        patch(f"{MODULE}.AppInfo") as app_info,
        patch(f"{MODULE}.dialogue.show_dialogue_conditional", side_effect=prompt),
    ):
        app_info.return_value.app_version = "1.0.0"
        _run(qtbot, manager, quiet=True)

    assert threads["fetch"] is not qapp.thread()
    assert threads["prompt"] is qapp.thread()
    manager._handle_update_process.assert_called_once()  # type: ignore[attr-defined]
    update_info = manager._handle_update_process.call_args.args[0]  # type: ignore[attr-defined]
    assert update_info["tag_name"] == "v9.0.0"
    assert update_info["download_url"] == "https://x/rimsort.zip"


@pytest.mark.usefixtures("compiled")
def test_up_to_date_build_is_not_prompted(qtbot: QtBot) -> None:
    manager = _manager()
    with (
        patch(f"{MODULE}.probe_internet_connection", return_value=[]),
        patch.object(manager, "_fetch_release_data", return_value=RELEASE),
        patch(f"{MODULE}.AppInfo") as app_info,
        patch(f"{MODULE}.dialogue.show_dialogue_conditional") as prompt,
    ):
        app_info.return_value.app_version = "v9.1.0-edge3+abc1234"
        _run(qtbot, manager, quiet=False)

    prompt.assert_not_called()
    manager._handle_update_process.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.usefixtures("compiled")
def test_second_check_waits_for_the_first(qtbot: QtBot) -> None:
    manager = _manager()
    with (
        patch(f"{MODULE}.probe_internet_connection", return_value=[]),
        patch.object(manager, "_fetch_release_data", return_value=RELEASE) as fetch,
        patch(f"{MODULE}.AppInfo") as app_info,
        patch(f"{MODULE}.dialogue.show_dialogue_conditional") as prompt,
    ):
        app_info.return_value.app_version = "9.0.0"
        manager.do_check_for_update(quiet=True)
        first = manager._release_check_thread
        manager.do_check_for_update(quiet=True)
        assert manager._release_check_thread is first
        _settle(qtbot, manager)

    assert fetch.call_count == 1
    prompt.assert_not_called()


def test_unknown_version_is_skipped_quietly_and_asked_about_otherwise() -> None:
    manager = _manager()
    with patch(f"{MODULE}.dialogue.show_dialogue_conditional") as ask:
        ask.return_value = QMessageBox.StandardButton.Yes
        assert manager._parse_current_version("Unknown version", quiet=True) is None
        ask.assert_not_called()
        assert str(manager._parse_current_version("Unknown version")) == "0.0.0"
    assert ReleaseProbe(["https://a"], None).release_data is None
