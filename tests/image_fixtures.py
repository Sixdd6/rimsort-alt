"""Helpers for writing small test images."""

from pathlib import Path

from PySide6.QtGui import QColor, QImage


def write_png(path: Path, width: int, height: int) -> str:
    """Write a solid-colour PNG of the given size, creating parent folders."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("green"))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path))
    return str(path)
