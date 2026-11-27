"""Minimal tkinter viewer for SVO2 files, built on open-svo2."""

from .render import canvas_to_source, nearest_index, rect_view, sample_viewport, to_ppm
from .source import FrameSource

__all__ = [
    "FrameSource", "canvas_to_source", "nearest_index",
    "rect_view", "sample_viewport", "to_ppm",
]
