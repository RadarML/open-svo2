"""Decode stereo video frames and export image sequences from SVO2 files."""

import csv
import math
import os
import re
from collections import OrderedDict
from collections.abc import Generator, Iterator
from contextlib import closing
from dataclasses import dataclass
from fractions import Fraction
from itertools import chain
from pathlib import Path
from typing import Literal, Self

import av
import numpy as np
from mcap.reader import McapReader, make_reader
from numpy.typing import NDArray

from .convert import _parse_video_message, detect_codec
from .metadata import FrameFooter, Metadata


def _codec_parameter_sets(payload: bytes, codec: str) -> bytes:
    """Extract VPS/SPS/PPS (or SPS/PPS) parameter sets from an Annex B payload."""
    parameter_types = (32, 33, 34) if codec == "hevc" else (7, 8)
    sets = []
    for unit in re.split(b"\x00\x00\x00?\x01", payload):
        if unit:
            nal_type = (unit[0] & 0x7E) >> 1 if codec == "hevc" else unit[0] & 0x1F
            if nal_type in parameter_types:
                sets.append(b"\x00\x00\x00\x01" + unit)
    if not sets:
        raise ValueError("First video frame contains no codec parameter sets.")
    return b"".join(sets)


def _video_decoder(codec: str, extradata: bytes) -> av.VideoCodecContext:
    decoder = av.CodecContext.create(codec, "r")
    if not isinstance(decoder, av.VideoCodecContext):
        raise TypeError("Frame decoding requires a video codec.")
    decoder.extradata = extradata
    decoder.thread_type = "AUTO"
    return decoder


def _validated_pts(
    footer: FrameFooter, timestamps: NDArray[np.uint64], origin: int
) -> int:
    if not 0 <= footer.frame_id < len(timestamps):
        raise ValueError(f"Invalid video frame index {footer.frame_id}.")
    if footer.timestamp != int(timestamps[footer.frame_id]):
        raise ValueError(
            f"Timestamp mismatch between frame {footer.frame_id} and svo_footer.")
    return footer.timestamp - origin


@dataclass
class DecodedFrame:
    """A decoded stereo frame, with RGB uint8 pixels.

    Attributes:
        image: Side-by-side RGB image, shaped (height, 2 * camera_width, 3).
        index: Original frame index from the SVO2 frame footer.
        timestamp: Seconds relative to the first video frame.
        timestamp_ns: Exact integer Unix nanoseconds, verified against svo_footer.

    The ``left`` and ``right`` properties are views into ``image``.
    """

    image: NDArray[np.uint8]
    index: int
    timestamp: float
    timestamp_ns: int

    @property
    def left(self) -> NDArray[np.uint8]:
        """Left camera RGB image."""
        return self.image[:, :self.image.shape[1] // 2]

    @property
    def right(self) -> NDArray[np.uint8]:
        """Right camera RGB image."""
        return self.image[:, self.image.shape[1] // 2:]


def iter_frames(
    mcap: McapReader | str,
    *,
    start: float = 0.0,
    duration: float | None = None,
    metadata: Metadata | None = None,
) -> Generator[DecodedFrame, None, None]:
    """Decode RGB frames from a seekable SVO2 file, optionally within a time range.

    Args:
        mcap: File path or MCAP reader. Caller-owned readers remain open.
        start: Non-negative seconds relative to the first video frame.
        duration: Positive duration in seconds, or None to read through EOF.
        metadata: Optional pre-parsed metadata.

    Yields:
        Frames in presentation order in the half-open range [start, start + duration).
        A range beyond the last frame yields no frames.

    Seeking uses MCAP timestamps and the frame footer's previous-keyframe index.
    Only that keyframe and subsequent frames are decoded. Each call starts an
    independent decoder, so calls can request ranges in any order. Close the
    iterator when stopping early to release a file opened by this function.
    """
    if not math.isfinite(start) or start < 0:
        raise ValueError("start must be finite and non-negative.")
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        raise ValueError("duration must be finite and positive.")
    if isinstance(mcap, str):
        with open(mcap, "rb") as f:
            yield from iter_frames(
                make_reader(f), start=start, duration=duration, metadata=metadata)
        return
    if metadata is None:
        metadata = Metadata.from_mcap(mcap)

    topic = f"Camera_SN{metadata.header.serial_number}/side_by_side"
    timestamps = metadata.timestamps.get(topic)
    if timestamps is None or len(timestamps) == 0:
        raise ValueError(f"No video timestamps found for {topic}.")
    first = next(mcap.iter_messages(topics=[topic]), None)
    if first is None:
        raise ValueError(f"No video messages found for {topic}.")
    first_payload, first_footer = _parse_video_message(first[2].data)
    origin = first_footer.timestamp
    clock_offset = first[2].log_time - origin
    start_ns = round(Fraction(start) * 1_000_000_000)
    end_ns = None if duration is None else start_ns + round(Fraction(duration) * 1_000_000_000)
    target = next(mcap.iter_messages(
        topics=[topic], start_time=origin + start_ns + clock_offset), None)
    if target is None:
        return
    _, target_footer = _parse_video_message(target[2].data)
    key_index = target_footer.last_keyframe_index
    if not 0 <= key_index < len(timestamps):
        raise ValueError(f"Invalid keyframe index {key_index} for {topic}.")
    key_time = int(timestamps[key_index]) + clock_offset
    messages = mcap.iter_messages(
        topics=[topic], start_time=key_time, log_time_order=False)
    key_message = next(messages, None)
    if key_message is None:
        raise ValueError(f"No video message found for keyframe {key_index}.")
    _, key_footer = _parse_video_message(key_message[2].data)
    if key_footer.frame_id != key_index or key_footer.frame_type != 3:
        raise ValueError(f"Video timestamp index does not identify keyframe {key_index}.")

    codec = detect_codec(first_payload)
    # Later keyframes may omit the parameter sets carried by the first frame.
    decoder = _video_decoder(codec, _codec_parameter_sets(first_payload, codec))
    indices: dict[int, int] = {}

    def decoded_frames(frames: list[av.VideoFrame]) -> Iterator[DecodedFrame]:
        for frame in frames:
            pts = frame.pts
            if pts is None or pts not in indices:
                raise ValueError("Decoded frame has no matching SVO2 timestamp.")
            index = indices.pop(pts)
            if pts < start_ns or (end_ns is not None and pts >= end_ns):
                continue
            if (frame.width, frame.height) != (
                metadata.header.width * 2, metadata.header.height
            ):
                raise ValueError("Decoded frame dimensions do not match the SVO2 header.")
            yield DecodedFrame(
                image=np.asarray(frame.to_ndarray(format="rgb24"), dtype=np.uint8),
                index=index,
                timestamp=pts / 1_000_000_000,
                timestamp_ns=origin + pts,
            )

    for _, _, message in chain([key_message], messages):
        payload, footer = _parse_video_message(message.data)
        pts = _validated_pts(footer, timestamps, origin)
        if pts in indices:
            raise ValueError(f"Duplicate video timestamp {footer.timestamp}.")
        indices[pts] = footer.frame_id
        packet = av.Packet(payload)
        packet.pts = pts
        packet.time_base = Fraction(1, 1_000_000_000)
        frames = decoder.decode(packet)
        yield from decoded_frames(frames)
        if end_ns is not None and any(
            frame.pts is not None and frame.pts >= end_ns for frame in frames
        ):
            return
    yield from decoded_frames(decoder.decode(None))


class VideoReader:
    """Random-access frame decoder with an LRU cache, designed for scrubbing.

    Unlike `iter_frames`, which starts a fresh decoder per call, a `VideoReader`
    keeps the decoder, MCAP reader, and an LRU cache of decoded frames alive
    between calls:

    - Repeated requests for cached frames return instantly.
    - Stepping forward continues the running decoder (one packet per frame).
    - Jumps seek to the target's preceding keyframe via the MCAP index and
      decode only that GOP; frames decoded on the way are cached too.

    Not thread-safe: use one `VideoReader` per thread.

    Example:
        ```python
        with VideoReader("recording.svo2") as reader:
            frame = reader.get_frame(reader.index_at(90.0))
            print(frame.timestamp_ns)  # exact integer Unix nanoseconds
        ```
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        max_cache_bytes: int = 1 << 30,
        metadata: Metadata | None = None,
    ) -> None:
        """Open an SVO2 file for random frame access.

        Args:
            path: Path to the SVO2 file. The reader owns the file handle;
                call `close` (or use a `with` block) to release it.
            max_cache_bytes: Approximate decoded-frame cache budget in bytes
                (RGB frames; a 3840x1200 frame is ~13.8 MB). The most recently
                requested frame is always retained.
            metadata: Optional pre-parsed metadata.
        """
        if max_cache_bytes <= 0:
            raise ValueError("max_cache_bytes must be positive.")
        self._file = open(path, "rb")
        try:
            self._reader = make_reader(self._file)
            self._metadata = (
                metadata if metadata is not None else Metadata.from_mcap(self._reader))
            self._topic = (
                f"Camera_SN{self._metadata.header.serial_number}/side_by_side")
            timestamps = self._metadata.timestamps.get(self._topic)
            if timestamps is None or len(timestamps) == 0:
                raise ValueError(f"No video timestamps found for {self._topic}.")
            self._timestamps = timestamps.view()
            self._timestamps.flags.writeable = False
            first = next(self._reader.iter_messages(topics=[self._topic]), None)
            if first is None:
                raise ValueError(f"No video messages found for {self._topic}.")
            payload, footer = _parse_video_message(first[2].data)
            self._origin = footer.timestamp
            self._clock_offset = first[2].log_time - footer.timestamp
            self._codec = detect_codec(payload)
            self._extradata = _codec_parameter_sets(payload, self._codec)
        except BaseException:
            self._file.close()
            raise
        self._max_cache_bytes = max_cache_bytes
        self._cache: OrderedDict[int, DecodedFrame] = OrderedDict()
        self._cache_bytes = 0
        self._keyframes: dict[int, int] = {}
        self._decoder: av.VideoCodecContext | None = None
        self._messages: Iterator | None = None
        self._pts_to_index: dict[int, int] = {}
        # Frame index of the next message the active iterator will yield.
        self._position: int | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __len__(self) -> int:
        return len(self._timestamps)

    def close(self) -> None:
        """Release the file handle and decoder. Cached frames are discarded."""
        self._decoder = None
        self._messages = None
        self._cache.clear()
        self._cache_bytes = 0
        self._file.close()

    @property
    def metadata(self) -> Metadata:
        """Parsed SVO2 metadata."""
        return self._metadata

    @property
    def fps(self) -> int:
        """Nominal frame rate from the SVO2 header."""
        return self._metadata.header.fps

    @property
    def timestamps_ns(self) -> NDArray[np.uint64]:
        """Read-only exact Unix nanosecond timestamps, indexed by frame."""
        return self._timestamps

    def timestamp_ns(self, index: int) -> int:
        """Exact integer Unix nanosecond timestamp of a frame."""
        self._check_index(index)
        return int(self._timestamps[index])

    def index_at(self, seconds: float) -> int:
        """Index of the frame nearest to `seconds` relative to the first frame."""
        if not math.isfinite(seconds):
            raise ValueError("seconds must be finite.")
        target = int(self._timestamps[0]) + round(seconds * 1_000_000_000)
        position = int(np.searchsorted(self._timestamps, max(target, 0)))
        if position <= 0:
            return 0
        if position >= len(self._timestamps):
            return len(self._timestamps) - 1
        before = target - int(self._timestamps[position - 1])
        after = int(self._timestamps[position]) - target
        return position - 1 if before <= after else position

    def cached_indices(self) -> list[int]:
        """Sorted indices of currently cached frames."""
        return sorted(self._cache)

    def get_frame(self, index: int) -> DecodedFrame:
        """Return the decoded frame at `index`, using the cache when possible."""
        if self._file.closed:
            raise ValueError("VideoReader is closed.")
        self._check_index(index)
        cached = self._cache.get(index)
        if cached is not None:
            self._cache.move_to_end(index)
            return cached
        key_index = self._keyframe_index(index)
        # The target packet may already be fed but not yet decoded, since
        # frame threading delays output; then simply keep feeding.
        target_pts = int(self._timestamps[index]) - self._origin
        resume = self._decoder is not None and (
            target_pts in self._pts_to_index
            or (self._position is not None
                and self._position <= index and key_index <= self._position))
        if not resume:
            self._restart(key_index)
            self._feed_next(index, expect_keyframe=True)
        # Frame threading delays output by a bounded number of packets; a
        # frame still missing well past its packet indicates corrupt data.
        margin = 64
        while index not in self._cache and self._decoder is not None:
            if self._position is not None and self._position > index + margin:
                self._flush(index)
                break
            self._feed_next(index)
        frame = self._cache.get(index)
        if frame is None:
            raise ValueError(f"Frame {index} could not be decoded.")
        self._cache.move_to_end(index)
        return frame

    def _check_index(self, index: int) -> None:
        if not 0 <= index < len(self._timestamps):
            raise IndexError(
                f"Frame index {index} out of range [0, {len(self._timestamps)}).")

    def _keyframe_index(self, index: int) -> int:
        """Index of the keyframe preceding `index`, from the frame's footer."""
        cached = self._keyframes.get(index)
        if cached is not None:
            return cached
        record = next(self._reader.iter_messages(
            topics=[self._topic],
            start_time=int(self._timestamps[index]) + self._clock_offset), None)
        if record is None:
            raise ValueError(f"No video message found for frame {index}.")
        _, footer = _parse_video_message(record[2].data)
        if footer.frame_id != index:
            raise ValueError(
                f"Timestamp index mismatch: expected frame {index}, "
                f"found {footer.frame_id}.")
        key_index = footer.last_keyframe_index
        if not 0 <= key_index <= index:
            raise ValueError(f"Invalid keyframe index {key_index} for frame {index}.")
        self._keyframes[index] = key_index
        return key_index

    def _restart(self, key_index: int) -> None:
        self._decoder = _video_decoder(self._codec, self._extradata)
        self._messages = self._reader.iter_messages(
            topics=[self._topic],
            start_time=int(self._timestamps[key_index]) + self._clock_offset,
            log_time_order=False)
        self._pts_to_index = {}
        self._position = key_index

    def _flush(self, protect: int) -> None:
        assert self._decoder is not None
        frames = self._decoder.decode(None)
        self._decoder = None
        self._messages = None
        self._position = None
        self._store_frames(frames, protect)
        self._pts_to_index.clear()

    def _feed_next(self, protect: int, expect_keyframe: bool = False) -> bool:
        """Feed one packet to the decoder; False once the stream is exhausted."""
        assert self._messages is not None and self._decoder is not None
        record = next(self._messages, None)
        if record is None:
            if expect_keyframe:
                raise ValueError(f"No video message found for keyframe {self._position}.")
            self._flush(protect)
            return False
        payload, footer = _parse_video_message(record[2].data)
        if expect_keyframe and (
            footer.frame_id != self._position or footer.frame_type != 3
        ):
            raise ValueError(
                f"Expected keyframe {self._position}, found frame "
                f"{footer.frame_id} (type {footer.frame_type}).")
        pts = _validated_pts(footer, self._timestamps, self._origin)
        if pts in self._pts_to_index:
            raise ValueError(f"Duplicate video timestamp {footer.timestamp}.")
        self._pts_to_index[pts] = footer.frame_id
        packet = av.Packet(payload)
        packet.pts = pts
        packet.time_base = Fraction(1, 1_000_000_000)
        frames = self._decoder.decode(packet)
        self._position = footer.frame_id + 1
        self._store_frames(frames, protect)
        return True

    def _store_frames(self, frames: list[av.VideoFrame], protect: int) -> None:
        for frame in frames:
            pts = frame.pts
            if pts is None or pts not in self._pts_to_index:
                raise ValueError("Decoded frame has no matching SVO2 timestamp.")
            index = self._pts_to_index.pop(pts)
            if (frame.width, frame.height) != (
                self._metadata.header.width * 2, self._metadata.header.height
            ):
                raise ValueError("Decoded frame dimensions do not match the SVO2 header.")
            decoded = DecodedFrame(
                image=np.asarray(frame.to_ndarray(format="rgb24"), dtype=np.uint8),
                index=index,
                timestamp=pts / 1_000_000_000,
                timestamp_ns=self._origin + pts,
            )
            previous = self._cache.pop(index, None)
            if previous is not None:
                self._cache_bytes -= previous.image.nbytes
            self._cache[index] = decoded
            self._cache_bytes += decoded.image.nbytes
        self._evict(protect)

    def _evict(self, protect: int) -> None:
        while self._cache_bytes > self._max_cache_bytes and len(self._cache) > 1:
            oldest = next(iter(self._cache))
            if oldest == protect:
                self._cache.move_to_end(oldest)
                oldest = next(iter(self._cache))
                if oldest == protect:
                    break
            evicted = self._cache.pop(oldest)
            self._cache_bytes -= evicted.image.nbytes


def images_from_svo2(
    mcap: McapReader | str,
    output: str,
    *,
    start: float = 0.0,
    duration: float | None = None,
    image_format: Literal["png", "jpeg"] = "png",
    stereo: Literal["side_by_side", "left", "right", "split"] = "side_by_side",
    metadata: Metadata | None = None,
) -> int:
    """Export decoded frames to an image directory; return the number of frames.

    PNG is lossless; JPEG is lossy. Filenames use the original frame index:
    ``frame_00000000.png`` or, for split stereo, ``frame_00000000_left.png``
    and ``frame_00000000_right.png``. The accompanying ``frames.csv`` maps each
    image to its frame index, exact integer Unix nanoseconds, and Unix milliseconds
    as an exact decimal string (six fractional digits, not a floating-point value).
    Split stereo images share the same timestamp. Existing files, including the
    CSV, are never overwritten.
    Time ranges have the same meaning as in ``iter_frames``. An empty range
    raises ValueError rather than creating an empty output directory.
    """
    if image_format not in ("png", "jpeg"):
        raise ValueError(f"Unsupported image format: {image_format}.")
    if stereo not in ("side_by_side", "left", "right", "split"):
        raise ValueError(f"Unsupported stereo layout: {stereo}.")
    directory = Path(output)
    extension = "png" if image_format == "png" else "jpg"
    count = 0
    with closing(iter_frames(mcap, start=start, duration=duration, metadata=metadata)) as frames:
        first = next(frames, None)
        if first is None:
            raise ValueError("No video frames found in the requested time range.")
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "frames.csv").open("x", newline="") as manifest:
            writer = csv.writer(manifest)
            writer.writerow(["filename", "index", "timestamp_ns", "timestamp_ms", "camera"])
            for frame in chain([first], frames):
                if stereo == "split":
                    images = [("left", frame.left), ("right", frame.right)]
                elif stereo == "left":
                    images = [("left", frame.left)]
                elif stereo == "right":
                    images = [("right", frame.right)]
                else:
                    images = [("side_by_side", frame.image)]
                for camera, image in images:
                    encoder = av.CodecContext.create(
                        "png" if image_format == "png" else "mjpeg", "w")
                    if not isinstance(encoder, av.VideoCodecContext):
                        raise TypeError("Image export requires a video encoder.")
                    encoder.width = image.shape[1]
                    encoder.height = image.shape[0]
                    encoder.pix_fmt = "rgb24" if image_format == "png" else "yuvj420p"
                    encoder.time_base = Fraction(1, 1)
                    rgb_frame = av.VideoFrame.from_ndarray(image, format="rgb24")
                    packets = encoder.encode(rgb_frame) + encoder.encode(None)
                    suffix = f"_{camera}" if stereo == "split" else ""
                    path = directory / f"frame_{frame.index:08d}{suffix}.{extension}"
                    with path.open("xb") as f:
                        for packet in packets:
                            f.write(bytes(packet))
                    writer.writerow([
                        path.name, frame.index, frame.timestamp_ns,
                        f"{frame.timestamp_ns // 1_000_000}.{frame.timestamp_ns % 1_000_000:06d}",
                        camera,
                    ])
                count += 1
    return count
