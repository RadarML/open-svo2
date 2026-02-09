import tyro
from open_svo2 import mp4_from_svo2
import numpy as np


def test_conversion(path: str, /,) -> int:
    keyframes = mp4_from_svo2(f"{path}.svo2", f"{path}.mp4")
    np.save(f"{path}.npy", keyframes)

    return 0

if __name__ == '__main__':
    tyro.cli(test_conversion)
