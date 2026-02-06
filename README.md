# svo2-extract

Extract raw H.265 video and sensor data from Stereolabs SVO2 files without the SDK.

## What is SVO2?

SVO2 is Stereolabs' container format for ZED camera recordings. Under the hood, it uses the [MCAP](https://mcap.dev/) format (an open source container for multimodal sensor data) to store:

- H.265/HEVC encoded stereo video (side-by-side format)
- High-frequency IMU sensor data (200 Hz)
- Camera calibration parameters
- Magnetometer and barometer data
- Frame timestamps

## Why use this tool?

The official Stereolabs SDK only provides decoded frames through `retrieveImage()`. This tool allows you to:

- **Extract raw H.265/HEVC bitstreams** directly without decoding
- **Access video data without installing the ZED SDK**
- **Work with the raw encoded data** for custom processing pipelines
- **Extract sensor data** separately from video

## Installation

```bash
# Using uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .
```

## Usage

### Extract video stream (default)

```bash
svo2-extract input.svo2 output.h265
```

### List all channels

```bash
svo2-extract --list input.svo2
```

Output:
```
File: input.svo2
Format: MCAP (SVO2)

Statistics:
  Total messages: 13407
  Start time: 5145757361000
  End time: 5197388991000

Channels:
  [1] svo_header
      Encoding: json
      Messages: 1
  [2] Camera_SN40735594/side_by_side
      Encoding: zed_sdk_encoded
      Messages: 1547
  [3] Camera_SN40735594/sensors
      Encoding: json
      Messages: 10311
```

### Extract specific channels

```bash
# Extract video
svo2-extract --video input.svo2 output.h265

# Extract sensor data
svo2-extract --sensors input.svo2 sensors.bin

# Extract by channel name or ID
svo2-extract --channel side_by_side input.svo2 output.h265
svo2-extract --channel 3 input.svo2 sensors.bin
```

### Convert to MP4 for playback

After extracting the H.265 stream, you can convert it to MP4 using ffmpeg:

```bash
ffmpeg -r 30 -i output.h265 -c:v copy output.mp4
```

### Quiet mode

```bash
svo2-extract -q input.svo2 output.h265
```

## Python API

You can also use svo2-extract as a Python library:

```python
from svo2_extract import list_channels, extract_video, extract_sensors

# List channels
info = list_channels("input.svo2")
print(info)

# Extract video
stats = extract_video("input.svo2", "output.h265")
print(f"Extracted {stats['message_count']} frames")

# Extract sensors
stats = extract_sensors("input.svo2", "sensors.bin")
```

## Technical Details

SVO2 files are MCAP containers with the following structure:

- **Container format**: MCAP (Multimodal Container for Asynchronous Processes)
- **Video encoding**: H.265/HEVC, typically 3840x1080 (side-by-side stereo)
- **Video channel**: `Camera_SN{SERIAL}/side_by_side`
- **Sensor channels**: High-frequency IMU data, integrated sensors per frame
- **Metadata**: JSON-encoded calibration, SDK version, camera info

Each video message contains one complete H.265 frame (NAL units with start codes).

## Requirements

- Python 3.8+
- mcap >= 1.0.0

## License

MIT

## See Also

- [MCAP Format](https://mcap.dev/)
- [Stereolabs ZED SDK](https://www.stereolabs.com/developers)
- [FFmpeg](https://ffmpeg.org/) for video conversion
