# Open SVO2

Extract raw H.265 video and sensor data from Stereolabs SVO2 files without the SDK.

SVO2 is Stereolabs' "proprietary" container format for ZED camera recordings. Under the hood, it uses the [MCAP](https://mcap.dev/) format.

## Why use this tool?

The official Stereolabs SDK only provides decoded frames through `retrieveImage()`. This tool allows you to:

- **Extract raw H.265/HEVC bitstreams** directly without decoding
- **Access video data without installing the ZED SDK**
- **Work with the raw encoded data** for custom processing pipelines

## See Also

- [MCAP Format](https://mcap.dev/)
- [Stereolabs ZED SDK](https://www.stereolabs.com/developers)
- [FFmpeg](https://ffmpeg.org/) for video conversion
