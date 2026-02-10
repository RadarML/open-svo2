"""SVO file conversion."""

import logging
import struct
from fractions import Fraction
from typing import Literal

import av
import numpy as np
from jaxtyping import UInt32, UInt64
from mcap.reader import McapReader, make_reader

from .metadata import FrameFooter, Metadata

logger = logging.getLogger("open_svo2.convert")


def detect_codec(sample: bytes) -> Literal["hevc", "h264"]:
    """Detect whether video sample is H.265 (HEVC) or H.264 (AVC).

    Analyzes NAL unit headers in the provided sample bytes. Defaults to "hevc"
    if detection is ambiguous.
    """
    # Simple search for NAL start code (00 00 00 01) in header
    # to differentiate HEVC (H.265) from AVC (H.264).
    header_bytes = sample[:128]
    start_idx = header_bytes.find(b'\x00\x00\x00\x01')

    if start_idx != -1:
        nal_byte = header_bytes[start_idx + 4]

        # H.265 (HEVC) NAL unit type is (byte & 0x7E) >> 1
        # VPS(32), SPS(33), PPS(34)
        hevc_type = (nal_byte & 0x7E) >> 1

        # H.264 (AVC) NAL unit type is byte & 0x1F
        # SPS(7), PPS(8)
        h264_type = nal_byte & 0x1F

        if hevc_type in (32, 33, 34):
            return "hevc"
        elif h264_type in (7, 8):
            return "h264"

    return "hevc"


def _check_timestamps(
    ts_meta: UInt64[np.ndarray, "N"], ts_footer: UInt64[np.ndarray, "N"]
):
    if len(ts_meta) != len(ts_footer):
        logger.warning(
            "Frame count mismatch between SVO2 metadata and frame footers: "
            f"{len(ts_meta)} vs {len(ts_footer)}")
        return

    if not np.all(ts_meta == ts_footer):
        logger.warning(
            "Timestamps from SVO2 metadata do not match frame footers.")
        mismatch = np.where(ts_meta != ts_footer)
        logger.warning(
            f"First 10 mismatches ({len(mismatch)} total): {mismatch[:10]}")
        logger.warning(f"SVO2 Metadata: {ts_meta[mismatch[:10]]}")
        logger.warning(f"Frame Footers: {ts_footer[mismatch[:10]]}")


def mp4_from_svo2(
    mcap: McapReader | str, output: str, metadata: Metadata | None = None
) -> UInt32[np.ndarray, "N"]:
    """Extract video stream from SVO2 MCAP into a standard MP4 container.

    Args:
        mcap: file path to a svo2 mcap file or a `McapReader` handle.
        output: file path to the output MP4 file.
        metadata: Optional pre-parsed metadata. If not provided, it will be
            extracted from the MCAP reader.

    Returns:
        Index of the last keyframe, as recorded by the frame footer.
    """
    if isinstance(mcap, str):
        with open(mcap, "rb") as f:
            return mp4_from_svo2(make_reader(f), output)
    if metadata is None:
        metadata = Metadata.from_mcap(mcap)

    stream_iter = mcap.iter_messages(
        topics=[f"Camera_SN{metadata.header.serial_number}/side_by_side"])

    try:
        first_msg = next(stream_iter)
    except StopIteration:
        return np.zeros((), dtype=np.uint32)

    _, _, msg = first_msg
    _, frame_size = struct.unpack("<II", msg.data[:8])
    payload = msg.data[8 : 8 + frame_size]
    codec_name = detect_codec(payload)
    start_ts = FrameFooter.from_buffer_copy(
        msg.data[8 + frame_size:]).timestamp

    timestamps = []
    keyframes = []
    with av.open(output, mode='w', format='mp4') as container:
        stream = container.add_stream(codec_name, rate=metadata.header.fps)
        # width is just one camera
        stream.width = metadata.header.width * 2
        stream.height = metadata.header.height
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 1_000_000)

        def message_generator():
            yield first_msg
            yield from stream_iter

        last_pts = -1
        for i, (_, _, msg) in enumerate(message_generator()):
            _, size = struct.unpack("<II", msg.data[:8])
            payload = msg.data[8 : 8 + size]
            footer = FrameFooter.from_buffer_copy(msg.data[8 + size:])
            timestamps.append(footer.timestamp)
            keyframes.append(footer.last_keyframe_index)

            packet = av.Packet(payload)
            pts_us = int(footer.timestamp - start_ts) // 1000

            # Enforce strict monotonicity for MP4
            if pts_us <= last_pts:
                logger.warning(
                    f"Non-monotonic timestamp at frame {i}: "
                    f"{pts_us} <= {last_pts}. Correcting.")
                pts_us = last_pts + 1

            last_pts = pts_us
            packet.pts = pts_us
            packet.stream = stream

            container.mux(packet)

    container.close()

    timestamps = np.array(timestamps, dtype=np.uint64)
    timestamps_meta = metadata.timestamps[
        f"Camera_SN{metadata.header.serial_number}/side_by_side"]
    _check_timestamps(timestamps_meta, timestamps)

    return np.array(keyframes, dtype=np.uint32)
