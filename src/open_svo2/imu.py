"""IMU data."""

from dataclasses import dataclass

import numpy as np
from jaxtyping import Float32


@dataclass
class IMUData:
    """Zed IMU data.

    Attributes:
        timestamp: IMU measurement timestamp in seconds.
        accel: Linear acceleration in m/s^2, in the Zed camera coordinate
            frame, without calibration.
        avel: Angular velocity in deg/s, in the Zed camera coordinate frame,
            without calibration.
    """

    timestamp: np.float64
    accel: Float32[np.ndarray, "3"]
    avel: Float32[np.ndarray, "3"]

    @classmethod
    def from_raw_data(cls, raw_data: bytes) -> "IMUData":
        """Parse raw IMU data from the ZED SDK binary format."""
        timestamp_ns = np.frombuffer(
            raw_data, dtype=np.uint64, count=1, offset=0x010)[0]

        accel = np.frombuffer(
            raw_data, dtype=np.float32, count=3, offset=0x064)
        avel = np.frombuffer(
            raw_data, dtype=np.float32, count=3, offset=0x058)

        return cls(
            timestamp=np.float64(timestamp_ns) / 1e9, accel=accel, avel=avel)
