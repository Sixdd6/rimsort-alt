"""Background decoding and caching for mod preview images."""

import os
from collections import OrderedDict

from loguru import logger
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader

_CacheKey = tuple[str, int, int]


class _DecodeTask(QRunnable):
    def __init__(self, loader: PreviewImageLoader, key: _CacheKey) -> None:
        super().__init__()
        self._loader = loader
        self._key = key

    def run(self) -> None:
        image = QImageReader(self._key[0]).read()
        max_side = self._loader.max_side
        if not image.isNull() and max(image.width(), image.height()) > max_side:
            image = image.scaled(
                max_side,
                max_side,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        try:
            self._loader._decoded.emit(self._key, image)
        except RuntimeError:
            logger.debug("Preview loader was deleted before a decode finished")


class PreviewImageLoader(QObject):
    """
    Decode preview images off the GUI thread and keep the most recent ones.

    ``load`` returns a cached image straight away; otherwise it starts a
    decode and ``image_ready`` is emitted with the path once it finishes. A
    null image means the file could not be read.
    """

    image_ready = Signal(str, QImage)
    _decoded = Signal(object, QImage)

    def __init__(
        self,
        cache_size: int = 64,
        max_side: int = 1024,
        parent: QObject | None = None,
    ) -> None:
        """
        :param cache_size: Number of decoded images to keep.
        :param max_side: Larger images are scaled down to fit this many pixels.
        :param parent: Optional Qt parent.
        """
        super().__init__(parent)
        self.max_side = max_side
        self._cache_size = cache_size
        self._cache: OrderedDict[_CacheKey, QImage] = OrderedDict()
        self._in_flight: set[_CacheKey] = set()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._decoded.connect(self._on_decoded)

    def load(self, path: str) -> QImage | None:
        """
        Return the cached image for ``path``, or start decoding it.

        :param path: Path of the image file.
        :return: The decoded image if cached, otherwise None.
        """
        try:
            stat = os.stat(path)
        except OSError:
            self.image_ready.emit(path, QImage())
            return None
        key = (path, stat.st_mtime_ns, stat.st_size)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        if key not in self._in_flight:
            # Drop decodes queued for images the user has already moved past
            self._pool.clear()
            self._in_flight = {key}
            self._pool.start(_DecodeTask(self, key))
        return None

    def wait_for_done(self, msecs: int = -1) -> bool:
        """
        Wait for running decodes to finish.

        :param msecs: Milliseconds to wait, or -1 to wait without a limit.
        :return: True if all decodes finished.
        """
        return self._pool.waitForDone(msecs)

    def _on_decoded(self, key: _CacheKey, image: QImage) -> None:
        self._in_flight.discard(key)
        if not image.isNull():
            self._cache[key] = image
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        self.image_ready.emit(key[0], image)
