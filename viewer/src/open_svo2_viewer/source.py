"""Background frame source: owns a VideoReader in a worker thread."""

import queue
import threading
from typing import Any

from open_svo2 import VideoReader

_STOP = object()


class FrameSource:
    """Decodes frames in a background thread so the UI never blocks.

    Seek requests are coalesced: while a decode is running, only the newest
    pending request is served afterwards. After serving a request, the worker
    prefetches the following frames while idle, so stepping forward is smooth.

    Events are delivered via `poll` (call it from the UI thread):

    - ``("ready", info)``: reader opened; ``info`` has ``frame_count``,
      ``fps``, and ``timestamps_ns`` (exact Unix nanoseconds per frame).
    - ``("frame", DecodedFrame)``: a requested frame finished decoding.
    - ``("cache", indices)``: sorted list of currently cached frame indices.
    - ``("error", message)``: opening or decoding failed.
    """

    def __init__(
        self, path: str, *,
        max_cache_bytes: int = 1 << 30, prefetch: int = 8,
    ) -> None:
        self._requests: queue.Queue = queue.Queue()
        self._events: queue.Queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, args=(path, max_cache_bytes, prefetch),
            name="svo2-decoder", daemon=True)
        self._thread.start()

    def request(self, index: int) -> None:
        """Ask for a frame; supersedes older unserved requests."""
        self._requests.put(index)

    def poll(self) -> list[tuple[str, Any]]:
        """Drain and return pending events (non-blocking)."""
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def close(self) -> None:
        """Stop the worker thread and release the reader."""
        self._requests.put(_STOP)
        self._thread.join(timeout=10)

    def _run(self, path: str, max_cache_bytes: int, prefetch: int) -> None:
        try:
            reader = VideoReader(path, max_cache_bytes=max_cache_bytes)
        except Exception as e:
            self._events.put(("error", f"Cannot open {path}: {e}"))
            return
        try:
            self._events.put(("ready", {
                "frame_count": len(reader),
                "fps": reader.fps,
                "timestamps_ns": reader.timestamps_ns.copy(),
            }))
            while True:
                batch = [self._requests.get()]
                while True:
                    try:
                        batch.append(self._requests.get_nowait())
                    except queue.Empty:
                        break
                if any(item is _STOP for item in batch):
                    return
                target = batch[-1]
                try:
                    frame = reader.get_frame(target)
                except Exception as e:
                    self._events.put(("error", f"Frame {target}: {e}"))
                    continue
                self._events.put(("frame", frame))
                self._events.put(("cache", reader.cached_indices()))
                for index in range(target + 1, min(target + 1 + prefetch, len(reader))):
                    if not self._requests.empty():
                        break
                    try:
                        reader.get_frame(index)
                    except Exception:
                        break
                self._events.put(("cache", reader.cached_indices()))
        finally:
            reader.close()
