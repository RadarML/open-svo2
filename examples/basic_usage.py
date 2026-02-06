#!/usr/bin/env python3
"""Example: Basic usage of svo2-extract as a Python library."""

from svo2_extract import list_channels, extract_video, extract_sensors, extract_channel

# Example 1: List all channels in an SVO2 file
print("=" * 60)
print("Example 1: List channels")
print("=" * 60)

info = list_channels("test3_1080_motion.svo2")

print(f"File: {info['file']}")
print(f"Total messages: {info['statistics']['total_messages']}")
print(f"\nChannels:")
for channel in info["channels"]:
    print(f"  [{channel['id']}] {channel['topic']}: {channel['messages']} messages")

# Example 2: Extract video stream
print("\n" + "=" * 60)
print("Example 2: Extract video")
print("=" * 60)

stats = extract_video("test3_1080_motion.svo2", "example_video.h265", verbose=True)

print(f"\nExtraction complete:")
print(f"  Channel: {stats['channel']}")
print(f"  Frames: {stats['message_count']}")
print(f"  Size: {stats['total_bytes']:,} bytes ({stats['total_bytes']/1024/1024:.1f} MB)")

# Example 3: Extract sensors in quiet mode
print("\n" + "=" * 60)
print("Example 3: Extract sensors (quiet)")
print("=" * 60)

stats = extract_sensors("test3_1080_motion.svo2", "example_sensors.bin", verbose=False)

print(f"Extracted {stats['message_count']} sensor messages")
print(f"Size: {stats['total_bytes']:,} bytes")

# Example 4: Extract a specific channel by ID
print("\n" + "=" * 60)
print("Example 4: Extract specific channel")
print("=" * 60)

stats = extract_channel(
    "test3_1080_motion.svo2",
    "integrated_sensors",
    "example_integrated_sensors.bin",
    verbose=True
)

print(f"\nDone! Extracted from channel: {stats['channel']}")
