"""Extract metadata from SVO2 (MCAP) files."""

import base64
import json
import logging
import re
from ctypes import Structure, c_float, c_int32, c_uint32, c_uint64, sizeof
from dataclasses import dataclass
from typing import Self

import numpy as np
from jaxtyping import Float32, UInt64
from mcap.reader import McapReader, make_reader

logger = logging.getLogger("opensvo2.metadata")


class Header(Structure):
    """Memory mapping for the SVO2 binary header (128 bytes, 32 fields).

    !!! info "Field naming conventions"

        - Confirmed fields are named directly
        - Unconfirmed fields are prefixed with '_unsure_'
        - Likely correct fields are prefixed with '_likely_'

    !!! warning

        The parsed transformation matrix does not match the stereo
        transformation values given by the Zed SDK. The exact meaning and
        relationship is currently unknown.

    Attributes:
        width: Image width in pixels (for a single camera).
        height: Image height in pixels.
        serial_number: Camera serial number (e.g., 40735594).
        fps: Frames per second.
        _unsure_frame_counter: Possibly frame index or counter.
        _unsure_bit_depth: Bits per channel (typically 8).
        _unsure_exposure_mode: Exposure control mode.
        _likely_exposure_time: Likely exposure time (units unknown, observed: 1000).
        _likely_camera_model: Camera model/SKU (e.g., 2001 = ZED 2).
        _unsure_ts_sec: Timestamp seconds (often 0).
        _unsure_ts_nsec: Timestamp nanoseconds (often 0).
        _unsure_imu_status: IMU-related status flag.
        w_scale: Scale factor (typically 1.0).
        _likely_lens_id: Lens type identifier (observed: 5).
        _unsure_isp_gain: ISP gain setting.
        _unsure_isp_wb_r: White balance red channel.
        _unsure_isp_wb_b: White balance blue channel.
        _unsure_isp_gamma: Gamma correction value.
        _likely_sync_status: Sync status flag (1 = synced?).
        _unsure_padding: Padding or reserved field.
    """

    _fields_ = [
        ("width", c_uint32),
        ("height", c_uint32),
        ("serial_number", c_uint32),
        ("fps", c_uint32),
        ("_unsure_frame_counter", c_uint32),
        ("_unsure_bit_depth", c_uint32),
        ("_unsure_exposure_mode", c_uint32),
        ("_likely_exposure_time", c_uint32),
        ("_likely_camera_model", c_uint32),

        ("r00", c_float), ("r01", c_float), ("r02", c_float), ("tx", c_float),
        ("r10", c_float), ("r11", c_float), ("r12", c_float), ("ty", c_float),
        ("r20", c_float), ("r21", c_float), ("r22", c_float), ("tz", c_float),

        ("_unsure_ts_sec", c_uint32),
        ("_unsure_ts_nsec", c_uint32),
        ("_unsure_imu_status", c_uint32),
        ("w_scale", c_float),

        ("_likely_lens_id", c_uint32),
        ("_unsure_isp_gain", c_uint32),
        ("_unsure_isp_wb_r", c_uint32),
        ("_unsure_isp_wb_b", c_uint32),
        ("_unsure_isp_gamma", c_uint32),
        ("_likely_sync_status", c_uint32),
        ("_unsure_padding", c_uint32),
    ]

    @classmethod
    def from_base64(cls, data: str) -> Self:
        """Create an SVO2Header instance from encoded base64."""
        decoded = base64.b64decode(data)
        if len(decoded) != sizeof(cls):
            raise ValueError(
                f"Data length {len(decoded)} does not match SVO2Header "
                f"(requires {sizeof(cls)} bytes).")
        return cls.from_buffer_copy(decoded)


@dataclass
class Metadata:
    """SVO2 file metadata extracted from MCAP container.

    Attributes:
        imu_frequency: IMU sampling frequency in Hz (e.g., 200.0).
        zed_sdk_version: Version of the ZED SDK used to create the file.
        calib_acc_matrix1: 3x3 float32 matrix for accelerometer calibration.
        calib_acc_matrix2: 3x3 float32 matrix for accelerometer calibration.
        calib_gyro_matrix1: 3x3 float32 matrix for gyroscope calibration.
        calib_gyro_matrix2: 3x3 float32 matrix for gyroscope calibration.
        header: Parsed SVO2Header.
        version: SVO2 file format version string (e.g., "2.0.3").
        channels: Mapping of topic names to channel IDs in the MCAP file.
        timestamps: Dictionary mapping topic names to arrays of uint64
            timestamps (in nanoseconds since epoch) for each sensor reading.
    """

    imu_frequency: float
    zed_sdk_version: str
    calib_acc_matrix1: Float32[np.ndarray, "3 3"]
    calib_acc_matrix2: Float32[np.ndarray, "3 3"]
    calib_gyro_matrix1: Float32[np.ndarray, "3 3"]
    calib_gyro_matrix2: Float32[np.ndarray, "3 3"]
    header: Header
    version: str
    channels: dict[str, int]
    timestamps: dict[str, UInt64[np.ndarray, "?N"]]

    @staticmethod
    def _read_json_msg(stream, topic: str = "") -> dict:
        _schema, _channel, msg = next(stream, (None, None, None))
        if msg is None:
            raise ValueError(f"No {topic} message found in the SVO2 file.")
        return json.loads(msg.data)

    @staticmethod
    def _get_raw_data(reader: McapReader):
        footer_stream = reader.iter_messages(topics=["svo_footer"])
        footer = Metadata._read_json_msg(footer_stream, topic="svo_footer")

        header_stream = reader.iter_messages(topics=["svo_header"])
        header = Metadata._read_json_msg(header_stream, topic="svo_header")

        return header, footer

    @classmethod
    def from_mcap(cls, mcap: McapReader | str) -> Self:
        """Extract metadata from the MCAP reader.

        Args:
            mcap: file path to a svo2 mcap file or a `McapReader` handle.
        """
        if isinstance(mcap, str):
            with open(mcap, "rb") as f:
                return cls.from_mcap(make_reader(f))

        summary = mcap.get_summary()
        if summary is None:
            raise ValueError("Failed to read summary from the SVO2 file.")
        summary_short = {v.topic: k for k, v in summary.channels.items()}

        header, footer = cls._get_raw_data(mcap)
        timestamps = {
            k: np.array(v, dtype=np.uint64)
            for k, v in footer.items()}
        decoded_header = Header.from_base64(header.get("header", ""))

        # Parse calibration data (each is 18 float32s = two 3x3 matrices)
        calib_acc_raw = base64.b64decode(header.get("Calib_acc", ""))
        calib_gyro_raw = base64.b64decode(header.get("Calib_gyro", ""))

        acc_floats = np.frombuffer(calib_acc_raw, dtype=np.float32)
        gyro_floats = np.frombuffer(calib_gyro_raw, dtype=np.float32)

        return cls(
            imu_frequency=header.get("imu_frequency_hz", 0.0),
            zed_sdk_version=header.get("zed_sdk_version", "unknown"),
            header=decoded_header,
            version=header.get("version", "unknown"),
            calib_acc_matrix1=acc_floats[:9].reshape(3, 3),
            calib_acc_matrix2=acc_floats[9:].reshape(3, 3),
            calib_gyro_matrix1=gyro_floats[:9].reshape(3, 3),
            calib_gyro_matrix2=gyro_floats[9:].reshape(3, 3),
            timestamps=timestamps,
            channels=summary_short
        )

    def consistency_check(self) -> None:
        """Check parsed metadata for consistency."""
        for channel in self.channels:
            if channel.startswith("Camera"):
                m = re.match(r"Camera_SN(\d+)/(.*)", channel)
                if m is None:
                    logger.warning(
                        f"Channel name has unexpected pattern: {channel}")
                elif int(m.group(1)) != self.header.serial_number:
                    logger.warning(
                        f"Serial number mismatch: channel {channel} "
                        f"vs {self.header.serial_number} (from header)")


class FrameFooter(Structure):
    """Memory mapping for the SVO2 stereo frame footer (56 bytes, 12 fields).

    Attributes:
        width: Image width in pixels.
        height: Image height in pixels.
        _unknown_magic: Magic number (0x5c002c00).
        _unknown_1: Unknown constant (1).
        _unknown_2: Unknown constant (2).
        _unknown_3: Unknown constant (-1).
        timestamp: Timestamp in nanoseconds.
        payload_size: Size of H.264/H.265 payload in bytes.
        frame_type: 3 for key-frame, 0 for i-frame.
        last_keyframe_index: Index of the last keyframe.
        frame_id: Sequential frame index.
        _unsure_keyframe_id: Possible keyframe ID.
    """

    _fields_ = [
        ("width", c_uint32),
        ("height", c_uint32),
        ("_unknown_magic", c_uint32),
        ("_unknown_1", c_int32),
        ("_unknown_2", c_int32),
        ("_unknown_3", c_int32),
        ("timestamp", c_uint64),
        ("payload_size", c_uint32),
        ("frame_type", c_int32),
        ("last_keyframe_index", c_int32),
        ("frame_id", c_uint32),
        ("_unsure_keyframe_id", c_int32),
    ]
