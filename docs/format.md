# SVO2 Format Reverse Engineering

`.svo2` files are MCAP files with 5 topics:

| Topic | Description |
| ----- | ----------- |
| `svo_header` | Contains the SVO metadata in JSON format. It has only one message near the beginning of the file. |
| `svo_footer` | Contains the SVO footer in JSON format. It has only one message near the end of the file. |
| `Camera_SN(?<sn>\d+)/side_by_side` | Contains the video stream encoded as H.264/H.265, with left and right stereo images concatenated side-by-side (along the width axis). |
| `Camera_SN(?<sn>\d+)/sensors` | IMU and temperature sensor data. |
| `Camera_SN(?<sn>\d+)/sensors_integrated` | IMU and temperature sensor data which has been integrated (?) to match the camera data rate (?). |

Here, `(?<sn>\d+)` refers to the camera serial number, which is expected to be a decimal number.

Based on our analysis, `.svo2` files do not appear to have any gaps between messages which could indicate data stored outside of MCAP message payloads.

## Header

The header is a JSON object with the following fields:

- `Calib_acc`: Base64-encoded binary containing two 3×3 float32 matrices (72 bytes = 18 floats). The first matrix appears to contain bias correction terms; the second is a scale/cross-axis calibration matrix close to the identity.
- `Calib_gyro`: Base64-encoded binary containing two 3×3 float32 matrices (72 bytes = 18 floats). Same layout as `Calib_acc`: first matrix contains gyroscope offset terms, second is a full scale+cross-axis calibration matrix.
- `IMU_frequency`: IMU measurement frequency in Hz (e.g., 200.0 for ZED X).
- `ZED_SDK_version`: The version of the Zed SDK used to record the SVO as a string (e.g., `"5.0.0"`).
- `header`: A base64-encoded binary structure.

Header format: see [`metadata.Header`][open_svo2.metadata.Header] for additional details.

??? info "Header Format"

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

## Footer

The footer is a JSON object with one entry for each time series stream (`Camera_SN(?<sn>\d+)/side_by_side`, `Camera_SN(?<sn>\d+)/sensors`, `Camera_SN(?<sn>\d+)/sensors_integrated`).

- Each entry is a base64-encoded array of timestamps for the messages in the corresponding stream.
- The timestamps are stored as 64-bit integers representing milliseconds since the Unix epoch. These are presumably unsigned integers.

## Video Stream

The video payload is stored as a standard h264/h265 bitstream, with left and right cameras concatenated side by side (i.e., along the width axis). Each encoded key-frame or i-frame is stored as a separate message.

Based on analysis of a sample h265 svo recording, we believe that video frames have the following structure:

- An 8-byte header containing a 32-bit total size (excluding itself) and a 32-bit H.265 size (excluding the header and footer)
- Standard h264/h265 header and payload
- A 56-byte footer containing metadata about the frame (resolution, timestamp, frame type, etc)

See [`metadata.FrameFooter`][open_svo2.metadata.FrameFooter] for additional details.

??? info "Frame Footer Format"

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
    | 0x0dfe24  | 56      |   [00-03] width: u32 = 3840 |
    |           |         |   [04-07] height: u32 = 1080 |
    |           |         |   [08-0B] unknown: unknown = 0x5c002c00 |
    |           |         |   [0C-0F] unknown: i32 = 1 |
    |           |         |   [10-13] unknown: i32 = 2 |
    |           |         |   [14-17] unknown: i32 = -1 |
    |           |         |   [18-1F] timestamp: u64 = 1738434526000 ns |
    |           |         |   [20-23] frame_size: u32 = 917020 |
    |           |         |   [24-27] frame_type: i32 = {0 (i-frame), 3 (key-frame)} |
    |           |         |   [28-2F] last_keyframe_index: i32 |
    |           |         |   [30-33] frame_idx: int32 = 0, 1, 2, ... |
    |           |         |   [34-37] unknown: keyframe id? changes to a seemingly random value every keyframe |
    | 0x0dfe5c  | END     | |

## Sensor Data

Both `Camera_SN(?<sn>\d+)/sensors` and `Camera_SN(?<sn>\d+)/integrated_sensors` topics use the same 360-byte binary format, wrapped in a JSON object with a single `data` field containing a base64-encoded payload:

```json
{"data": "<base64>"}
```

The two topics differ only in the first 8 bytes (a type byte differs: `0x33` for `/sensors`, `0x26` for `/integrated_sensors`) and in a few fields that are zero in `/sensors` but non-zero in `/integrated_sensors` (noted below).

The `/sensors` topic streams raw IMU data at the IMU sampling rate (200 Hz for ZED X). The `/integrated_sensors` topic streams data at the camera frame rate (~30 fps), with IMU readings synchronized to camera frame timestamps.

All multi-byte values are **little-endian**.

??? info "Message Format"

    | Offset | Size | Type | Content |
    | ------ | ---- | ---- | ------- |
    | 0x000 | 1 | u8 | unknown: constant `0x01` |
    | 0x001 | 1 | u8 | topic_type: `0x33` = `/sensors`, `0x26` = `/integrated_sensors` |
    | 0x002 | 2 | u16 | unknown: constant `0xd6f5` |
    | 0x004 | 4 | u32 | unknown: constant `0x0000fffe` |
    | 0x008 | 8 | u64 | timestamp_boot_ns: internal monotonic clock timestamp in nanoseconds (not Unix epoch; differences match MCAP log_time) |
    | 0x010 | 8 | u64 | timestamp_unix_ns: Unix epoch timestamp in nanoseconds; identical to MCAP log_time |
    | 0x018 | 32 | u8[32] | unknown: constant zeros |
    | 0x038 | 4 | u32 | imu_new_sample: `1` when IMU DMP produced a new quaternion estimate, `0` otherwise |
    | 0x03C | 16 | f32[4] | orientation: quaternion (x, y, z, w); unit quaternion representing IMU orientation |
    | 0x04C | 12 | f32[3] | orientation_covariance_diagonal: (x, y, z) diagonal of orientation covariance matrix; zeros in `/sensors`, non-zero in `/integrated_sensors` |
    | 0x058 | 12 | f32[3] | angular_velocity_uncalibrated: calibrated gyroscope (x, y, z) in deg/s |
    | 0x064 | 12 | f32[3] | linear_acceleration_uncalibrated: calibrated accelerometer (x, y, z) in m/s² |
    | 0x070 | 12 | f32[3] | angular_velocity: raw gyroscope (x, y, z) in deg/s, without bias/cross-axis correction |
    | 0x07C | 12 | f32[3] | linear_acceleration: raw accelerometer (x, y, z) in m/s², without scale correction |
    | 0x088 | 12 | f32[3] | angular_velocity_covariance_diagonal: (x, y, z) diagonal of gyro covariance (rad²/s²); constant per recording |
    | 0x094 | 12 | f32[3] | linear_acceleration_covariance_diagonal: (x, y, z) diagonal of accel covariance (m²/s⁴); constant per recording |
    | 0x0A0 | 64 | f32[16] | unknown: 16 very small floats (~1e-8 to ~1e-6), varying; possibly 4×4 orientation covariance |
    | 0x0E0 | 4 | u32 | unknown: constant `0x00000100` in `/sensors`, differs in `/integrated_sensors` |
    | 0x0E4 | 4 | f32 | temperature: IMU temperature in °C |
    | 0x0E8 | 4 | f32 | unknown: `0.0` in `/sensors`; a large float (~1e10) in `/integrated_sensors` |
    | 0x0EC | 24 | f32[6] | unknown: 6 NaN values (mixed positive `0x7fc00000` and negative `0xffc00000` NaN); possibly unavailable magnetometer x,y,z uncalibrated + calibrated, or temperature sensor slots |
    | 0x104 | 4 | u32 | unknown: constant `0x00000004` |
    | 0x108 | 60 | u8[60] | unknown: mix of zeros and special values; 1 NaN (`0x7fc00000`) at `0x110`; `0x3f800000` (1.0f) at `0x120` in `/sensors`, a large float (~1e10) in `/integrated_sensors`; 2 NaN values at `0x124`–`0x12B` |
    | 0x144 | 4 | u8[4] | unknown: constant bytes `0x64 0x00 0x07 0x00` (reads as u16 pair: 100, 7) |
    | 0x148 | 16 | u8[16] | unknown: constant zeros |
    | 0x158 | 4 | u32 | unknown: constant `0x00000001` |
    | 0x15C | 4 | f32 | effective_rate: IMU effective sampling rate as a fraction of the nominal rate (observed ~0.990–1.000) |
    | 0x160 | 8 | u8[8] | unknown: constant zeros |

!!! note "Confirmed fields"

    The following fields have been confirmed against ZED SDK reference output:

    - `timestamp_unix_ns` at `0x010`: exactly matches MCAP `log_time` for all messages (zero error across 24,623 messages)
    - `angular_velocity` at `0x058`: matches `SensorsData.imu.angular_velocity`
    - `linear_acceleration` at `0x064`: matches `SensorsData.imu.linear_acceleration`
    - `angular_velocity_covariance_diagonal` at `0x088`: matches `SensorsData.imu.angular_velocity_covariance` diagonal
    - `linear_acceleration_covariance_diagonal` at `0x094`: matches `SensorsData.imu.linear_acceleration_covariance` diagonal
    - `temperature` at `0x0E4`: physically consistent (42.25°C for ZED X under normal operation)
