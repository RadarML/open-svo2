# Open SVO2

Extract raw H.265 video and sensor data from Stereolabs SVO2 files without the SDK.

SVO2 is Stereolabs' "proprietary" container format for ZED camera recordings. Under the hood, it uses the [MCAP](https://mcap.dev/) format.

## Why use this tool?

The official Stereolabs SDK only provides decoded frames through `retrieveImage()`. This tool allows you to:

- **Extract raw H.265/HEVC bitstreams** directly without decoding
- **Access video data without installing the ZED SDK**
- **Work with the raw encoded data** for custom processing pipelines

## SVO2 Format

`.svo2` files are MCAP files with 5 topics:
- `svo_header`: contains the SVO metadata in JSON format. It has only 1 message near the beginning of the file.
- `svo_footer`: contains the SVO footer in JSON format. It has only 1 message near the end of the file.
- `Camera_SN{camera_serial_number}/side_by_side`: contains the video stream encoded as h264/h265, with left and right stereo images concatenated side by side (i.e., along the width axis).
- `Camera_SN{camera_serial_number}/sensors`: TODO
- `Camera_SN{camera_serial_number}/sensors_integrated`: TODO

Based on our analysis, `.svo2` files do not appear to have any gaps between messages which could indicate data stored outside of MCAP message payloads.

### Header

The header is a JSON object with the following fields:
- `Calib_acc`: TODO
- `Calib_gyro`: TODO
- `imu_frequency_hz`: IMU measurement frequency
- `zed_sdk_version`: The version of the Zed SDK used to record the SVO as a string.
- `header`: A base64-encoded binary structure.

Header format: see `metadata.SVO2Header` for additional details.

| Offset | Size | Content |
| ------ | ---- | ------- |
| 0x00   | 4    | width: u32 = 3840 |
| 0x04   | 4    | height: u32 = 1080 |
| 0x08   | 4    | serial_number: u32 = 40735594 |
| 0x0C   | 4    | fps: u32 = 30 |
| 0x10   | 4    | unknown: u32 = 0 |
| 0x14   | 4    | unknown: u32 = 8 |
| 0x18   | 4    | unknown: u32 = 0 |
| 0x1C   | 4    | unknown: u32 = 1000 |
| 0x20   | 4    | unknown: u32 = 2001 |
| 0x24   | 48   | transform: f32[12] |
| 0x54   | 4    | unknown: u32 = 0 |
| 0x58   | 4    | unknown: u32 = 0 |
| 0x5C   | 4    | unknown: u32 = 0 |
| 0x60   | 4    | unknown: f32 = 1.0 |
| 0x64   | 4    | unknown: u32 = 5 |
| 0x68   | 4    | unknown: u32 = 0 |
| 0x6C   | 4    | unknown: u32 = 0 |
| 0x70   | 4    | unknown: u32 = 0 |
| 0x74   | 4    | unknown: u32 = 0 |
| 0x78   | 4    | unknown: u32 = 1 |
| 0x7C   | 4    | unknown: u32 = 0 |

### Footer

The footer is a JSON object with one entry for each time series stream (`Camera_SN{camera_serial_number}/side_by_side`, `Camera_SN{camera_serial_number}/sensors`, `Camera_SN{camera_serial_number}/sensors_integrated`).
- Each entry is a base64-encoded array of timestamps for the messages in the corresponding stream.
- The timestamps are stored as 64-bit integers representing milliseconds since the Unix epoch. These are presumably unsigned integers.

### Video Stream

The video payload is stored as a standard h264/h265 bitstream, with left and right cameras concatenated side by side (i.e., along the width axis). Each encoded key-frame or i-frame is stored as a separate message.

Based on analysis of a sample h265 svo recording, we believe that video frames have the following structure:
- An 8-byte header containing a 32-bit total size and a 32-bit H.265 size (excluding the header)
- Standard h264/h265 header and payload
- A 56-byte trailer containing metadata about the frame (resolution, timestamp, frame type, etc)

| Offset    | Size    | Content |
| ----------|---------|-------------------------------------------------- |
| 0x000000  | 4       | total_size: u32 = 917080 |
| 0x000004  | 4       | payload_size: u32 = 917020 |
| 0x000008  | 4       | 0x00000001 - H.265 start code |
| 0x00000C  | 24      | VPS NAL unit |
| 0x000024  | 4       | 0x00000001 - H.265 start code |
| 0x000028  | 48      | SPS NAL unit (with VUI) |
| 0x000058  | 4       | 0x00000001 - H.265 start code |
| 0x00005C  | 7       | PPS NAL unit |
| 0x000063  | 4       | 0x00000001 - H.265 start code |
| 0x000067  | 916981  | IDR slice data (video payload) |
| 0x0dfe24  | 56      | TRAILER (metadata): |
|           |         |   [00-03] width: u32 = 3840 |
|           |         |   [04-07] height: u32 = 1080 |
|           |         |   [08-0B] unknown = 0x5c002c00 |
|           |         |   [0C-0F] unknown: i32 = 1 |
|           |         |   [10-13] unknown: i32 = 2 |
|           |         |   [14-17] unknown: i32 = -1 |
|           |         |   [18-1F] timestamp: u64 = 1738434526000 ms |
|           |         |   [20-23] h265_size: u32 = 917020 |
|           |         |   [24-27] unknown: i32 = 3 |
|           |         |   [28-2F] unknown: i32 = 0 |
|           |         |   [30-37] timestamp: u64 = 1738434526000 ms |
| 0x0dfe5c  | END     | |

### Sensor Data

TODO

## See Also

- [MCAP Format](https://mcap.dev/)
- [Stereolabs ZED SDK](https://www.stereolabs.com/developers)
- [FFmpeg](https://ffmpeg.org/) for video conversion
