"""Workshop preview images for mods that are not installed, cached on disk."""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from app.utils import http
from app.utils.app_info import AppInfo
from app.utils.steam.webapi.wrapper import ISteamRemoteStorage_GetPublishedFileDetails

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def fetch_workshop_preview_urls(pfids: list[str]) -> dict[str, str]:
    """Ask the Steam Web API for the preview image URL of each published file.

    :param pfids: Published file IDs to look up.
    :return: Preview URL per published file ID that Steam returned a result for.
    """
    urls: dict[str, str] = {}
    if not pfids:
        return urls
    details, _failed, _errors = ISteamRemoteStorage_GetPublishedFileDetails(pfids)
    for entry in details or []:
        pfid = str(entry.get("publishedfileid", ""))
        if entry.get("result") != 1:
            logger.warning(f"No Workshop details for published file {pfid}")
            continue
        url = entry.get("preview_url")
        if pfid and url:
            urls[pfid] = str(url)
    return urls


def preview_cache_folder() -> Path:
    """Folder holding downloaded Workshop previews, created on demand."""
    folder = AppInfo().app_storage_folder / "cache" / "workshop_previews"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class _FetchTask(QRunnable):
    def __init__(self, cache: WorkshopPreviewCache, pfids: list[str]) -> None:
        super().__init__()
        self._cache = cache
        self._pfids = pfids

    def run(self) -> None:
        try:
            urls = fetch_workshop_preview_urls(self._pfids)
        except Exception as e:
            logger.warning(f"Could not look up Workshop previews: {e}")
            return
        for pfid, url in urls.items():
            path = self._cache.download(pfid, url)
            if path is not None:
                try:
                    self._cache.preview_ready.emit(pfid, str(path))
                except RuntimeError:
                    return


class WorkshopPreviewCache(QObject):
    """Download Workshop preview images in the background and keep them on disk.

    :meth:`cached_path` answers at once for previews fetched earlier; otherwise
    :meth:`fetch` looks the files up and ``preview_ready`` reports each one.
    """

    preview_ready = Signal(str, str)

    def __init__(self, folder: Path | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._folder = folder if folder is not None else preview_cache_folder()
        self._requested: set[str] = set()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

    def cached_path(self, pfid: str) -> Path | None:
        """The downloaded preview for ``pfid``, if there is one."""
        for ext in _IMAGE_EXTENSIONS:
            candidate = self._folder / f"{pfid}{ext}"
            if candidate.exists():
                return candidate
        return None

    def fetch(self, pfids: list[str]) -> None:
        """Look up and download previews not yet requested in this session."""
        wanted = [p for p in dict.fromkeys(pfids) if p and p not in self._requested]
        if not wanted:
            return
        self._requested.update(wanted)
        self._pool.start(_FetchTask(self, wanted))

    def download(self, pfid: str, url: str) -> Path | None:
        """Fetch one preview to the cache; returns its path, or None on failure."""
        suffix = Path(url.split("?", 1)[0]).suffix.lower()
        if suffix not in _IMAGE_EXTENSIONS:
            suffix = ".png"
        target = self._folder / f"{pfid}{suffix}"
        if target.exists():
            return target
        try:
            response = http.get(url, timeout=(5, 30))
            if response.status_code != 200 or not response.content:
                logger.warning(
                    f"Preview download for {pfid} returned HTTP {response.status_code}"
                )
                return None
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.write_bytes(response.content)
            tmp.replace(target)
        except (OSError, Exception) as e:
            logger.warning(f"Preview download for {pfid} failed: {e}")
            return None
        return target

    def wait_for_done(self, msecs: int = -1) -> bool:
        return self._pool.waitForDone(msecs)
