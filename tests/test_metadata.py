import base64
import io
import json

import numpy as np
import pytest
from mcap.reader import make_reader
from mcap.writer import Writer

from open_svo2.metadata import Header, Metadata


@pytest.mark.parametrize(
    "header_size,frequency_key,sdk_key",
    [
        (128, "imu_frequency_hz", "zed_sdk_version"),
        (128, "IMU_frequency", "ZED_SDK_version"),
        (392, "imu_frequency_hz", "zed_sdk_version"),
        (392, "IMU_frequency", "ZED_SDK_version"),
    ],
)
def test_metadata_header_variants(header_size, frequency_key, sdk_key):
    header = Header(width=1920, height=1200, serial_number=12345678, fps=60)
    raw = bytes(header) + bytes([1]) * (header_size - len(bytes(header)))
    calibration = np.arange(18, dtype=np.float32)
    encoded_calibration = base64.b64encode(calibration.tobytes()).decode("ascii")
    topic = "Camera_SN12345678/side_by_side"
    stream = io.BytesIO()
    writer = Writer(stream)
    writer.start()
    for name, data in [
        (
            "svo_header",
            {
                "header": base64.b64encode(raw).decode("ascii"),
                "Calib_acc": encoded_calibration,
                "Calib_gyro": encoded_calibration,
                frequency_key: 200.0,
                sdk_key: "5.4.1",
                "version": "2.0.5" if header_size == 392 else "2.0.3",
            },
        ),
        ("svo_footer", {topic: [100, 200]}),
    ]:
        channel = writer.register_channel(name, "json", 0)
        writer.add_message(channel, 0, json.dumps(data).encode(), 0)
    writer.register_channel(topic, "zed_sdk_encoded", 0)
    writer.finish()
    stream.seek(0)

    metadata = Metadata.from_mcap(make_reader(stream))

    assert (
        metadata.header.width,
        metadata.header.height,
        metadata.header.serial_number,
        metadata.header.fps,
    ) == (1920, 1200, 12345678, 60)
    assert metadata.imu_frequency == 200.0
    assert metadata.zed_sdk_version == "5.4.1"
    np.testing.assert_array_equal(metadata.calib_acc_matrix1, calibration[:9].reshape(3, 3))
    np.testing.assert_array_equal(metadata.calib_gyro_matrix2, calibration[9:].reshape(3, 3))
    np.testing.assert_array_equal(metadata.timestamps[topic], [100, 200])
    assert topic in metadata.channels


@pytest.mark.parametrize("size", [0, 127, 129, 391, 393])
def test_header_rejects_unsupported_lengths(size):
    with pytest.raises(ValueError, match=f"Data length {size}"):
        Header.from_base64(base64.b64encode(bytes(size)).decode("ascii"))
