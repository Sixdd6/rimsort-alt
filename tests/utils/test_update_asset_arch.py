"""Release assets are matched on the machine architecture, never across it."""

import pytest

from app.utils.update_utils import normalize_machine
from tests.utils.test_appimage_update import _make_asset, _make_platform_mgr

X86_LINUX = _make_asset("RimSort-v1.17.0-Ubuntu-22.04_x86_64.tar.gz", "https://x/x86")
ARM_LINUX = _make_asset("RimSort-v1.18.0-Ubuntu-22.04_aarch64.tar.gz", "https://x/arm")
ARM_MAC = _make_asset("RimSort-v1.17.0-Darwin_arm64.tar.gz", "https://x/mac-arm")
X86_MAC = _make_asset("RimSort-v1.17.0-Darwin_x86_64.tar.gz", "https://x/mac-x86")
OLD_LINUX = _make_asset("RimSort-v1.0.0-Ubuntu.zip", "https://x/old")
X86_APPIMAGE = _make_asset("RimSort-v1.17.0-x86_64.AppImage", "https://x/appimage")


@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        ("AMD64", "x86_64"),
        ("x86_64", "x86_64"),
        ("aarch64", "arm64"),
        ("arm64", "arm64"),
        ("i686", "x86"),
        ("riscv64", "riscv64"),
    ],
)
def test_normalize_machine(machine: str, expected: str) -> None:
    assert normalize_machine(machine) == expected


def test_arm_linux_is_never_offered_an_x86_build() -> None:
    mgr = _make_platform_mgr("Linux", arch="arm64")

    assert mgr._get_platform_download_url([X86_LINUX, OLD_LINUX]) is None
    chosen = mgr._get_platform_download_url([X86_LINUX, ARM_LINUX])
    assert chosen is not None
    assert chosen["url"] == "https://x/arm"


def test_x86_mac_skips_the_arm_bundle_but_accepts_unlabelled_assets() -> None:
    mgr = _make_platform_mgr("Darwin")

    assert mgr._get_platform_download_url([ARM_MAC]) is None
    chosen = mgr._get_platform_download_url([ARM_MAC, X86_MAC])
    assert chosen is not None
    assert chosen["url"] == "https://x/mac-x86"
    legacy = _make_asset("RimSort-v1.0.0-Darwin.tar.gz", "https://x/mac-legacy")
    chosen = mgr._get_platform_download_url([legacy])
    assert chosen is not None
    assert chosen["url"] == "https://x/mac-legacy"


def test_arm_appimage_host_does_not_fall_back_to_an_x86_appimage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = _make_platform_mgr("Linux", arch="arm64", bind_appimage=True)
    monkeypatch.setenv("APPIMAGE", "/home/user/RimSort.AppImage")

    assert mgr._find_appimage_asset([X86_APPIMAGE], ["arm64", "aarch64"], True) is None
    assert mgr._get_platform_download_url([X86_APPIMAGE, X86_LINUX]) is None
