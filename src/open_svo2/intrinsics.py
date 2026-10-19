"""Read camera intrinsics from Zed SDK Config."""

from dataclasses import dataclass
from typing import Self

import numpy as np
import toml
from jaxtyping import Float64


@dataclass
class Intrinsics:
    """Camera intrinsic parameters using the OpenCV distortion model.

    This dataclass represents the calibration parameters for a single camera in
    OpenCV-compatible format, ready to be passed directly to OpenCV functions.

    - The `camera_matrix` is the camera intrinsic matrix in the form:
        ```
        [[fx,  0, cx],
         [ 0, fy, cy],
         [ 0,  0,  1]]
        ```
        where fx/fy are focal lengths in pixels and cx/cy is the principal
        point.
    - The `dist_coeffs` array contains the distortion coefficients in OpenCV
        order, using either the 8-parameter rational model
        (k1, k2, p1, p2, k3, k4, k5, k6) or the 5-parameter Brown-Conrady
        model (k1, k2, p1, p2, k3):
        - k1, k2, k3: Radial distortion coefficients (numerator, 2nd, 4th,
          6th order)
        - k4, k5, k6: Radial distortion coefficients (denominator, 2nd, 4th,
          6th order; rational model only)
        - p1, p2: Tangential distortion coefficients


    Attributes:
        camera_matrix: camera intrinsic matrix in OpenCV format.
        dist_coeffs: distortion coefficients in OpenCV order.

    Notes:
        - Compatible with cv2.undistort(), cv2.calibrateCamera(), etc.
        - Distortion coefficients are dimensionless and resolution-independent
        - Camera matrix scales linearly with image resolution
        - The distortion model follows OpenCV convention (Brown-Conrady model)
    """

    camera_matrix: Float64[np.ndarray, "3 3"]
    dist_coeffs: Float64[np.ndarray, "n"]

    @classmethod
    def from_config(cls, cfg: dict, disto: dict | None = None) -> Self:
        """Create Intrinsics from a parsed configuration dictionary.

        Args:
            cfg: Zed SDK sensor configuration section for a single camera and
                mode, e.g. `LEFT_CAM_FHD1200`.
            disto: Zed SDK rational distortion section for the same camera,
                e.g. `LEFT_DISTO`. If provided, the 8-parameter rational model
                is used instead of the 5-parameter model in `cfg`.
        """
        camera_matrix = np.array([
            [cfg["fx"], 0.0, cfg["cx"]],
            [0.0, cfg["fy"], cfg["cy"]],
            [0.0, 0.0, 1.0]
        ], dtype=np.float64,)

        if disto is not None:
            dist_coeffs = np.array([
                disto["k1"], disto["k2"], disto["p1"], disto["p2"],
                disto["k3"], disto["k4"], disto["k5"], disto["k6"]
            ], dtype=np.float64)
        else:
            dist_coeffs = np.array(
                [cfg["k1"], cfg["k2"], cfg["p1"], cfg["p2"], cfg["k3"]],
                dtype=np.float64)

        return cls(camera_matrix=camera_matrix, dist_coeffs=dist_coeffs)


@dataclass
class StereoIntrinsics:
    """Stereo camera pair parameters.

    !!! info

        Zed uses a convention where the left camera is transformed relative
        to the right camera which is considered the reference frame.

    Attributes:
        left: Intrinsics for the left camera.
        right: Intrinsics for the right camera.
        baseline: Horizontal separation between cameras in mm.
        ty: Translation offset in Y direction (vertical) in mm.
        tz: Translation offset in Z direction (depth) in mm.
        cv: Convergence angle in radians (angle at which optical axes converge).
        rx: Rotation around X axis (pitch) in radians.
        rz: Rotation around Z axis (roll) in radians.
    """

    left: Intrinsics
    right: Intrinsics
    baseline: float
    ty: float
    tz: float
    cv: float
    rx: float
    rz: float

    @classmethod
    def from_config(
        cls, cfg: dict | str,
        mode: str | None = None, height: int | None = None,
        rational: bool = True
    ) -> Self:
        """Parse Zed SDK `sensor.conf` contents.

        !!! info

            Newer factory calibrations (e.g. the Zed X) include
            `LEFT_DISTO` / `RIGHT_DISTO` sections containing an 8-parameter
            rational distortion model, in addition to the 5-parameter model in
            each `{LEFT|RIGHT}_CAM_{mode}` section. These are separate fits
            which can differ by several pixels near the image edges; the
            rational model is used by default when present.

        Args:
            cfg: Zed SDK sensor configuration dictionary or path to dictionary.
            mode: Camera mode (e.g., `FHD1200|FHD|SVGA` for the Zed X).
            height: Image height in pixels, used to infer mode if mode is not
                provided. Must be one of {1200, 1080, 600} corresponding to
                modes {FHD1200, FHD, SVGA} respectively.
            rational: Use the 8-parameter rational distortion model from the
                `{LEFT|RIGHT}_DISTO` sections if present. If `False`, or if
                these sections are missing, the 5-parameter model is used.
        """
        if isinstance(cfg, str):
            with open(cfg, "r") as f:
                cfg = toml.load(f)

        if mode is None:
            if height is None:
                raise ValueError("Either mode or height must be provided")
            mode = cls.infer_mode(height)

        left_disto = cfg.get("LEFT_DISTO") if rational else None
        right_disto = cfg.get("RIGHT_DISTO") if rational else None
        if (left_disto is None) != (right_disto is None):
            raise ValueError(
                "Only one of LEFT_DISTO and RIGHT_DISTO is present")

        try:
            left = Intrinsics.from_config(
                cfg[f"LEFT_CAM_{mode}"], disto=left_disto)
            right = Intrinsics.from_config(
                cfg[f"RIGHT_CAM_{mode}"], disto=right_disto)
        except KeyError as e:
            raise ValueError(
                f"Missing camera configuration for mode '{mode}': {e}") from e

        return cls(
            left=left, right=right,
            baseline=cfg["STEREO"]["Baseline"],
            ty=cfg["STEREO"]["TY"],
            tz=cfg["STEREO"]["TZ"],
            cv=cfg["STEREO"][f"CV_{mode}"],
            rx=cfg["STEREO"][f"RX_{mode}"],
            rz=cfg["STEREO"][f"RZ_{mode}"],
        )

    def as_dict(self) -> dict:
        """Convert StereoIntrinsics to a dictionary format."""
        return {
            "left": {
                "camera_matrix": self.left.camera_matrix.tolist(),
                "dist_coeffs": self.left.dist_coeffs.tolist(),
            },
            "right": {
                "camera_matrix": self.right.camera_matrix.tolist(),
                "dist_coeffs": self.right.dist_coeffs.tolist(),
            },
            "baseline": self.baseline,
            "ty": self.ty,
            "tz": self.tz,
            "cv": self.cv,
            "rx": self.rx,
            "rz": self.rz,
        }

    @staticmethod
    def infer_mode(height: int) -> str:
        """Infer Zed camera mode from image height."""
        if height == 1200:
            return "FHD1200"
        elif height == 1080:
            return "FHD"
        elif height == 600:
            return "SVGA"
        else:
            raise ValueError(f"Unrecognized image height: {height}")
