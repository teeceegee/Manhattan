#!/usr/bin/env python3
"""
CLI Helper for Queueing and Controlling Video Remastering on Argolis
Usage:
  queue-upscale "TV/COMEDY/Steptoe and Son/Series 2"
  queue-upscale "TV/COMEDY/Porridge"
  queue-upscale --status
  queue-upscale --pause
  queue-upscale --pause-after-current
  queue-upscale --abort
  queue-upscale --resume
"""

import os
import sys
import json
import argparse
from datetime import datetime

LOCAL_STOP_FILE = "/Users/tony/Library/Application Support/ShadaHEVC/argolis-upscale.stop"
LOCAL_PAUSE_AFTER_CURRENT_FILE = "/Users/tony/Library/Application Support/ShadaHEVC/argolis-upscale.pause-after-current"
LOCAL_ABORT_FILE = "/Users/tony/Library/Application Support/ShadaHEVC/argolis-upscale.abort"
REMOTE_STOP_NAME = "upscale.stop"

VIDEO_MOUNTS = ["/Volumes/VIDEO", "/Users/tony/VIDEO"]
def get_video_mount():
    for m in VIDEO_MOUNTS:
        if os.path.exists(m) and os.path.isdir(m):
            return m
    return None

def is_upscale_paused(v_mount=None):
    if os.path.exists(LOCAL_STOP_FILE):
        return True
    if v_mount and os.path.exists(os.path.join(v_mount, REMOTE_STOP_NAME)):
        return True
    for m in VIDEO_MOUNTS:
        if os.path.exists(m) and os.path.exists(os.path.join(m, REMOTE_STOP_NAME)):
            return True
    return False

def pause_upscale(v_mount=None, after_current=False, abort_active=False):
    os.makedirs(os.path.dirname(LOCAL_STOP_FILE), exist_ok=True)
    if after_current:
        with open(LOCAL_PAUSE_AFTER_CURRENT_FILE, "w") as f:
            f.write(f"Pause after current requested at {datetime.now().isoformat()}\n")
        print("SUCCESS: AI Upscaling scheduled to PAUSE after current episode completes.")
        return

    with open(LOCAL_STOP_FILE, "w") as f:
        f.write(f"Paused at {datetime.now().isoformat()}\n")
    if v_mount:
        try:
            remote_stop = os.path.join(v_mount, REMOTE_STOP_NAME)
            with open(remote_stop, "w") as f:
                f.write(f"Paused at {datetime.now().isoformat()}\n")
        except Exception:
            pass

    if abort_active:
        with open(LOCAL_ABORT_FILE, "w") as f:
            f.write(f"Abort requested at {datetime.now().isoformat()}\n")
        print("SUCCESS: AI Upscaling abort requested. Active job will terminate and queue will remain paused.")
    else:
        print("SUCCESS: AI Upscaling PAUSED. Active job (if running) suspended; queue paused.")

def resume_upscale(v_mount=None):
    for f in [LOCAL_STOP_FILE, LOCAL_PAUSE_AFTER_CURRENT_FILE, LOCAL_ABORT_FILE]:
        if os.path.exists(f):
            try: os.remove(f)
            except Exception: pass
    if v_mount:
        remote_stop = os.path.join(v_mount, REMOTE_STOP_NAME)
        if os.path.exists(remote_stop):
            try: os.remove(remote_stop)
            except Exception: pass
    for m in VIDEO_MOUNTS:
        if os.path.exists(m):
            remote_stop = os.path.join(m, REMOTE_STOP_NAME)
            if os.path.exists(remote_stop):
                try: os.remove(remote_stop)
                except Exception: pass
    print("SUCCESS: AI Upscaling RESUMED. Active job (if suspended) resumed; queue active.")

def main():
    parser = argparse.ArgumentParser(description="Queue and control videos for AI Remastering on Argolis")
    parser.add_argument("target", nargs="?", help="Show name, series folder, or episode path to queue")
    parser.add_argument("--status", action="store_true", help="Display current queue daemon status")
    parser.add_argument("--list", action="store_true", help="List all currently queued items")
    parser.add_argument("--pause", action="store_true", help="Immediately pause upscaling (suspends active job, pauses queue)")
    parser.add_argument("--pause-after-current", action="store_true", help="Pause upscaling after current episode completes")
    parser.add_argument("--abort", action="store_true", help="Abort active upscale job and pause queue")
    parser.add_argument("--resume", action="store_true", help="Resume upscaling (resumes suspended job, unpauses queue)")
    args = parser.parse_args()

    v_mount = get_video_mount()

    if args.pause:
        pause_upscale(v_mount, after_current=False, abort_active=False)
        return
    if args.pause_after_current:
        pause_upscale(v_mount, after_current=True, abort_active=False)
        return
    if args.abort:
        pause_upscale(v_mount, after_current=False, abort_active=True)
        return
    if args.resume:
        resume_upscale(v_mount)
        return

    if not v_mount:
        print("ERROR: /Volumes/VIDEO share is not currently mounted.")
        sys.exit(1)

    queue_file = os.path.join(v_mount, "upscale_queue.txt")
    status_file = os.path.join(v_mount, "upscale_status.json")

    if args.status:
        paused = is_upscale_paused(v_mount)
        if os.path.exists(status_file):
            with open(status_file, "r") as f:
                data = json.load(f)
            data["paused_by_user"] = paused
            if os.path.exists(LOCAL_PAUSE_AFTER_CURRENT_FILE):
                data["pause_after_current_pending"] = True
            print(json.dumps(data, indent=2))
        else:
            print(json.dumps({"daemon_status": "PAUSED" if paused else "UNKNOWN", "paused_by_user": paused}, indent=2))
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
