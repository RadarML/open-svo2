# Open SVO2

Extract raw H.265 video and sensor data from Stereolabs SVO2 files without the SDK.

SVO2 is Stereolabs' "proprietary" container format for ZED camera recordings. Under the hood, it uses the [MCAP](https://mcap.dev/) format.

## Usage

In addition to the [Python API](api.md), the `svo2` command-line tool can be used to convert SVO2 files to standard formats. For example, to extract the raw H.265 video stream:

```sh
svo2 recording.svo2 output.h265
```

The output format is inferred from the file extension, or can be specified explicitly with `--mode`. Four modes are currently supported:

| Mode | Description |
| ---- | ----------- |
| `mp4` | Extract the raw H.265 video stream and save it as an MP4 file. |
| `h265` | Extract the raw H.265 video stream and save it as a raw H.265 bitstream. |
| `npz` | Extract the raw IMU data and save it as a NumPy archive. |
| `images` | Decode RGB frames to PNG/JPEG images with exact Unix timestamps in a CSV file. |

## Decode images and seek to a time range

The Python iterator decodes H.264 or H.265 stereo frames directly, without the
ZED SDK. For example, to read ten seconds starting at 1:30:

```python
from contextlib import closing
from open_svo2 import iter_frames

with closing(iter_frames("recording.svo2", start=90, duration=10)) as frames:
    for frame in frames:
        rgb = frame.image       # uint8 RGB, side-by-side
        left = frame.left       # left camera view
        right = frame.right     # right camera view
        unix_ns = frame.timestamp_ns  # exact integer Unix timestamp
        relative_seconds = frame.timestamp
```

`start` and `duration` are seconds relative to the first video frame. The interval
is half-open: `[90, 100)`. Each call can jump independently, including backwards.
The reader seeks to the preceding keyframe using the MCAP index, decodes the
necessary pre-roll, and only returns images within the requested interval.
Memory usage does not grow with the recording length unless you retain the images.
The input must be seekable. Close the iterator when stopping early.

For interactive random access — stepping through a recording, scrubbing, or
repeatedly revisiting nearby frames — use `VideoReader` instead. It keeps the
decoder and an LRU cache of decoded frames alive between calls: cached frames
return instantly, sequential steps decode a single packet (~30 ms for a ZED X
recording), and jumps decode only from the nearest preceding keyframe.

```python
from open_svo2 import VideoReader

with VideoReader("recording.svo2", max_cache_bytes=1 << 30) as reader:
    frame = reader.get_frame(reader.index_at(90.0))  # nearest frame to 1:30
    next_frame = reader.get_frame(frame.index + 1)   # fast sequential step
    print(frame.timestamp_ns)                        # exact Unix nanoseconds
```

A minimal interactive viewer built on `VideoReader` — with real-time playback,
a timeline with buffered-frame display, millisecond timestamps, and zoom —
lives in this repository as a separate project so the core library stays
dependency-light; see [viewer/](viewer/README.md). Run it with:

```sh
uv run --project viewer svo2-viewer recording.svo2
```

To export the same range as separate left/right PNG images:

```sh
svo2 recording.svo2 frames --mode images --start 90 --duration 10 --stereo split
```

Use `--image-format jpeg` for JPEG, or `--stereo side_by_side`, `left`, or `right`
to choose another layout. Omit `--duration` to read through the end of the file.
Time-range and image options apply only to `--mode images`.

The output directory contains images named by their original frame indices and
`frames.csv` with columns `filename,index,timestamp_ns,timestamp_ms,camera`.
`timestamp_ns` is the exact integer Unix timestamp from the recording, verified
against the final `svo_footer` message. `timestamp_ms` is an exact decimal string
with six fractional digits, not a floating-point conversion. Left/right images
of the same frame have identical timestamps. Existing images and CSV files are
never overwritten; use a separate output directory for each exported range.
An empty export range raises an error.

## Why use this tool?

The official Stereolabs SDK only provides decoded frames through `retrieveImage()`. This tool allows you to:

- **Extract raw H.265/HEVC bitstreams** directly without decoding
- **Access video data without installing the ZED SDK**
- **Work with the raw encoded data** for custom processing pipelines

## See Also

- [MCAP Format](https://mcap.dev/)
- [Stereolabs ZED SDK](https://www.stereolabs.com/developers)
- [FFmpeg](https://ffmpeg.org/) for video conversion
