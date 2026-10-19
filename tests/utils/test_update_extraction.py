"""Archive extraction runs on a worker; its result is handled on the GUI thread."""

import io
import tarfile
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QThread

from app.utils.update_utils import UpdateExtractionError, UpdateManager


def _manager(threads: dict[str, Any]) -> UpdateManager:
    manager = UpdateManager(MagicMock(), None, None)

    def hide(_widget: Any) -> None:
        threads["hide"] = QThread.currentThread()

    manager._show_progress_widget = MagicMock()  # type: ignore[method-assign]
    manager._hide_progress_widget = MagicMock(side_effect=hide)  # type: ignore[method-assign]
    return manager


def _tar_gz() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        data = b"#!/bin/sh\necho hello"
        info = tarfile.TarInfo(name="RimSort")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("RimSort/RimSort.exe", b"MZ")
    return buffer.getvalue()


def test_tar_gz_is_extracted_and_finished_on_the_gui_thread(
    qapp: Any, tmp_path: Path
) -> None:
    threads: dict[str, Any] = {}
    manager = _manager(threads)
    temp_base = tmp_path / "RimSort_update_1"
    temp_base.mkdir()

    assert manager._extract_tar_gz(_tar_gz(), temp_base) == 1

    assert (temp_base / "RimSort").read_bytes() == b"#!/bin/sh\necho hello"
    assert threads["hide"] is qapp.thread()
    assert not (tmp_path / "RimSort_update_1.tar.gz").exists()


def test_zip_is_extracted(qapp: Any, tmp_path: Path) -> None:
    manager = _manager({})
    temp_base = tmp_path / "RimSort_update_2"
    temp_base.mkdir()

    assert manager._extract_zip(_zip(), temp_base) == 1

    assert (temp_base / "RimSort" / "RimSort.exe").exists()
    assert not (tmp_path / "RimSort_update_2.zip").exists()


def test_cancelled_extraction_raises(qapp: Any, tmp_path: Path) -> None:
    manager = _manager({})
    temp_base = tmp_path / "RimSort_update_3"
    temp_base.mkdir()

    with (
        patch.object(
            manager, "_connect_extraction_cancel", side_effect=lambda t: t.stop()
        ),
        pytest.raises(UpdateExtractionError, match="aborted"),
    ):
        manager._extract_tar_gz(_tar_gz(), temp_base)

    assert not (temp_base / "RimSort").exists()
