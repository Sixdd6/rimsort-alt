from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage

from app.models.metadata.metadata_structure import ListedMod
from app.models.settings import Settings
from app.utils.generic import format_file_size
from app.views.mod_info_panel import ClickablePathLabel, ModInfoPanel
from tests.image_fixtures import write_png


@pytest.fixture
def label(qtbot: Any) -> ClickablePathLabel:
    """Create a ClickablePathLabel instance for testing.

    Args:
        qtbot: Pytest-Qt bot for widget testing.

    Returns:
        ClickablePathLabel: A configured label instance for testing.
    """
    lbl = ClickablePathLabel()
    qtbot.addWidget(lbl)
    return lbl


def test_initialization(label: ClickablePathLabel) -> None:
    """Test that ClickablePathLabel initializes with correct default values.

    Args:
        label: The ClickablePathLabel instance to test.
    """
    assert label.clickable is True
    assert label.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert label.styleSheet() == "text-decoration: underline;"
    assert label.path == ""
    assert label.text() == ""
    assert label.toolTip() == ""


def test_set_path(label: ClickablePathLabel) -> None:
    """Test setting and clearing the path property.

    Args:
        label: The ClickablePathLabel instance to test.
    """
    test_path = "/test/path"
    label.setPath(test_path)
    assert label.path == test_path
    assert label.text() == test_path
    assert label.toolTip() == f"Click to open folder: {test_path}"

    label.setPath("")
    assert label.path == ""
    assert label.text() == ""
    assert label.toolTip() == ""

    label.setPath(None)
    assert label.path == ""
    assert label.text() == ""
    assert label.toolTip() == ""


def test_set_clickable(label: ClickablePathLabel) -> None:
    """Test enabling and disabling clickable behavior.

    Args:
        label: The ClickablePathLabel instance to test.
    """
    label.setClickable(False)
    assert label.clickable is False
    assert label.cursor().shape() == Qt.CursorShape.ArrowCursor

    label.setClickable(True)
    assert label.clickable is True
    assert label.cursor().shape() == Qt.CursorShape.PointingHandCursor


@pytest.fixture
def mocked_env(monkeypatch: Any) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Create mocked environment for path-related tests.

    Args:
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        Tuple containing mocked Path, platform_specific_open, and logger objects.
    """
    mock_path = MagicMock()
    monkeypatch.setattr("app.views.mod_info_panel.Path", lambda p: mock_path)
    mock_open = MagicMock()
    monkeypatch.setattr("app.views.mod_info_panel.platform_specific_open", mock_open)
    mock_logger = MagicMock()
    monkeypatch.setattr("app.views.mod_info_panel.logger", mock_logger)
    return mock_path, mock_open, mock_logger


@pytest.mark.parametrize(
    "exists_return, is_dir_return, exists_side_effect, expected_open, expected_log_level, expected_log_msg",
    [
        (True, True, None, "/test/path", "info", "Opening mod folder: /test/path"),
        (False, None, None, None, "warning", "Mod folder does not exist: /test/path"),
        (True, False, None, None, "warning", "Path is not a directory: /test/path"),
        (
            None,
            None,
            Exception("Test exception"),
            None,
            "error",
            "Failed to open mod folder /test/path: Test exception",
        ),
    ],
)
def test_mouse_press_path_scenarios(
    label: ClickablePathLabel,
    mocked_env: tuple[MagicMock, MagicMock, MagicMock],
    qtbot: Any,
    exists_return: Any,
    is_dir_return: Any,
    exists_side_effect: Any,
    expected_open: Any,
    expected_log_level: Any,
    expected_log_msg: Any,
) -> None:
    """Test various path scenarios when clicking the label.

    This test covers different path validation scenarios:
    - Valid directory path (should open folder)
    - Non-existent path (should log warning)
    - File path instead of directory (should log warning)
    - Exception during path validation (should log error)

    Args:
        label: The ClickablePathLabel instance to test.
        mocked_env: Tuple of mocked objects (path, open, logger).
        qtbot: Pytest-Qt bot for widget testing.
        exists_return: Return value for Path.exists().
        is_dir_return: Return value for Path.is_dir().
        exists_side_effect: Side effect for Path.exists() (for exceptions).
        expected_open: Expected path to be opened, or None if no open expected.
        expected_log_level: Expected log level (info, warning, error).
        expected_log_msg: Expected log message.
    """
    mock_path, mock_open, mock_logger = mocked_env
    test_path = "/test/path"
    label.setPath(test_path)

    # Configure mock behavior based on test parameters
    if exists_return is not None:
        mock_path.exists.return_value = exists_return
    if is_dir_return is not None:
        mock_path.is_dir.return_value = is_dir_return
    if exists_side_effect is not None:
        mock_path.exists.side_effect = exists_side_effect

    # Simulate left mouse click
    qtbot.mouseClick(label, Qt.MouseButton.LeftButton)

    # Verify expected behavior
    if expected_open:
        mock_open.assert_called_once_with(expected_open)
    else:
        mock_open.assert_not_called()
    if expected_log_level:
        getattr(mock_logger, expected_log_level).assert_called_once_with(
            expected_log_msg
        )


def test_mouse_press_event_not_left_button(
    label: ClickablePathLabel,
    mocked_env: tuple[MagicMock, MagicMock, MagicMock],
    qtbot: Any,
) -> None:
    """Test that right mouse button clicks are ignored.

    # jscpd:ignore-start
        Args:
            label: The ClickablePathLabel instance to test.
            mocked_env: Tuple of mocked objects (path, open, logger).
            qtbot: Pytest-Qt bot for widget testing.
    """
    _, mock_open, _ = mocked_env
    test_path = "/test/path"
    label.setPath(test_path)
    # jscpd:ignore-end
    qtbot.mouseClick(label, Qt.MouseButton.RightButton)
    mock_open.assert_not_called()


def test_mouse_press_event_not_clickable(
    label: ClickablePathLabel,
    mocked_env: tuple[MagicMock, MagicMock, MagicMock],
    qtbot: Any,
) -> None:
    """Test that clicks are ignored when label is not clickable.

    Args:
        label: The ClickablePathLabel instance to test.
        mocked_env: Tuple of mocked objects (path, open, logger).
        qtbot: Pytest-Qt bot for widget testing.
    """
    _, mock_open, _ = mocked_env
    test_path = "/test/path"
    label.setPath(test_path)
    label.setClickable(False)
    qtbot.mouseClick(label, Qt.MouseButton.LeftButton)
    mock_open.assert_not_called()


def test_mouse_press_event_no_path(
    label: ClickablePathLabel,
    mocked_env: tuple[MagicMock, MagicMock, MagicMock],
    qtbot: Any,
) -> None:
    """Test that clicks are ignored when no path is set.

    Args:
        label: The ClickablePathLabel instance to test.
        mocked_env: Tuple of mocked objects (path, open, logger).
        qtbot: Pytest-Qt bot for widget testing.
    """
    _, mock_open, _ = mocked_env
    label.setPath("")
    qtbot.mouseClick(label, Qt.MouseButton.LeftButton)
    mock_open.assert_not_called()


@pytest.fixture
def panel(
    qapp: Any,
    mock_metadata_controller: MagicMock,
) -> Generator[ModInfoPanel]:
    """Build a real ModInfoPanel with a mocked metadata controller.

    Args:
        qapp: Qt application fixture.
        mock_metadata_controller: Mocked metadata controller singleton.

    Yields:
        A fully-constructed ModInfoPanel, cleaned up after the test.
    """
    info_panel = ModInfoPanel(
        settings=Settings(),
        metadata_controller=mock_metadata_controller,
    )
    yield info_panel
    info_panel.shutdown_folder_size_worker()


def test_folder_size_updates_asynchronously(
    panel: ModInfoPanel,
    qtbot: Any,
    tmp_path: Path,
    mock_metadata_controller: MagicMock,
) -> None:
    """Test that the folder size label is filled from a background thread."""
    (tmp_path / "file.txt").write_bytes(b"abc")
    mod = ListedMod(name="Test Mod")
    mod.mod_path = Path(str(tmp_path))
    mock_metadata_controller.mods_metadata = {str(tmp_path): mod}

    panel._set_folder_size_info(str(tmp_path))
    assert panel.mod_info_folder_size_value.text() == "Calculating..."
    qtbot.waitUntil(
        lambda: panel.mod_info_folder_size_value.text() != "Calculating...",
        timeout=5000,
    )
    assert panel.mod_info_folder_size_value.text() == format_file_size(3)


def test_folder_size_above_signed_32_bit_limit_updates_asynchronously(
    panel: ModInfoPanel,
    qtbot: Any,
    tmp_path: Path,
    mock_metadata_controller: MagicMock,
) -> None:
    large_size = 2**31
    large_file = tmp_path / "large-mod-asset.bin"
    with large_file.open("wb") as file:
        file.seek(large_size - 1)
        file.write(bytes(1))

    mod = ListedMod(name="Large Mod")
    mod.mod_path = Path(str(tmp_path))
    mock_metadata_controller.mods_metadata = {str(tmp_path): mod}

    panel._set_folder_size_info(str(tmp_path))
    qtbot.waitUntil(
        lambda: panel.mod_info_folder_size_value.text() != "Calculating...",
        timeout=5000,
    )

    assert panel.mod_info_folder_size_value.text() == format_file_size(large_size)


def test_folder_size_error_shows_not_available(
    panel: ModInfoPanel,
    qtbot: Any,
    tmp_path: Path,
    mock_metadata_controller: MagicMock,
    monkeypatch: Any,
) -> None:
    """Test that a folder size computation failure reports a fallback text."""
    mod = ListedMod(name="Test Mod")
    mod.mod_path = Path(str(tmp_path))
    mock_metadata_controller.mods_metadata = {str(tmp_path): mod}

    def raise_error(_uuid: str) -> int:
        raise OSError("boom")

    monkeypatch.setattr("app.sort.mod_sorting.path_to_folder_size", raise_error)
    panel._set_folder_size_info(str(tmp_path))
    qtbot.waitUntil(
        lambda: panel.mod_info_folder_size_value.text() != "Calculating...",
        timeout=5000,
    )
    assert panel.mod_info_folder_size_value.text() == "Not available"


def test_stale_folder_size_results_are_ignored(panel: ModInfoPanel) -> None:
    """Test that results for a previously displayed mod are discarded."""
    panel._current_uuid = "modB"
    panel._folder_size_request_id = 10
    panel.mod_info_folder_size_value.setText("Start")
    panel._on_folder_size_result("modA", 10, 12345)
    assert panel.mod_info_folder_size_value.text() == "Start"
    panel._on_folder_size_result("modB", 9, 12345)
    assert panel.mod_info_folder_size_value.text() == "Start"
    panel._on_folder_size_result("modB", 10, 12345)
    assert panel.mod_info_folder_size_value.text() == format_file_size(12345)


def _loaded_preview_size(panel: ModInfoPanel, qtbot: Any, mod_path: Path) -> QSize:
    """Load the preview for ``mod_path`` and return the decoded pixmap's size."""
    panel._load_preview_image({"path": str(mod_path)}, is_scenario=False)
    qtbot.waitUntil(lambda: panel._pending_preview_path is None, timeout=5000)
    pixmap = panel.preview_picture._original_pixmap
    assert pixmap is not None
    return pixmap.size()


def test_preview_image_is_shown_after_background_decode(
    panel: ModInfoPanel, qtbot: Any, tmp_path: Path
) -> None:
    write_png(tmp_path / "About" / "Preview.png", 64, 32)

    assert _loaded_preview_size(panel, qtbot, tmp_path) == QSize(64, 32)


def test_preview_image_is_found_regardless_of_case(
    panel: ModInfoPanel, qtbot: Any, tmp_path: Path
) -> None:
    write_png(tmp_path / "about" / "preview.PNG", 20, 10)

    assert _loaded_preview_size(panel, qtbot, tmp_path) == QSize(20, 10)


def test_stale_preview_result_is_ignored(panel: ModInfoPanel, tmp_path: Path) -> None:
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(QColor("green"))
    panel.preview_picture.clear()
    panel._pending_preview_path = str(tmp_path / "current.png")

    panel._on_preview_image_ready(str(tmp_path / "previous.png"), image)

    assert panel.preview_picture._original_pixmap is None
    assert panel._pending_preview_path == str(tmp_path / "current.png")


def test_placeholder_pixmap_is_loaded_once_and_capped(
    panel: ModInfoPanel, tmp_path: Path
) -> None:
    path = write_png(tmp_path / "missing.png", 2048, 1024)

    first = panel._placeholder_pixmap(path)
    second = panel._placeholder_pixmap(path)

    assert first is second
    assert first.size() == QSize(1024, 512)
