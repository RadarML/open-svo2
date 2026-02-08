"""Command-line interface for svo2-extract."""

import argparse
import sys

from . import __version__
from .extractor import (
    list_channels,
    print_channel_info,
    extract_channel,
    extract_video,
    extract_sensors,
)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="svo2-extract",
        description="Extract data from SVO2 (MCAP) files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all channels
  svo2-extract --list input.svo2

  # Extract video stream
  svo2-extract --video input.svo2 output.h265

  # Extract specific channel
  svo2-extract --channel side_by_side input.svo2 output.h265
  svo2-extract --channel sensors input.svo2 sensors.bin

  # Quiet mode (no progress output)
  svo2-extract -q input.svo2 output.h265
        """,
    )

    parser.add_argument("input", help="Input SVO2 file")
    parser.add_argument("output", nargs="?", help="Output file")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--list", "-l", action="store_true", help="List all channels"
    )
    parser.add_argument(
        "--video", "-v", action="store_true", help="Extract video stream (default)"
    )
    parser.add_argument(
        "--sensors", "-s", action="store_true", help="Extract sensor data"
    )
    parser.add_argument(
        "--channel", "-c", help="Extract specific channel by name or ID"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress progress output"
    )

    args = parser.parse_args()

    verbose = not args.quiet

    try:
        if args.list:
            info = list_channels(args.input)
            print_channel_info(info)
        elif args.channel:
            if not args.output:
                print("ERROR: Output file required", file=sys.stderr)
                sys.exit(1)
            extract_channel(args.input, args.channel, args.output, verbose)
        elif args.sensors:
            if not args.output:
                args.output = args.input.replace(".svo2", "_sensors.bin")
            extract_sensors(args.input, args.output, verbose)
        else:
            # Default: extract video
            if not args.output:
                args.output = args.input.replace(".svo2", "_video.h265")
            extract_video(args.input, args.output, verbose)

    except FileNotFoundError as e:
        print(f"ERROR: File not found: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
