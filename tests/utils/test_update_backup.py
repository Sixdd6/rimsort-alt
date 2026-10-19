"""The pre-update backup: off the GUI thread, and its failure aborts the update."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMessageBox

from app.utils.app_info import AppInfo
from app.utils.update_utils import UpdateManager

MODULE = "app.utils.update_utils"


def _manager() -> UpdateManager:
    settings = MagicMock()
    settings.enable_backup_before_update = True
    settings.max_backups = 3
    manager = UpdateManager(settings, None, None)
    manager._show_progress_widget = MagicMock()  # type: ignore[method-assign]
    manager._hide_progress_widget = MagicMock()  # type: ignore[method-assign]
    AppInfo().application_backups_folder.mkdir(parents=True, exist_ok=True)
    return manager


def _fake_zip(progress_calls: list[tuple[int, int]]) -> Any:
    def create(source: Path, target: Path, progress_callback: Any = None) -> None:
        for current in (1, 2):
            progress_callback(current, 2)
            progress_calls.append((current, 2))
        target.write_bytes(b"PK\x05\x06" + b"\0" * 18)

    return create


def test_successful_backup_lets_the_update_proceed(qapp: Any) -> None:
    manager = _manager()
    calls: list[tuple[int, int]] = []
    with (
        patch(f"{MODULE}.create_zip_backup", side_effect=_fake_zip(calls)),
        patch(f"{MODULE}.dialogue.show_dialogue_conditional") as ask,
    ):
        assert manager._create_backup_with_progress() is True

    ask.assert_not_called()
    assert calls == [(1, 2), (2, 2)]
    assert list(AppInfo().application_backups_folder.glob("RimSort_Backup_*.zip"))
    manager._hide_progress_widget.assert_called_once()  # type: ignore[attr-defined]


def test_failed_backup_aborts_unless_the_user_insists(qapp: Any) -> None:
    manager = _manager()
    with (
        patch(f"{MODULE}.create_zip_backup", side_effect=OSError("disk full")),
        patch(
            f"{MODULE}.dialogue.show_dialogue_conditional",
            return_value=QMessageBox.StandardButton.No,
        ) as ask,
    ):
        assert manager._create_backup_with_progress() is False
    assert "disk full" in ask.call_args.kwargs["information"]

    with (
        patch(f"{MODULE}.create_zip_backup", side_effect=OSError("disk full")),
        patch(
            f"{MODULE}.dialogue.show_dialogue_conditional",
            return_value=QMessageBox.StandardButton.Yes,
        ),
    ):
        assert manager._create_backup_with_progress() is True


def test_perform_update_stops_when_the_backup_is_declined(qapp: Any) -> None:
    manager = _manager()
    manager._system = "Linux"

    def fake_download(url: str) -> None:
        manager._update_content = b"x" * 2048
        manager.download_complete.emit(True, "")

    def fake_extract(is_msi: bool, is_tar_gz: bool) -> None:
        manager._extracted_path = Path("/tmp/rimsort-update")

    with (
        patch.object(manager, "_download_update_worker", side_effect=fake_download),
        patch.object(
            manager, "_extract_update_with_progress", side_effect=fake_extract
        ),
        patch(
            f"{MODULE}.dialogue.show_dialogue_conditional",
            return_value=QMessageBox.StandardButton.Yes,
        ),
        patch.object(manager, "_create_backup_with_progress", return_value=False),
        patch.object(manager, "_launch_update_script") as launch,
    ):
        manager._perform_update(
            "https://x/y.tar.gz", "v9.9.9", is_msi=False, is_tar_gz=True
        )

    launch.assert_not_called()
