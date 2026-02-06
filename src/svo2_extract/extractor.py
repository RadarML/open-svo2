"""Core extraction functionality for SVO2 files."""

from mcap.reader import make_reader


def list_channels(svo2_file):
    """List all channels in the SVO2 file.

    Args:
        svo2_file: Path to the SVO2 file

    Returns:
        dict: Channel information including statistics
    """
    with open(svo2_file, "rb") as f:
        reader = make_reader(f)
        summary = reader.get_summary()

        info = {
            "file": svo2_file,
            "format": "MCAP (SVO2)",
            "statistics": {
                "total_messages": summary.statistics.message_count if summary.statistics else None,
                "start_time": summary.statistics.message_start_time if summary.statistics else None,
                "end_time": summary.statistics.message_end_time if summary.statistics else None,
            },
            "channels": []
        }

        for channel_id, channel in summary.channels.items():
            channel_msgs = (
                summary.statistics.channel_message_counts.get(channel_id, 0)
                if summary.statistics
                else 0
            )
            info["channels"].append({
                "id": channel_id,
                "topic": channel.topic,
                "encoding": channel.message_encoding,
                "messages": channel_msgs,
            })

        return info


def print_channel_info(info):
    """Pretty print channel information."""
    print(f"File: {info['file']}")
    print(f"Format: {info['format']}")
    print(f"\nStatistics:")
    print(f"  Total messages: {info['statistics']['total_messages']}")
    print(f"  Start time: {info['statistics']['start_time']}")
    print(f"  End time: {info['statistics']['end_time']}")

    print(f"\nChannels:")
    for channel in info["channels"]:
        print(f"  [{channel['id']}] {channel['topic']}")
        print(f"      Encoding: {channel['encoding']}")
        print(f"      Messages: {channel['messages']}")


def extract_channel(svo2_file, channel_topic, output_file, verbose=True):
    """Extract a specific channel from the SVO2 file.

    Args:
        svo2_file: Path to the SVO2 file
        channel_topic: Channel topic name or ID to extract
        output_file: Output file path
        verbose: Print progress information

    Returns:
        dict: Extraction statistics (message_count, total_bytes)
    """
    with open(svo2_file, "rb") as f:
        reader = make_reader(f)
        summary = reader.get_summary()

        # Find matching channel
        target_channel_id = None
        target_channel = None
        for channel_id, channel in summary.channels.items():
            if channel_topic in channel.topic or str(channel_id) == channel_topic:
                target_channel_id = channel_id
                target_channel = channel
                if verbose:
                    print(f"Extracting channel: {channel.topic} (ID: {channel_id})")
                    print(f"  Encoding: {channel.message_encoding}")
                break

        if not target_channel_id:
            raise ValueError(f"Channel '{channel_topic}' not found!")

        # Extract messages
        if verbose:
            print(f"Writing to: {output_file}")

        message_count = 0
        total_bytes = 0

        with open(output_file, "wb") as out:
            for schema, channel, message in reader.iter_messages():
                if channel.id == target_channel_id and message.data:
                    out.write(message.data)
                    message_count += 1
                    total_bytes += len(message.data)
                    if verbose and message_count % 100 == 0:
                        print(f"  Extracted {message_count} messages ({total_bytes:,} bytes)...", end='\r')

        if verbose:
            print(f"\nExtracted {message_count} messages ({total_bytes:,} bytes)")

        return {
            "message_count": message_count,
            "total_bytes": total_bytes,
            "channel": target_channel.topic,
            "encoding": target_channel.message_encoding,
        }


def extract_video(svo2_file, output_file, verbose=True):
    """Extract video stream (side_by_side channel).

    Args:
        svo2_file: Path to the SVO2 file
        output_file: Output H.265 file path
        verbose: Print progress information

    Returns:
        dict: Extraction statistics
    """
    return extract_channel(svo2_file, "side_by_side", output_file, verbose)


def extract_sensors(svo2_file, output_file, verbose=True):
    """Extract sensor data (sensors channel).

    Args:
        svo2_file: Path to the SVO2 file
        output_file: Output file path
        verbose: Print progress information

    Returns:
        dict: Extraction statistics
    """
    return extract_channel(svo2_file, "sensors", output_file, verbose)
