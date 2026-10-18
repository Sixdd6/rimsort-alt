import os
from pathlib import Path

from PySide6.QtGui import QColor, QImage, QPixmap
from pytestqt.qtbot import QtBot

from app.models.image_label import ImageLabel
from app.utils.preview_image_loader import PreviewImageLoader


def _write_png(path: Path, width: int, height: int) -> str:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(path))
    return str(path)


def _decode(qtbot: QtBot, loader: PreviewImageLoader, path: str) -> QImage:
    with qtbot.waitSignal(loader.image_ready, timeout=5000) as blocker:
        assert loader.load(path) is None
    assert blocker.args is not None
    assert blocker.args[0] == path
    image = blocker.args[1]
    assert isinstance(image, QImage)
    return image


def test_decodes_in_background_then_serves_from_cache(
    qtbot: QtBot, tmp_path: Path
) -> None:
    loader = PreviewImageLoader()
    path = _write_png(tmp_path / "Preview.png", 40, 20)

    image = _decode(qtbot, loader, path)
    cached = loader.load(path)

    assert (image.width(), image.height()) == (40, 20)
    assert cached is not None
    assert cached.size() == image.size()


def test_large_images_are_scaled_to_max_side(qtbot: QtBot, tmp_path: Path) -> None:
    loader = PreviewImageLoader(max_side=50)
    path = _write_png(tmp_path / "Preview.png", 200, 100)

    image = _decode(qtbot, loader, path)

    assert (image.width(), image.height()) == (50, 25)


def test_missing_file_reports_null_image(qtbot: QtBot, tmp_path: Path) -> None:
    loader = PreviewImageLoader()
    path = str(tmp_path / "missing.png")

    with qtbot.waitSignal(loader.image_ready, timeout=1000) as blocker:
        assert loader.load(path) is None

    assert blocker.args is not None
    assert blocker.args[1].isNull()


def test_changed_file_is_decoded_again(qtbot: QtBot, tmp_path: Path) -> None:
    loader = PreviewImageLoader()
    path = _write_png(tmp_path / "Preview.png", 40, 20)
    _decode(qtbot, loader, path)

    _write_png(tmp_path / "Preview.png", 30, 30)
    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    image = _decode(qtbot, loader, path)

    assert (image.width(), image.height()) == (30, 30)


def test_image_label_clear_forgets_original_pixmap(qtbot: QtBot) -> None:
    label = ImageLabel()
    qtbot.addWidget(label)
    pixmap = QPixmap(10, 10)
    pixmap.fill(QColor("blue"))
    label.setPixmap(pixmap)

    label.clear()
    label.resize(20, 20)

    assert label.pixmap().isNull()
