# Open SVO2

The `open_svo2` library provides tools for reading raw video and sensor data from SVO2 files, which is Stereolabs' "proprietary" [MCAP](https://mcap.dev/)-based container format for ZED camera recordings.

=== "As git dependency"

    Add this dependency to your `pyproject.toml`:
    ```sh title="pyproject.toml"
    dependencies = ["open_svo2 @ git+ssh://github.com/RadarML/open-svo2.git@main"]
    ```

=== "As submodule"

    Add as a submodule with `git submodule add git@github.com:RadarML/open-svo2.git`, then:
    ```sh title="pyproject.toml"
    dependencies = ["open_svo2"]

    [tool.uv.sources]
    open_svo2 = { path = "open-svo2" }
    ```

## Why use this tool?

The official Stereolabs SDK only provides decoded frames through `retrieveImage()`. This tool allows you to:

- **Extract raw H.265/HEVC bitstreams** directly without decoding
- **Access video data without installing the ZED SDK**
- **Work with the raw encoded data** for custom processing pipelines

## See Also

- [MCAP Format](https://mcap.dev/)
- [Stereolabs ZED SDK](https://www.stereolabs.com/developers)
- [FFmpeg](https://ffmpeg.org/) for video conversion
