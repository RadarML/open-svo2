"""
svo2-extract: Extract raw H.265 video and sensor data from Stereolabs SVO2 files.

SVO2 files are MCAP containers that store H.265/HEVC encoded video along with
sensor data from Stereolabs ZED cameras.
"""

__version__ = "0.1.0"

from .extractor import (
    list_channels,
    extract_channel,
    extract_video,
    extract_sensors,
)

__all__ = [
    "__version__",
    "list_channels",
    "extract_channel",
    "extract_video",
    "extract_sensors",
]
