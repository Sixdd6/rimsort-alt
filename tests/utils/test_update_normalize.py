"""Normalising the extracted update must not hang when the worker is fast."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.utils.update_utils import UpdateExtractionError, UpdateManager


def _manager() -> UpdateManager:
    settings = MagicMock()
    manager = UpdateManager(settings, None, None)
    manager._show_progress_widget = MagicMock()  # type: ignore[method-assign]
    manager._hide_progress_widget = MagicMock()  # type: ignore[method-assign]
    return manager


def test_instant_worker_does_not_hang_the_event_loop(qapp: Any, tmp_path: Path) -> None:
    manager = _manager()
    with patch.object(manager, "_normalize_extracted_structure") as normalize:
        manager._normalize_structure(tmp_path, 3)
    normalize.assert_called_once_with(tmp_path, 3)
    manager._hide_progress_widget.assert_called_once()  # type: ignore[attr-defined]


def test_worker_errors_are_raised_on_the_gui_thread(qapp: Any, tmp_path: Path) -> None:
    manager = _manager()
    with (
        patch.object(
            manager, "_normalize_extracted_structure", side_effect=OSError("boom")
        ),
        pytest.raises(UpdateExtractionError, match="boom"),
    ):
        manager._normalize_structure(tmp_path, 1)
    manager._hide_progress_widget.assert_called_once()  # type: ignore[attr-defined]
