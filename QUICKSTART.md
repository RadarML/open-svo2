# Quick Start Guide

## Installation

```bash
# Clone or navigate to the project directory
cd /path/to/svo2-extract

# Install with uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .
```

## CLI Usage

### Extract video stream (most common)
```bash
svo2-extract input.svo2 output.h265
```

### List channels to see what's available
```bash
svo2-extract --list input.svo2
```

### Extract specific data
```bash
# Video (default)
svo2-extract --video input.svo2 output.h265

# High-frequency sensor data
svo2-extract --sensors input.svo2 sensors.bin

# By channel ID or name
svo2-extract --channel 3 input.svo2 output.bin
svo2-extract --channel integrated_sensors input.svo2 data.bin
```

### Quiet mode
```bash
svo2-extract -q input.svo2 output.h265
```

## Python API Usage

```python
from svo2_extract import list_channels, extract_video, extract_sensors

# List all channels
info = list_channels("input.svo2")
print(f"Total messages: {info['statistics']['total_messages']}")

# Extract video
stats = extract_video("input.svo2", "output.h265")
print(f"Extracted {stats['message_count']} frames")

# Extract sensors (quiet mode)
stats = extract_sensors("input.svo2", "sensors.bin", verbose=False)
```

See [examples/basic_usage.py](examples/basic_usage.py) for more examples.

## Converting to MP4

After extracting the H.265 stream, convert to MP4 for playback:

```bash
# Set framerate (e.g., 30fps) and copy video without re-encoding
ffmpeg -r 30 -i output.h265 -c:v copy output.mp4
```

## What You Get

From a typical SVO2 file:

- **Video**: Raw H.265/HEVC stereo stream (3840x1080 side-by-side)
- **Sensors**: High-frequency IMU data (200 Hz)
- **Metadata**: Camera calibration, timestamps, SDK version
- **Per-frame data**: Integrated sensor readings synchronized with video

## Technical Details

SVO2 files use the MCAP container format. Each video message contains a complete H.265 frame with NAL unit start codes. The format is:

```
SVO2 = MCAP Container
├── svo_header (JSON metadata)
├── side_by_side (H.265 video frames)
├── sensors (High-frequency IMU @ 200Hz)
├── integrated_sensors (Per-frame sensor data)
└── svo_footer (JSON metadata)
```

## Troubleshooting

**Import Error**: Make sure old `.py` files aren't conflicting:
```bash
# Move or delete old scripts
mv svo2_extract.py svo2_extract.py.old
```

**CLI Not Found**: Reinstall the package:
```bash
uv pip uninstall svo2-extract
uv pip install -e .
```

**Invalid NAL Units**: These warnings are normal when converting to MP4. The video will still work.
