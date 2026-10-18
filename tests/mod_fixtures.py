"""Lightweight stand-ins for AboutXmlMod used by table/panel tests."""

from pathlib import Path
from unittest.mock import MagicMock

from app.models.metadata.metadata_structure import AboutXmlMod


def fake_about_mod(name: str, pfid: str, path: str, preview: str = "") -> MagicMock:
    """A MagicMock that passes ``isinstance(mod, AboutXmlMod)`` with the usual fields."""
    mod = MagicMock(spec=AboutXmlMod)
    mod.name = name
    mod.published_file_id = pfid
    mod.mod_path = Path(path)
    mod.authors = ["Someone"]
    mod.package_id = f"pkg.{pfid}"
    mod.supported_versions = {"1.6"}
    mod.preview_img_path = Path(preview) if preview else None
    return mod
