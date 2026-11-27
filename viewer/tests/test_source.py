import time

import numpy as np
import pytest
from test_video import INTERVAL, ORIGIN, make_recording

from open_svo2_viewer.source import FrameSource


def collect(source, kinds, timeout=15.0):
    """Poll until one event of each requested kind arrived, newest wins."""
    found = {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for kind, payload in source.poll():
            if kind == "error":
                raise AssertionError(payload)
            found[kind] = payload
        if all(kind in found for kind in kinds):
            return found
        time.sleep(0.01)
    raise AssertionError(f"Timed out waiting for {kinds}, got {sorted(found)}.")


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "recording.svo2"
    path.write_bytes(make_recording("h264"))
    source = FrameSource(str(path), prefetch=3)
    yield source
    source.close()


def test_frame_source_lifecycle(source):
    ready = collect(source, ["ready"])["ready"]
    assert ready["frame_count"] == 24
    assert ready["fps"] == 4
    assert ready["timestamps_ns"][5] == ORIGIN + 5 * INTERVAL

    source.request(10)
    found = collect(source, ["frame", "cache"])
    frame = found["frame"]
    assert frame.index == 10
    assert frame.timestamp_ns == ORIGIN + 10 * INTERVAL
    assert frame.image.dtype == np.uint8
    # Prefetch fills the cache beyond the requested frame.
    deadline = time.monotonic() + 15
    cache = found["cache"]
    while not set(range(10, 14)) <= set(cache) and time.monotonic() < deadline:
        for kind, payload in source.poll():
            if kind == "cache":
                cache = payload
        time.sleep(0.01)
    assert set(range(10, 14)) <= set(cache)


def test_frame_source_coalesces_requests(source):
    collect(source, ["ready"])
    for index in range(20):
        source.request(index)
    source.request(23)
    deadline = time.monotonic() + 15
    last = None
    while time.monotonic() < deadline:
        for kind, payload in source.poll():
            if kind == "frame":
                last = payload
        if last is not None and last.index == 23:
            break
        time.sleep(0.01)
    assert last is not None and last.index == 23


def test_frame_source_reports_open_error(tmp_path):
    source = FrameSource(str(tmp_path / "missing.svo2"))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        events = dict(source.poll())
        if "error" in events:
            assert "missing.svo2" in events["error"]
            return
        time.sleep(0.01)
    raise AssertionError("No error event received.")
