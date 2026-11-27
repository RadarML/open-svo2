import base64
import csv
import io
import json
import re
import struct
from fractions import Fraction

import av
import numpy as np
import pytest
from mcap.reader import make_reader
from mcap.writer import Writer

from open_svo2 import images_from_svo2, iter_frames
from open_svo2._cli import cli_main
from open_svo2.convert import _parse_video_message, mp4_from_svo2, raw_from_svo2
from open_svo2.metadata import FrameFooter, Header, Metadata

ORIGIN = 1_790_000_000_123_456_789
INTERVAL = 250_000_000
TOPIC = "Camera_SN12345678/side_by_side"


def make_recording(codec: str, b_frames: int = 0) -> bytes:
    encoder = av.CodecContext.create("libx265" if codec == "hevc" else "libx264", "w")
    encoder.width = 64
    encoder.height = 32
    encoder.pix_fmt = "yuv420p"
    encoder.time_base = Fraction(1, 4)
    encoder.framerate = Fraction(4)
    encoder.gop_size = 4
    encoder.max_b_frames = b_frames
    if codec == "hevc":
        encoder.options = {
            "preset": "ultrafast",
            "x265-params": (
                "log-level=error:pools=1:frame-threads=1:keyint=4:min-keyint=4:"
                "scenecut=0:bframes=0:repeat-headers=1"
            ),
        }
    else:
        encoder.options = {
            "preset": "medium" if b_frames else "ultrafast",
            "x264-params": "keyint=4:min-keyint=4:scenecut=0",
        }
        if not b_frames:
            encoder.options["tune"] = "zerolatency"
    packets = []
    for index in range(24):
        pixels = np.zeros((32, 64, 3), dtype=np.uint8)
        pixels[:, :32] = [index * 9, 40, 80]
        pixels[:, 32:] = [50, index * 8, 120]
        frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
        frame.pts = index
        packets.extend(encoder.encode(frame))
    packets.extend(encoder.encode(None))

    stream = io.BytesIO()
    writer = Writer(stream)
    writer.start()
    header_channel = writer.register_channel("svo_header", "json", 0)
    calibration = base64.b64encode(np.zeros(18, dtype=np.float32).tobytes()).decode()
    writer.add_message(header_channel, 0, json.dumps({
        "header": base64.b64encode(bytes(
            Header(width=32, height=32, serial_number=12345678, fps=4))).decode(),
        "Calib_acc": calibration,
        "Calib_gyro": calibration,
    }).encode(), 0)
    video_channel = writer.register_channel(TOPIC, "zed_sdk_encoded", 0)
    key_index = 0
    for packet in packets:
        assert packet.pts is not None
        index = packet.pts
        payload = bytes(packet)
        if packet.is_keyframe:
            key_index = index
            if index:
                # Exercise seeking when only the first frame carries VPS/SPS/PPS.
                types = (32, 33, 34) if codec == "hevc" else (7, 8)
                units = []
                for unit in re.split(b"\x00\x00\x00?\x01", payload):
                    if unit:
                        nal_type = (unit[0] & 126) >> 1 if codec == "hevc" else unit[0] & 31
                        if nal_type not in types:
                            units.append(b"\x00\x00\x00\x01" + unit)
                payload = b"".join(units)
        timestamp = ORIGIN + index * INTERVAL
        footer = bytes(FrameFooter(
            width=64, height=32, timestamp=timestamp, payload_size=len(payload),
            frame_type=3 if packet.is_keyframe else 0,
            last_keyframe_index=key_index, frame_id=index,
        ))
        data = struct.pack("<II", len(payload) + len(footer), len(payload)) + payload + footer
        writer.add_message(video_channel, timestamp, data, timestamp)
    footer_channel = writer.register_channel("svo_footer", "json", 0)
    writer.add_message(footer_channel, ORIGIN + 24 * INTERVAL, json.dumps({
        TOPIC: [ORIGIN + i * INTERVAL for i in range(24)],
    }).encode(), ORIGIN + 24 * INTERVAL)
    writer.finish()
    return stream.getvalue()


@pytest.fixture(params=["h264", "hevc"])
def recording(request):
    return make_recording(request.param)


def test_decode_and_seek_match_full_sequence(recording, monkeypatch):
    reader = make_reader(io.BytesIO(recording))
    all_frames = list(iter_frames(reader))
    assert [frame.index for frame in all_frames] == list(range(24))
    assert [frame.timestamp_ns for frame in all_frames] == [
        ORIGIN + i * INTERVAL for i in range(24)
    ]
    assert all_frames[0].image.shape == (32, 64, 3)
    assert all_frames[0].image.dtype == np.uint8
    assert np.shares_memory(all_frames[0].left, all_frames[0].image)
    assert np.shares_memory(all_frames[0].right, all_frames[0].image)

    original = reader.iter_messages
    preroll_indices = []

    def tracked_messages(*args, **kwargs):
        for record in original(*args, **kwargs):
            if kwargs.get("log_time_order") is False:
                _, footer = _parse_video_message(record[2].data)
                preroll_indices.append(footer.frame_id)
            yield record

    monkeypatch.setattr(reader, "iter_messages", tracked_messages)
    selected = list(iter_frames(reader, start=1.3, duration=1.2))
    assert [frame.index for frame in selected] == [6, 7, 8, 9]
    assert preroll_indices[0] == 4
    assert all(index >= 4 for index in preroll_indices)
    for frame in selected:
        assert 1.3 <= frame.timestamp < 2.5
        assert frame.timestamp_ns == ORIGIN + frame.index * INTERVAL
        np.testing.assert_array_equal(frame.image, all_frames[frame.index].image)
    earlier = list(iter_frames(reader, start=0.25, duration=0.5))
    assert [frame.index for frame in earlier] == [1, 2]


def test_b_frames_preserve_timestamps_and_flush():
    recording = make_recording("h264", b_frames=2)
    reader = make_reader(io.BytesIO(recording))
    full = list(iter_frames(reader))
    assert [frame.index for frame in full] == list(range(24))
    selected = list(iter_frames(reader, start=1.3, duration=1.2))
    assert [frame.index for frame in selected] == [6, 7, 8, 9]
    for frame in selected:
        assert frame.timestamp_ns == ORIGIN + frame.index * INTERVAL
        np.testing.assert_array_equal(frame.image, full[frame.index].image)
    assert list(iter_frames(reader, start=100)) == []


@pytest.mark.parametrize(
    "options",
    [
        {"start": -1}, {"start": float("nan")}, {"start": float("inf")},
        {"duration": 0}, {"duration": -1}, {"duration": float("nan")},
        {"duration": float("inf")},
    ],
)
def test_invalid_time_ranges(recording, options):
    with pytest.raises(ValueError, match="must be finite"):
        list(iter_frames(make_reader(io.BytesIO(recording)), **options))


def test_rejects_footer_timestamp_mismatch(recording):
    reader = make_reader(io.BytesIO(recording))
    metadata = Metadata.from_mcap(reader)
    metadata.timestamps[TOPIC][6] += np.uint64(1)
    with pytest.raises(ValueError, match="Timestamp mismatch"):
        list(iter_frames(reader, start=1.3, duration=1, metadata=metadata))


@pytest.mark.parametrize(
    "data", [b"", struct.pack("<II", 100, 100) + b"short"]
)
def test_rejects_truncated_video(data):
    with pytest.raises(ValueError, match="missing|truncated"):
        _parse_video_message(data)


@pytest.mark.parametrize("image_format", ["png", "jpeg"])
@pytest.mark.parametrize("stereo", ["side_by_side", "left", "right", "split"])
def test_image_export_and_exact_timestamp_csv(recording, tmp_path, image_format, stereo):
    reader = make_reader(io.BytesIO(recording))
    expected = list(iter_frames(reader, start=1.3, duration=0.3))[0]
    output = tmp_path / "images"
    count = images_from_svo2(
        reader, str(output), start=1.3, duration=0.3,
        image_format=image_format, stereo=stereo,
    )
    assert count == 1
    with (output / "frames.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == (2 if stereo == "split" else 1)
    for row in rows:
        assert int(row["index"]) == expected.index
        assert int(row["timestamp_ns"]) == expected.timestamp_ns
        ms, fraction = row["timestamp_ms"].split(".")
        assert int(ms) * 1_000_000 + int(fraction) == expected.timestamp_ns
        with av.open(str(output / row["filename"])) as container:
            pixels = next(container.decode(video=0)).to_ndarray(format="rgb24")
        source = expected.image if row["camera"] == "side_by_side" else (
            expected.left if row["camera"] == "left" else expected.right
        )
        assert pixels.shape == source.shape
        if image_format == "png":
            np.testing.assert_array_equal(pixels, source)
        else:
            assert np.abs(pixels.astype(float) - source.astype(float)).mean() < 5
    with pytest.raises(FileExistsError):
        images_from_svo2(reader, str(output), start=1.3, duration=0.3)


def test_image_cli_and_empty_range(recording, tmp_path):
    source = tmp_path / "recording.svo2"
    source.write_bytes(recording)
    output = tmp_path / "images"
    assert cli_main(
        str(source), str(output), mode="images", start=1.3, duration=0.3,
        image_format="jpeg", stereo="split",
    ) == 0
    assert len(list(output.glob("*.jpg"))) == 2
    assert cli_main(str(source), str(tmp_path / "out.mp4"), start=1) == 1
    empty_output = tmp_path / "empty"
    with pytest.raises(ValueError, match="No video frames"):
        images_from_svo2(str(source), str(empty_output), start=100)
    assert not empty_output.exists()


def test_existing_video_exports(recording, tmp_path):
    reader = make_reader(io.BytesIO(recording))
    expected = list(iter_frames(reader))
    mp4_path = tmp_path / "video.mp4"
    indices = mp4_from_svo2(reader, str(mp4_path))
    assert len(indices) == len(expected)
    with av.open(str(mp4_path)) as container:
        actual = list(container.decode(video=0))
    assert len(actual) == len(expected)
    np.testing.assert_array_equal(actual[-1].to_ndarray(format="rgb24"), expected[-1].image)
    raw_path = tmp_path / "video.raw"
    offsets, timestamps, keyframes = raw_from_svo2(reader, str(raw_path))
    assert len(offsets) == len(timestamps) == len(keyframes) == len(expected)
    assert raw_path.stat().st_size > 0


def write_recording(recording: bytes, tmp_path) -> str:
    path = tmp_path / "recording.svo2"
    path.write_bytes(recording)
    return str(path)


def test_video_reader_random_access_matches_iter_frames(recording, tmp_path, monkeypatch):
    from open_svo2 import VideoReader
    from open_svo2.video import _video_decoder

    expected = list(iter_frames(make_reader(io.BytesIO(recording))))
    decoders = []
    original = _video_decoder

    def counting_decoder(codec, extradata):
        decoders.append(codec)
        return original(codec, extradata)

    monkeypatch.setattr("open_svo2.video._video_decoder", counting_decoder)
    with VideoReader(write_recording(recording, tmp_path)) as reader:
        assert len(reader) == 24
        assert reader.fps == 4
        assert reader.timestamp_ns(5) == ORIGIN + 5 * INTERVAL
        # Jump into the middle of a GOP: decodes from keyframe 8 only.
        frame = reader.get_frame(10)
        assert frame.index == 10
        assert frame.timestamp_ns == ORIGIN + 10 * INTERVAL
        np.testing.assert_array_equal(frame.image, expected[10].image)
        assert set(reader.cached_indices()) >= {8, 9, 10}
        decoders_after_jump = len(decoders)
        # Stepping forward must reuse the running decoder, without a reseek.
        for index in (11, 12, 13):
            np.testing.assert_array_equal(
                reader.get_frame(index).image, expected[index].image)
        assert len(decoders) == decoders_after_jump
        # Cached frames return identical objects without decoding.
        assert reader.get_frame(10) is frame
        assert len(decoders) == decoders_after_jump
        # Backward jumps reseek to the earlier keyframe.
        np.testing.assert_array_equal(reader.get_frame(2).image, expected[2].image)
        assert len(decoders) == decoders_after_jump + 1
        # Last frame requires the end-of-stream flush path.
        np.testing.assert_array_equal(reader.get_frame(23).image, expected[23].image)
        with pytest.raises(IndexError):
            reader.get_frame(24)
        with pytest.raises(IndexError):
            reader.get_frame(-1)
    with pytest.raises(ValueError, match="closed"):
        reader.get_frame(0)


def test_video_reader_with_b_frames(tmp_path):
    from open_svo2 import VideoReader

    recording = make_recording("h264", b_frames=2)
    expected = list(iter_frames(make_reader(io.BytesIO(recording))))
    with VideoReader(write_recording(recording, tmp_path)) as reader:
        for index in (7, 6, 23, 0, 12):
            frame = reader.get_frame(index)
            assert frame.index == index
            assert frame.timestamp_ns == ORIGIN + index * INTERVAL
            np.testing.assert_array_equal(frame.image, expected[index].image)


def test_video_reader_cache_eviction(recording, tmp_path):
    from open_svo2 import VideoReader

    frame_bytes = 32 * 64 * 3
    with VideoReader(
        write_recording(recording, tmp_path), max_cache_bytes=2 * frame_bytes
    ) as reader:
        for index in range(12):
            frame = reader.get_frame(index)
            assert frame.index == index
        cached = reader.cached_indices()
        assert len(cached) == 2
        assert 11 in cached
        # The requested frame is always retained, even over budget.
        tiny = VideoReader(
            write_recording(recording, tmp_path / "sub" if False else tmp_path),
            max_cache_bytes=1)
        try:
            assert tiny.get_frame(5).index == 5
            assert tiny.cached_indices() == [5]
        finally:
            tiny.close()


def test_video_reader_index_at(recording, tmp_path):
    from open_svo2 import VideoReader

    with VideoReader(write_recording(recording, tmp_path)) as reader:
        assert reader.index_at(0.0) == 0
        assert reader.index_at(-5.0) == 0
        assert reader.index_at(1.5) == 6
        assert reader.index_at(1.624) == 6
        assert reader.index_at(1.626) == 7
        assert reader.index_at(100.0) == 23
        with pytest.raises(ValueError, match="finite"):
            reader.index_at(float("nan"))
