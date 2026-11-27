"""Conversion CLI."""

import logging
from pathlib import Path
from typing import Literal, NoReturn

import numpy as np
import tyro
from rich.console import Console
from rich.logging import RichHandler

from . import convert
from .video import images_from_svo2

logger = logging.getLogger("open_svo2.cli")


def cli_main(
    path: str, output: str, /,
    mode: Literal["mp4", "h265", "imu", "images"] | None = None,
    *,
    start: float = 0.0,
    duration: float | None = None,
    image_format: Literal["png", "jpeg"] = "png",
    stereo: Literal["side_by_side", "left", "right", "split"] = "side_by_side",
) -> int:
    """Command-line interface for converting SVO2 files.

    Args:
        path: Path to the input SVO2 MCAP file.
        output: Path to the output file.
        mode: Conversion mode. If not specified, it will be inferred from the
            output file extension. Use images explicitly for an image directory.
        start: Image export start in seconds relative to the first video frame.
        duration: Image export duration in seconds; otherwise export through EOF.
        image_format: Image export format.
        stereo: Image export layout; split writes separate left/right images.
    """
    console = Console()
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(
            console=console, rich_tracebacks=True, markup=True)],
    )

    if mode is None:
        ext = Path(output).suffix.lower()
        if ext == ".mp4":
            mode = "mp4"
        elif ext == ".h265":
            mode = "h265"
        elif ext == ".npz":
            mode = "imu"
        else:
            logger.error(
                f"Cannot infer mode from extension '{ext}'. "
                "Specify --mode mp4, h265, imu, or images."
            )
            return 1

    if mode != "images" and (
        start != 0.0 or duration is not None or image_format != "png" or stereo != "side_by_side"
    ):
        logger.error("Time ranges and image options are only supported with --mode images.")
        return 1

    logger.info(f"Converting [bold]{path}[/bold] -> [bold]{output}[/bold] (mode: {mode})")

    if mode == "mp4":
        convert.mp4_from_svo2(path, output)
    elif mode == "h265":
        convert.raw_from_svo2(path, output)
    elif mode == "imu":
        data = convert.imu_from_svo2(path)
        np.savez(output, allow_pickle=False, **data)
    elif mode == "images":
        count = images_from_svo2(
            path, output, start=start, duration=duration, image_format=image_format, stereo=stereo)
        logger.info(f"Exported {count} stereo frames.")

    return 0


def _cli() -> NoReturn:
    exit(tyro.cli(cli_main))
