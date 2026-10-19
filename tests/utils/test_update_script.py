"""update.sh installs by staging and swapping, so a failure leaves the old
version runnable instead of a half-replaced folder."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "update.sh"

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("rsync") is None,
    reason="exercises the Linux branch of update.sh with rsync",
)


def _stub(folder: Path, name: str, body: str = "exit 0") -> None:
    path = folder / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


@pytest.fixture
def shims(tmp_path: Path) -> Path:
    """Neutralise the commands that touch other processes or wait."""
    folder = tmp_path / "bin"
    folder.mkdir()
    for name in ("killall", "pgrep", "sleep", "nohup"):
        _stub(folder, name)
    return folder


def _layout(tmp_path: Path) -> tuple[Path, Path]:
    install = tmp_path / "parent" / "RimSort"
    install.mkdir(parents=True)
    _stub(install, "RimSort", "echo old")
    (install / "stale.txt").write_text("stale")
    source = tmp_path / "source"
    source.mkdir()
    _stub(source, "RimSort", "echo brand new")
    (source / "fresh.txt").write_text("fresh")
    return install, source


def _run(shims: Path, install: Path, source: Path, log: Path) -> int:
    env = {**os.environ, "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}"}
    env.pop("APPIMAGE", None)
    result = subprocess.run(
        ["bash", str(SCRIPT), str(source), str(log), str(install)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result.returncode


def test_update_swaps_in_the_new_version_and_removes_leftovers(
    shims: Path, tmp_path: Path
) -> None:
    install, source = _layout(tmp_path)
    log = tmp_path / "updater.log"

    assert _run(shims, install, source, log) == 0

    assert (install / "RimSort").read_text().endswith("echo brand new\n")
    assert (install / "fresh.txt").exists()
    assert not (install / "stale.txt").exists()
    assert sorted(p.name for p in install.parent.iterdir()) == ["RimSort"]
    assert "New version installed" in log.read_text()


def test_failed_copy_leaves_the_old_version_untouched(
    shims: Path, tmp_path: Path
) -> None:
    install, source = _layout(tmp_path)
    _stub(shims, "rsync", "exit 1")
    log = tmp_path / "updater.log"

    assert _run(shims, install, source, log) == 1

    assert (install / "RimSort").read_text().endswith("echo old\n")
    assert (install / "stale.txt").exists()
    assert sorted(p.name for p in install.parent.iterdir()) == ["RimSort"]
    assert "Failed to copy update files" in log.read_text()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_unwritable_parent_falls_back_to_an_in_place_sync(
    shims: Path, tmp_path: Path
) -> None:
    install, source = _layout(tmp_path)
    log = tmp_path / "updater.log"
    install.parent.chmod(0o555)
    try:
        assert _run(shims, install, source, log) == 0
    finally:
        install.parent.chmod(0o755)

    assert (install / "RimSort").read_text().endswith("echo brand new\n")
    assert not (install / "stale.txt").exists()
    assert "in place without rollback" in log.read_text()
