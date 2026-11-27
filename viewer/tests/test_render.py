import numpy as np
import pytest

from open_svo2_viewer.render import nearest_index, sample_viewport, to_ppm


@pytest.fixture
def gradient():
    image = np.zeros((10, 20, 3), dtype=np.uint8)
    image[:, :, 0] = np.arange(20, dtype=np.uint8)[None, :] * 10
    image[:, :, 1] = np.arange(10, dtype=np.uint8)[:, None] * 20
    return image


def test_sample_viewport_identity(gradient):
    out = sample_viewport(gradient, 1.0, 20 / 2 - 0.5, 10 / 2 - 0.5, 20, 10)
    np.testing.assert_array_equal(out, gradient)


def test_sample_viewport_zoom_repeats_pixels(gradient):
    out = sample_viewport(gradient, 2.0, 5.0, 5.0, 8, 8)
    assert out.shape == (8, 8, 3)
    # At 2x zoom every source pixel covers a 2x2 output block.
    np.testing.assert_array_equal(out[::2, ::2], out[1::2, 1::2])
    center = out[4, 4]
    np.testing.assert_array_equal(center, gradient[5, 5])


def test_sample_viewport_background_fill(gradient):
    out = sample_viewport(gradient, 1.0, -100.0, -100.0, 6, 6, background=7)
    np.testing.assert_array_equal(out, np.full((6, 6, 3), 7, np.uint8))
    half = sample_viewport(gradient, 1.0, 0.0, 5.0, 8, 4, background=7)
    # Centering on the left image edge: the left output half is background.
    np.testing.assert_array_equal(half[:, :4], np.full((4, 4, 3), 7, np.uint8))
    assert (half[:, 4:] != 7).any()


@pytest.mark.parametrize("zoom,size", [(0, (4, 4)), (-1, (4, 4)), (1, (0, 4))])
def test_sample_viewport_rejects_invalid(gradient, zoom, size):
    with pytest.raises(ValueError):
        sample_viewport(gradient, zoom, 0, 0, *size)


def test_to_ppm_roundtrip(gradient):
    data = to_ppm(gradient)
    header, pixels = data.split(b"\n", 1)
    assert header == b"P6 20 10 255"
    assert pixels == gradient.tobytes()


def test_nearest_index():
    ts = np.array([100, 200, 400], dtype=np.uint64)
    assert nearest_index(ts, 0) == 0
    assert nearest_index(ts, 149) == 0
    assert nearest_index(ts, 150) == 0  # ties go to the earlier frame
    assert nearest_index(ts, 151) == 1
    assert nearest_index(ts, 10_000) == 2
    with pytest.raises(ValueError):
        nearest_index(np.array([], dtype=np.uint64), 5)


def test_canvas_to_source_roundtrip():
    from open_svo2_viewer.render import canvas_to_source

    # At zoom 2 with center (10, 5) on a 100x50 canvas, the canvas center
    # maps to the view center and offsets scale by 1/zoom.
    assert canvas_to_source(49.5, 24.5, 2.0, 10.0, 5.0, 100, 50) == (10.0, 5.0)
    sx, sy = canvas_to_source(59.5, 34.5, 2.0, 10.0, 5.0, 100, 50)
    assert (sx, sy) == (15.0, 10.0)


def test_rect_view_magnifies_selection():
    from open_svo2_viewer.render import canvas_to_source, rect_view

    # Fit view of a 200x100 image on a 100x50 canvas (zoom 0.5).
    zoom, (cx, cy) = rect_view(0.5, 100.0, 50.0, 100, 50, 20, 10, 40, 30, 40.0)
    # Selected 20x20 canvas pixels = 40x40 source pixels; limited by height.
    assert zoom == pytest.approx(50 / 40)
    sx0, sy0 = canvas_to_source(20, 10, 0.5, 100.0, 50.0, 100, 50)
    sx1, sy1 = canvas_to_source(40, 30, 0.5, 100.0, 50.0, 100, 50)
    assert cx == pytest.approx((sx0 + sx1) / 2)
    assert cy == pytest.approx((sy0 + sy1) / 2)
    # Corner order must not matter.
    assert rect_view(0.5, 100.0, 50.0, 100, 50, 40, 30, 20, 10, 40.0) == (
        zoom, (cx, cy))
    # Degenerate and oversized selections are clamped to max_zoom.
    clamped, _ = rect_view(1.0, 0.0, 0.0, 100, 50, 10, 10, 10, 10, 40.0)
    assert clamped == 40.0
