# Open SVO2 Viewer

A minimal viewer for SVO2 files, built as a separate project on top of
[open-svo2](../README.md) so that the core library carries no UI dependencies.
The UI uses only `tkinter` from the Python standard library — the viewer adds
**no dependencies** beyond `open-svo2` itself (your Python must include Tk
support, which the standard installers and uv-managed Pythons do).

## Usage

From the repository root:

```sh
uv run --project viewer svo2-viewer recording.svo2
```

Options: `--cache-mb` (decoded-frame cache budget, default 1024 MiB) and
`--prefetch` (frames decoded ahead of the playhead, default 8).

## Features

- **Play/Pause**: real-time playback paced by the recording's own timestamps
  (wall-clock anchored). If decoding is slower than real time, display frames
  are dropped so playback never falls behind. Space or the toolbar button
  toggles playback; playing at the end restarts from the beginning. Scrubbing
  or stepping during playback re-anchors it at the new position.
- **Scrubbing**: click or drag on the timeline; decoding happens on a
  background thread via `open_svo2.VideoReader`, so the UI never blocks.
  Cached frames appear instantly; sequential steps decode in ~30 ms.
- **Timeline**: green spans show buffered (cached) frames; the white playhead
  marks the current frame.
- **Time display**: the status bar shows the relative time, the wall-clock
  time, and the Unix timestamp from the recording, all with millisecond
  precision. (For full-nanosecond exact timestamps use the library API or the
  CSV image export.)
- **Zoom and pan**: scroll or pinch to zoom at the cursor, drag to pan,
  Shift+drag to zoom into a rectangle, double-click or the Fit button to fit.
  Note: Tk 8.6 on macOS does not deliver native pinch gestures to
  applications; two-finger trackpad scrolling zooms instead and serves as the
  pinch equivalent.
- **View switching**: toolbar buttons (or keys `1`/`2`/`3`) select the
  side-by-side, left, or right view.

## Key bindings

| Key | Action |
| --- | ------ |
| `Space` | Play / pause |
| `←` / `→` | Previous / next frame |
| `⇧←` / `⇧→` | Jump 10 frames |
| `Home` / `End` | First / last frame |
| `1` / `2` / `3` | Side-by-side / left / right view |
| Mouse wheel / trackpad scroll | Zoom at cursor |
| Drag | Pan |
| `⇧` + drag | Zoom into the selected rectangle |
| `Esc` | Cancel rectangle selection |
| `f`, `0`, double-click | Fit to window |
| `+` / `-` | Zoom at center |
