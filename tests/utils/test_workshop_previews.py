from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from pytestqt.qtbot import QtBot

from app.utils.workshop_previews import (
    WorkshopPreviewCache,
    fetch_workshop_preview_urls,
)

MODULE = "app.utils.workshop_previews"


def _details(
    *entries: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    return list(entries), [], []


def test_fetch_workshop_preview_urls_keeps_only_successful_results() -> None:
    with patch(
        f"{MODULE}.ISteamRemoteStorage_GetPublishedFileDetails",
        return_value=_details(
            {"publishedfileid": "1", "result": 1, "preview_url": "https://x/1.png"},
            {"publishedfileid": "2", "result": 9},
            {"publishedfileid": "3", "result": 1, "preview_url": ""},
        ),
    ):
        assert fetch_workshop_preview_urls(["1", "2", "3"]) == {"1": "https://x/1.png"}
    assert fetch_workshop_preview_urls([]) == {}


def test_cache_downloads_once_and_reports_the_file(
    qtbot: QtBot, tmp_path: Path
) -> None:
    cache = WorkshopPreviewCache(folder=tmp_path)
    response = MagicMock(status_code=200, content=b"\x89PNG...")
    with (
        patch(
            f"{MODULE}.ISteamRemoteStorage_GetPublishedFileDetails",
            return_value=_details(
                {
                    "publishedfileid": "42",
                    "result": 1,
                    "preview_url": "https://x/p.jpg?v=1",
                }
            ),
        ) as api,
        patch(f"{MODULE}.http.get", return_value=response) as get,
        qtbot.waitSignal(cache.preview_ready, timeout=5000) as blocker,
    ):
        cache.fetch(["42", "42"])
        cache.fetch(["42"])  # already requested: no second lookup

    assert blocker.args == ["42", str(tmp_path / "42.jpg")]
    assert (tmp_path / "42.jpg").read_bytes() == b"\x89PNG..."
    assert api.call_count == 1
    assert get.call_count == 1
    assert cache.cached_path("42") == tmp_path / "42.jpg"
    assert cache.cached_path("43") is None


def test_cache_ignores_failed_downloads(qtbot: QtBot, tmp_path: Path) -> None:
    cache = WorkshopPreviewCache(folder=tmp_path)
    received: list[Any] = []
    cache.preview_ready.connect(lambda *args: received.append(args))
    with (
        patch(
            f"{MODULE}.ISteamRemoteStorage_GetPublishedFileDetails",
            return_value=_details(
                {"publishedfileid": "7", "result": 1, "preview_url": "https://x/p.png"}
            ),
        ),
        patch(
            f"{MODULE}.http.get", return_value=MagicMock(status_code=404, content=b"")
        ),
    ):
        cache.fetch(["7"])
        assert cache.wait_for_done(5000)
        qtbot.wait(50)

    assert received == []
    assert cache.cached_path("7") is None
