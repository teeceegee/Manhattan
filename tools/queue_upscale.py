#!/usr/bin/env python3
"""
CLI Helper for Queueing Video Remastering on Argolis
Usage:
  queue-upscale "TV/COMEDY/Steptoe and Son/Series 2"
  queue-upscale "TV/COMEDY/Porridge"
  queue-upscale --status
"""

import os
import sys
import json
import argparse

VIDEO_MOUNTS = ["/Volumes/VIDEO", "/Users/tony/VIDEO"]
def get_video_mount():
    for m in VIDEO_MOUNTS:
        if os.path.exists(m) and os.path.isdir(m):
            return m
    return None

def main():
    parser = argparse.ArgumentParser(description="Queue videos for AI Remastering on Argolis")
    parser.add_argument("target", nargs="?", help="Show name, series folder, or episode path to queue")
    parser.add_argument("--status", action="store_true", help="Display current queue daemon status")
    parser.add_argument("--list", action="store_true", help="List all currently queued items")
    args = parser.parse_args()

    v_mount = get_video_mount()
    if not v_mount:
        print("ERROR: /Volumes/VIDEO share is not currently mounted.")
        sys.exit(1)

    queue_file = os.path.join(v_mount, "upscale_queue.txt")
    status_file = os.path.join(v_mount, "upscale_status.json")

    if args.status:
        if os.path.exists(status_file):
            with open(status_file, "r") as f:
                data = json.load(f)
            print(json.dumps(data, indent=2))
        else:
            print("No active status file found.")
        return

    if args.list:
        if os.path.exists(queue_file):
            print(f"--- Queue File: {queue_file} ---")
            with open(queue_file, "r") as f:
                print(f.read())
        return

    if not args.target:
        parser.print_help()
        sys.exit(1)

    target_entry = args.target.strip()
    with open(queue_file, "a") as f:
        f.write(f"{target_entry}\n")

    print(f"SUCCESS: Queued '{target_entry}' in {queue_file}")
    print("Argolis background daemon will process it automatically.")

if __name__ == "__main__":
    main()
