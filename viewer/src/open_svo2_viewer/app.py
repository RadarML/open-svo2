"""Tkinter SVO2 viewer application (stdlib UI, no extra dependencies)."""

import argparse
import math
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

import numpy as np

from .render import canvas_to_source, nearest_index, rect_view, sample_viewport, to_ppm
from .source import FrameSource

BG = "#1b1b1f"
TRACK = "#35353d"
BUFFERED = "#3f8f5f"
PLAYHEAD = "#e8e8e8"
TEXT = "#c8c8cc"
ERROR = "#e06060"
TIMELINE_HEIGHT = 46
TRACK_TOP, TRACK_BOTTOM = 16, 34
MIN_ZOOM, MAX_ZOOM = 0.02, 40.0
PLAY_TICK_MS = 15

HELP = ("Space play/pause · ←/→ frame · ⇧←/→ ±10 · scroll/pinch zoom · "
        "drag pan · ⇧drag zoom rect · f fit")
VIEW_MODES = (("side_by_side", "Side by side"), ("left", "Left"), ("right", "Right"))


class Viewer:
    """Main window: image canvas with zoom/pan, playback, timeline, time display."""

    def __init__(self, root: tk.Tk, path: str, cache_mb: int, prefetch: int) -> None:
        self.root = root
        root.title(f"SVO2 Viewer — {Path(path).name}")
        root.geometry("1280x720")
        root.configure(bg=BG)

        self.source = FrameSource(
            path, max_cache_bytes=cache_mb << 20, prefetch=prefetch)
        self.frame = None               # currently displayed DecodedFrame
        self.target = 0                 # requested frame index
        self.frame_count = 0
        self.timestamps: np.ndarray | None = None
        self.cached: list[int] = []
        self.view_mode = "side_by_side"
        self.zoom: float | None = None  # None = fit to window
        self.center = (0.0, 0.0)
        self._photo = None
        self._drag = None
        self._rect_start: tuple[int, int] | None = None
        self._rect_item = None
        self._resize_job = None
        self._error = None
        self._playing = False
        self._play_job = None
        self._play_anchor = (0.0, 0)    # (wall time, Unix ns at anchor)

        self.canvas = tk.Canvas(root, bg=BG, highlightthickness=0, cursor="tcross")
        toolbar = ttk.Frame(root)
        self.play_button = ttk.Button(
            toolbar, text="▶ Play", width=8, takefocus=0, command=self.toggle_play)
        self.play_button.pack(side="left", padx=(8, 12), pady=3)
        self._view_var = tk.StringVar(value=self.view_mode)
        for value, label in VIEW_MODES:
            ttk.Radiobutton(
                toolbar, text=label, value=value, variable=self._view_var,
                takefocus=0, command=lambda v=value: self._set_view_mode(v),
            ).pack(side="left", padx=4)
        ttk.Button(
            toolbar, text="Fit", width=4, takefocus=0, command=self._reset_zoom,
        ).pack(side="left", padx=(12, 8))
        self.timeline = tk.Canvas(
            root, height=TIMELINE_HEIGHT, bg=BG, highlightthickness=0)
        status = tk.Frame(root, bg=BG)
        self.status_left = tk.Label(
            status, bg=BG, fg=TEXT, anchor="w", font=("TkDefaultFont", 11))
        self.status_right = tk.Label(
            status, bg=BG, fg=TEXT, anchor="e", font=("TkFixedFont", 11))
        self.status_left.pack(side="left", padx=8)
        self.status_right.pack(side="right", padx=8)
        self.canvas.pack(fill="both", expand=True)
        toolbar.pack(fill="x")
        self.timeline.pack(fill="x")
        status.pack(fill="x", pady=(0, 4))
        self.status_left.configure(text=f"Opening {Path(path).name} …")

        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._zoom_step(e.x, e.y, 1.1))
        self.canvas.bind("<Button-5>", lambda e: self._zoom_step(e.x, e.y, 1 / 1.1))
        self.canvas.bind("<ButtonPress-1>", self._on_pan_start)
        self.canvas.bind("<B1-Motion>", self._on_pan_move)
        self.canvas.bind("<Shift-ButtonPress-1>", self._on_rect_start)
        self.canvas.bind("<Shift-B1-Motion>", self._on_rect_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", lambda e: self._reset_zoom())
        self.timeline.bind("<ButtonPress-1>", self._on_scrub)
        self.timeline.bind("<B1-Motion>", self._on_scrub)
        self.timeline.bind("<Configure>", lambda e: self._render_timeline())
        for key, step in (("<Left>", -1), ("<Right>", 1),
                          ("<Shift-Left>", -10), ("<Shift-Right>", 10)):
            root.bind(key, lambda e, s=step: self.seek(self.target + s))
        root.bind("<Home>", lambda e: self.seek(0))
        root.bind("<End>", lambda e: self.seek(self.frame_count - 1))
        root.bind("<space>", lambda e: self.toggle_play())
        root.bind("<Escape>", lambda e: self._cancel_rect())
        for key, mode in (("1", "side_by_side"), ("2", "left"), ("3", "right")):
            root.bind(key, lambda e, m=mode: self._set_view_mode(m))
        root.bind("f", lambda e: self._reset_zoom())
        root.bind("0", lambda e: self._reset_zoom())
        root.bind("<plus>", lambda e: self._zoom_center(1.25))
        root.bind("<minus>", lambda e: self._zoom_center(1 / 1.25))
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(30, self._poll)

    # -- frame selection and playback ---------------------------------------

    def seek(self, index: int, anchor: bool = True) -> None:
        """Request a frame; display updates when the decoder delivers it.

        User-initiated seeks re-anchor a running playback so that playback
        continues from the new position in real time.
        """
        if self.frame_count == 0:
            return
        index = max(0, min(index, self.frame_count - 1))
        if self._playing and anchor:
            self._anchor(index)
        if index == self.target and self.frame is not None \
                and self.frame.index == index:
            return
        self.target = index
        self.source.request(index)
        self._render_timeline()

    def toggle_play(self) -> None:
        """Start or stop real-time playback (frames drop if decoding lags)."""
        if self._playing:
            self._stop_playback()
            return
        if self.frame_count == 0 or self.timestamps is None:
            return
        if self.target >= self.frame_count - 1:
            self.seek(0)
        self._playing = True
        self.play_button.configure(text="⏸ Pause")
        self._anchor(self.target)
        self._play_job = self.root.after(PLAY_TICK_MS, self._play_tick)

    def _anchor(self, index: int) -> None:
        assert self.timestamps is not None
        self._play_anchor = (time.monotonic(), int(self.timestamps[index]))

    def _stop_playback(self) -> None:
        self._playing = False
        if self._play_job is not None:
            self.root.after_cancel(self._play_job)
            self._play_job = None
        self.play_button.configure(text="▶ Play")

    def _play_tick(self) -> None:
        if not self._playing or self.timestamps is None:
            return
        wall, anchor_ns = self._play_anchor
        desired_ns = anchor_ns + round((time.monotonic() - wall) * 1e9)
        index = nearest_index(self.timestamps, desired_ns)
        if index >= self.frame_count - 1:
            self.seek(self.frame_count - 1, anchor=False)
            self._stop_playback()
            return
        if index != self.target:
            self.seek(index, anchor=False)
        self._play_job = self.root.after(PLAY_TICK_MS, self._play_tick)

    def _on_scrub(self, event) -> None:
        if self.timestamps is None or len(self.timestamps) < 2:
            return
        width = max(self.timeline.winfo_width(), 2)
        fraction = min(max(event.x / (width - 1), 0.0), 1.0)
        first, last = int(self.timestamps[0]), int(self.timestamps[-1])
        target_ns = first + round(fraction * (last - first))
        self.seek(nearest_index(self.timestamps, target_ns))

    # -- event pump ----------------------------------------------------------

    def _poll(self) -> None:
        for kind, payload in self.source.poll():
            if kind == "ready":
                self.frame_count = payload["frame_count"]
                self.timestamps = payload["timestamps_ns"]
                self.seek(0)
                self.source.request(0)
            elif kind == "frame":
                shown = self.frame.index if self.frame is not None else -1
                # During playback, show every newer frame on the way to the
                # target, so lagging decodes still animate smoothly.
                accept = payload.index == self.target or (
                    self._playing and shown < payload.index <= self.target)
                if accept:
                    self.frame = payload
                    self._error = None
                    self._render_image()
                    self._render_status()
                    self._render_timeline()
            elif kind == "cache":
                self.cached = payload
                self._render_timeline()
            elif kind == "error":
                self._error = payload
                self._render_status()
        self.root.after(30, self._poll)

    def _on_close(self) -> None:
        self._stop_playback()
        self.source.close()
        self.root.destroy()

    # -- image view ----------------------------------------------------------

    def _current_image(self) -> np.ndarray | None:
        if self.frame is None:
            return None
        if self.view_mode == "left":
            return self.frame.left
        if self.view_mode == "right":
            return self.frame.right
        return self.frame.image

    def _fit_zoom(self, image: np.ndarray, w: int, h: int) -> float:
        return min(w / image.shape[1], h / image.shape[0])

    def _effective_view(self, image, w, h) -> tuple[float, float, float]:
        if self.zoom is None:
            return (self._fit_zoom(image, w, h),
                    image.shape[1] / 2, image.shape[0] / 2)
        return self.zoom, self.center[0], self.center[1]

    def _render_image(self) -> None:
        image = self._current_image()
        if image is None:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w < 2 or h < 2:
            return
        zoom, cx, cy = self._effective_view(image, w, h)
        out = sample_viewport(image, zoom, cx, cy, w, h)
        self._photo = tk.PhotoImage(data=to_ppm(out))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
        self._rect_item = None
        if self._rect_start is not None:
            self._rect_item = self.canvas.create_rectangle(
                *self._rect_start, *self._rect_start,
                outline=PLAYHEAD, dash=(4, 3))

    def _set_view_mode(self, mode: str) -> None:
        self._view_var.set(mode)
        if mode != self.view_mode:
            self.view_mode = mode
            self.zoom = None
            self._render_image()
            self._render_status()

    def _reset_zoom(self) -> None:
        self.zoom = None
        self._render_image()
        self._render_status()

    def _zoom_step(self, px: int, py: int, factor: float) -> None:
        image = self._current_image()
        if image is None:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        zoom, cx, cy = self._effective_view(image, w, h)
        new_zoom = min(max(zoom * factor, MIN_ZOOM), MAX_ZOOM)
        # Keep the source point under the cursor stationary.
        wx, wy = canvas_to_source(px, py, zoom, cx, cy, w, h)
        self.zoom = new_zoom
        self.center = (wx - (px - (w - 1) / 2) / new_zoom,
                       wy - (py - (h - 1) / 2) / new_zoom)
        self._render_image()
        self._render_status()

    def _zoom_center(self, factor: float) -> None:
        self._zoom_step(self.canvas.winfo_width() // 2,
                        self.canvas.winfo_height() // 2, factor)

    def _on_wheel(self, event) -> None:
        # Mouse wheels report ±120 per notch; trackpad scroll and pinch
        # (delivered as scroll by Tk aqua) report small continuous deltas.
        delta = event.delta / 120 if abs(event.delta) >= 120 else event.delta
        if delta:
            self._zoom_step(event.x, event.y, math.exp(delta * 0.06))

    def _on_pan_start(self, event) -> None:
        image = self._current_image()
        if image is None:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        zoom, cx, cy = self._effective_view(image, w, h)
        self.zoom = zoom
        self.center = (cx, cy)
        self._drag = (event.x, event.y, cx, cy, zoom)

    def _on_pan_move(self, event) -> None:
        if self._drag is None:
            return
        x0, y0, cx, cy, zoom = self._drag
        self.center = (cx - (event.x - x0) / zoom, cy - (event.y - y0) / zoom)
        self._render_image()

    # -- rectangle zoom ------------------------------------------------------

    def _on_rect_start(self, event) -> None:
        if self.frame is None:
            return
        self._drag = None
        self._rect_start = (event.x, event.y)
        self._rect_item = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline=PLAYHEAD, dash=(4, 3))

    def _on_rect_move(self, event) -> None:
        if self._rect_start is not None and self._rect_item is not None:
            self.canvas.coords(
                self._rect_item, *self._rect_start, event.x, event.y)

    def _on_release(self, event) -> None:
        self._drag = None
        if self._rect_start is None:
            return
        x0, y0 = self._rect_start
        self._cancel_rect()
        if abs(event.x - x0) < 8 or abs(event.y - y0) < 8:
            return
        image = self._current_image()
        if image is None:
            return
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        zoom, cx, cy = self._effective_view(image, w, h)
        self.zoom, self.center = rect_view(
            zoom, cx, cy, w, h, x0, y0, event.x, event.y, MAX_ZOOM)
        self._render_image()
        self._render_status()

    def _cancel_rect(self) -> None:
        if self._rect_item is not None:
            self.canvas.delete(self._rect_item)
        self._rect_start = None
        self._rect_item = None

    def _on_resize(self, _event) -> None:
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(40, self._render_image)

    # -- timeline and status ---------------------------------------------------

    def _render_timeline(self) -> None:
        c = self.timeline
        c.delete("all")
        w = c.winfo_width()
        if w < 2 or self.timestamps is None or self.frame_count == 0:
            return
        first, last = int(self.timestamps[0]), int(self.timestamps[-1])
        span = max(last - first, 1)

        def x_of(index: int) -> int:
            return round((int(self.timestamps[index]) - first) / span * (w - 1))

        c.create_rectangle(0, TRACK_TOP, w, TRACK_BOTTOM, fill=TRACK, outline="")
        if self.cached:
            # Aggregate cached frames into contiguous pixel spans.
            pixels = sorted({x_of(i) for i in self.cached})
            start = previous = pixels[0]
            for px in pixels[1:] + [pixels[-1] + 2]:
                if px > previous + 1:
                    c.create_rectangle(
                        start, TRACK_TOP, previous + 1, TRACK_BOTTOM,
                        fill=BUFFERED, outline="")
                    start = px
                previous = px
        x = x_of(self.target)
        c.create_line(x, 4, x, TIMELINE_HEIGHT - 4, fill=PLAYHEAD, width=2)
        duration_ms = (last - first) // 10**6
        c.create_text(4, 8, anchor="w", fill=TEXT, text="0:00",
                      font=("TkDefaultFont", 9))
        c.create_text(
            w - 4, 8, anchor="e", fill=TEXT,
            text=f"{duration_ms // 60_000}:{duration_ms % 60_000 / 1000:06.3f}",
            font=("TkDefaultFont", 9))

    def _render_status(self) -> None:
        if self._error is not None:
            self.status_left.configure(text=self._error, fg=ERROR)
            return
        if self.frame is None or self.timestamps is None:
            return
        image = self._current_image()
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        zoom = self.zoom if self.zoom is not None else (
            self._fit_zoom(image, w, h) if image is not None and w > 1 else 1.0)
        self.status_left.configure(
            fg=TEXT,
            text=(f"Frame {self.frame.index + 1}/{self.frame_count} · "
                  f"Zoom {zoom * 100:.0f}%    {HELP}"))
        ns = self.frame.timestamp_ns
        rel_ms = (ns - int(self.timestamps[0])) // 10**6
        wall = datetime.fromtimestamp(ns // 10**9)
        self.status_right.configure(text=(
            f"t +{rel_ms // 1000}.{rel_ms % 1000:03d} s   "
            f"{wall:%Y-%m-%d %H:%M:%S}.{(ns % 10**9) // 10**6:03d}   "
            f"unix {ns // 10**6} ms"))


def main() -> None:
    """Entry point for the `svo2-viewer` command."""
    parser = argparse.ArgumentParser(
        description="Minimal SVO2 viewer: playback, scrubbing, zoom, "
                    "exact millisecond timestamps.")
    parser.add_argument("path", help="Path to the SVO2 file.")
    parser.add_argument(
        "--cache-mb", type=int, default=1024,
        help="Decoded-frame cache budget in MiB (default: 1024).")
    parser.add_argument(
        "--prefetch", type=int, default=8,
        help="Frames to prefetch ahead of the current one (default: 8).")
    args = parser.parse_args()
    if args.cache_mb <= 0 or args.prefetch < 0:
        parser.error("--cache-mb must be positive and --prefetch non-negative.")

    root = tk.Tk()
    Viewer(root, args.path, args.cache_mb, args.prefetch)
    root.mainloop()


if __name__ == "__main__":
    main()
