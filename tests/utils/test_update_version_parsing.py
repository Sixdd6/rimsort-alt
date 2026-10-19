"""Version parsing in the updater: Edge/auto builds and version.xml."""

from pathlib import Path

import pytest

from app.utils.app_info import app_version_from_file
from app.utils.update_utils import UpdateManager
from packaging import version


def _bare_manager() -> UpdateManager:
    return UpdateManager.__new__(UpdateManager)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("v1.17.0", "1.17.0"),
        ("1.17.0", "1.17.0"),
        ("v1.18.0-edge5", "1.18.0.dev5"),
        ("v1.18.0-edge5+8ba380d", "1.18.0.dev5+8ba380d"),
        ("v1.18.0-auto12", "1.18.0.dev12"),
        ("1.18.0-edge5", "1.18.0.dev5"),
    ],
)
def test_normalize_version_string(raw: str, expected: str) -> None:
    assert UpdateManager.normalize_version_string(raw) == expected


def test_edge_build_sits_between_the_stable_it_follows_and_the_one_it_precedes() -> (
    None
):
    edge = version.parse(
        UpdateManager.normalize_version_string("v1.18.0-edge5+abc1234")
    )
    assert version.parse("1.17.0") < edge < version.parse("1.18.0")


def test_parse_current_version_no_longer_degrades_edge_builds_to_zero() -> None:
    manager = _bare_manager()
    parsed = manager._parse_current_version("v1.18.0-edge5+8ba380d")

    assert parsed is not None
    assert parsed == version.parse("1.18.0.dev5+8ba380d")
    # An Edge build must not be offered the stable release it was built after
    assert parsed >= version.parse("1.17.0")


def test_parse_current_version_falls_back_for_garbage() -> None:
    assert _bare_manager()._parse_current_version("not-a-version") == version.parse(
        "0.0.0"
    )


def _write_version_xml(path: Path, ver: str, commit: str) -> Path:
    path.write_text(
        f"<version><version>{ver}</version><commit>{commit}</commit></version>",
        encoding="utf-8",
    )
    return path


def test_app_version_from_file_appends_short_commit_for_edge(tmp_path: Path) -> None:
    xml = _write_version_xml(
        tmp_path / "version.xml",
        "v1.18.0-edge5",
        "8ba380d83301e0a6dd26773089956ac8575cf493",
    )
    assert app_version_from_file(xml) == "v1.18.0-edge5+8ba380d"


def test_app_version_from_file_stable_and_missing(tmp_path: Path) -> None:
    xml = _write_version_xml(tmp_path / "version.xml", "v1.17.0", "abcdef0123456789")
    assert app_version_from_file(xml) == "v1.17.0"
    assert app_version_from_file(tmp_path / "nope.xml") == "Unknown version"
