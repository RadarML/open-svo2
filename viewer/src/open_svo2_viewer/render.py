"""Pure rendering helpers: no tkinter dependency, unit-testable."""

import numpy as np
from numpy.typing import NDArray


def sample_viewport(
    image: NDArray[np.uint8],
    zoom: float,
    center_x: float,
    center_y: float,
    out_w: int,
    out_h: int,
    background: int = 24,
) -> NDArray[np.uint8]:
    """Nearest-neighbor resample of the region around a center point.

    Maps an output canvas of ``out_w x out_h`` pixels onto the source image
    such that the source point ``(center_x, center_y)`` lands on the canvas
    center and one source pixel covers ``zoom`` output pixels. Areas outside
    the image are filled with the ``background`` gray level.
    """
    if zoom <= 0:
        raise ValueError("zoom must be positive.")
    if out_w < 1 or out_h < 1:
        raise ValueError("Output size must be at least 1x1.")
    height, width = image.shape[:2]
    xs = np.floor(center_x + (np.arange(out_w) - (out_w - 1) / 2) / zoom).astype(np.int64)
    ys = np.floor(center_y + (np.arange(out_h) - (out_h - 1) / 2) / zoom).astype(np.int64)
    valid_x = (xs >= 0) & (xs < width)
    valid_y = (ys >= 0) & (ys < height)
    out = np.full((out_h, out_w, 3), background, dtype=np.uint8)
    if valid_x.any() and valid_y.any():
        out[np.ix_(valid_y, valid_x)] = image[np.ix_(ys[valid_y], xs[valid_x])]
    return out


def to_ppm(image: NDArray[np.uint8]) -> bytes:
    """Encode an RGB uint8 array as binary PPM (natively readable by tk)."""
    height, width = image.shape[:2]
    return b"P6 %d %d 255\n" % (width, height) + np.ascontiguousarray(image).tobytes()


def nearest_index(timestamps_ns: NDArray[np.uint64], target_ns: int) -> int:
    """Index of the timestamp nearest to ``target_ns`` in a sorted array."""
    if len(timestamps_ns) == 0:
        raise ValueError("timestamps_ns must not be empty.")
    position = int(np.searchsorted(timestamps_ns, max(target_ns, 0)))
    if position <= 0:
        return 0
    if position >= len(timestamps_ns):
        return len(timestamps_ns) - 1
    before = target_ns - int(timestamps_ns[position - 1])
    after = int(timestamps_ns[position]) - target_ns
    return position - 1 if before <= after else position


def canvas_to_source(
    px: float, py: float,
    zoom: float, center_x: float, center_y: float,
    out_w: int, out_h: int,
) -> tuple[float, float]:
    """Map a canvas pixel to source-image coordinates for a given view."""
    return (center_x + (px - (out_w - 1) / 2) / zoom,
            center_y + (py - (out_h - 1) / 2) / zoom)


def rect_view(
    zoom: float, center_x: float, center_y: float,
    out_w: int, out_h: int,
    x0: float, y0: float, x1: float, y1: float,
    max_zoom: float,
) -> tuple[float, tuple[float, float]]:
    """New (zoom, center) that magnifies a canvas-pixel rectangle to fill the canvas."""
    sx0, sy0 = canvas_to_source(
        min(x0, x1), min(y0, y1), zoom, center_x, center_y, out_w, out_h)
    sx1, sy1 = canvas_to_source(
        max(x0, x1), max(y0, y1), zoom, center_x, center_y, out_w, out_h)
    width = max(sx1 - sx0, 1e-9)
    height = max(sy1 - sy0, 1e-9)
    new_zoom = min(out_w / width, out_h / height, max_zoom)
    return new_zoom, ((sx0 + sx1) / 2, (sy0 + sy1) / 2)
