"""Staged update files are removed when the update does not go ahead."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMessageBox

from app.utils.update_utils import (
    UPDATE_TEMP_DIR_PREFIX,
    UpdateExtractionError,
    UpdateManager,
    UpdateScriptLaunchError,
)

MODULE = "app.utils.update_utils"


def _manager() -> UpdateManager:
    settings = MagicMock()
    settings.enable_backup_before_update = False
    manager = UpdateManager(settings, None, None)
    manager._system = "Linux"
    manager._check_needs_elevation = MagicMock(return_value=False)  # type: ignore[method-assign]
    manager._prepare_update_log = MagicMock(return_value=Path("/tmp/log"))  # type: ignore[method-assign]
    return manager


def _perform(
    manager: UpdateManager,
    staged: Path,
    answer: Any = QMessageBox.StandardButton.Yes,
    launch: Any = None,
    extract_error: Exception | None = None,
    cancel: bool = False,
) -> MagicMock:
    def fake_download(url: str) -> None:
        manager._update_content = b"x" * 2048
        manager.download_complete.emit(True, "")

    def fake_extract(is_msi: bool, is_tar_gz: bool) -> None:
        staged.mkdir(parents=True, exist_ok=True)
        (staged / "RimSort").write_text("new")
        manager._extracted_path = staged
        if cancel:
            manager._on_download_cancel()
        if extract_error is not None:
            raise extract_error

    with (
        patch.object(manager, "_download_update_worker", side_effect=fake_download),
        patch.object(
            manager, "_extract_update_with_progress", side_effect=fake_extract
        ),
        patch(f"{MODULE}.dialogue.show_dialogue_conditional", return_value=answer),
        patch(f"{MODULE}.dialogue.show_warning") as warn,
        patch.object(manager, "_launch_update_script", side_effect=launch),
    ):
        manager._perform_update("https://x/y.tar.gz", "v9.9.9", False, False, True)
    return warn


def test_declined_update_removes_the_extracted_files(qapp: Any, tmp_path: Path) -> None:
    manager = _manager()
    staged = tmp_path / f"{UPDATE_TEMP_DIR_PREFIX}1"

    warn = _perform(manager, staged, answer=QMessageBox.StandardButton.No)

    assert not staged.exists()
    assert manager._extracted_path is None
    assert manager._update_content is None
    warn.assert_not_called()


def test_failed_launch_removes_the_extracted_files(qapp: Any, tmp_path: Path) -> None:
    manager = _manager()
    staged = tmp_path / f"{UPDATE_TEMP_DIR_PREFIX}2"

    warn = _perform(manager, staged, launch=UpdateScriptLaunchError("no sh"))

    assert not staged.exists()
    warn.assert_called_once()


def test_cancelled_extraction_cleans_up_without_an_error_dialog(
    qapp: Any, tmp_path: Path
) -> None:
    manager = _manager()
    staged = tmp_path / f"{UPDATE_TEMP_DIR_PREFIX}3"

    warn = _perform(
        manager, staged, extract_error=UpdateExtractionError("aborted"), cancel=True
    )

    assert not staged.exists()
    warn.assert_not_called()


def test_successful_launch_keeps_the_files_for_the_script(
    qapp: Any, tmp_path: Path
) -> None:
    manager = _manager()
    staged = tmp_path / f"{UPDATE_TEMP_DIR_PREFIX}4"

    def launched(*_args: Any, **_kwargs: Any) -> None:
        manager._update_launched = True

    _perform(manager, staged, launch=launched)

    assert (staged / "RimSort").exists()


def test_discard_removes_the_temp_folder_around_a_saved_msi(tmp_path: Path) -> None:
    manager = _manager()
    folder = tmp_path / f"{UPDATE_TEMP_DIR_PREFIX}5"
    folder.mkdir()
    msi = folder / "RimSort_Update.msi"
    msi.write_bytes(b"msi")
    manager._extracted_path = msi

    manager._discard_update_files()

    assert not folder.exists()


def test_cancel_button_stops_the_extraction_thread() -> None:
    manager = _manager()
    manager._progress_widget = MagicMock()
    thread = MagicMock()

    manager._connect_extraction_cancel(thread)

    connected = [
        c.args[0]
        for c in manager._progress_widget.cancel_requested.connect.call_args_list
    ]
    assert thread.stop in connected
    assert manager._on_download_cancel in connected
