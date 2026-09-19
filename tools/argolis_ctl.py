#!/usr/bin/env python3
"""
Argolis Media Engine Control CLI
Unified controls for AI Upscaling (Manhattan) and HEVC Library Transcoding (ShadaHEVC).

Usage:
  argolis status
  argolis pause upscale [--after-current | --abort]
  argolis resume upscale
  argolis pause hevc
  argolis resume hevc
  argolis pause all
  argolis resume all
"""

import os
import sys
import json
import time
import sqlite3
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

# Paths
HEVC_INI = "/Users/tony/Documents/Shada/hevc-transcoder/argolis-library.ini"
HEVC_STOP_FILE = "/Users/tony/Library/Application Support/ShadaHEVC/argolis-library-jobs.stop"
HEVC_DB = "/Users/tony/Library/Application Support/ShadaHEVC/argolis-library-jobs.sqlite3"

UPSCALE_STOP_LOCAL = "/Users/tony/Library/Application Support/ShadaHEVC/argolis-upscale.stop"
UPSCALE_PAUSE_AFTER_CURRENT = "/Users/tony/Library/Application Support/ShadaHEVC/argolis-upscale.pause-after-current"
UPSCALE_ABORT_LOCAL = "/Users/tony/Library/Application Support/ShadaHEVC/argolis-upscale.abort"
UPSCALE_STATUS_LOCAL = os.path.expanduser("~/Library/Application Support/ShadaHEVC/upscale_status.local.json")
UPSCALE_STATUS_REMOTE = "/Volumes/VIDEO/upscale_status.json"
REMOTE_STOP_NAME = "upscale.stop"
VIDEO_MOUNTS = ["/Volumes/VIDEO", "/Users/tony/VIDEO"]

# ANSI colors
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"
RESET = "\033[0m"

def is_upscale_paused():
    if os.path.exists(UPSCALE_STOP_LOCAL):
        return True
    for m in VIDEO_MOUNTS:
        if os.path.exists(m) and os.path.exists(os.path.join(m, REMOTE_STOP_NAME)):
            return True
    return False

def is_hevc_paused():
    return os.path.exists(HEVC_STOP_FILE)

def pause_upscale(after_current=False, abort_active=False):
    os.makedirs(os.path.dirname(UPSCALE_STOP_LOCAL), exist_ok=True)
    if after_current:
        with open(UPSCALE_PAUSE_AFTER_CURRENT, "w") as f:
            f.write(f"Pause after current requested at {datetime.now().isoformat()}\n")
        print(f"{YELLOW}AI Upscaling scheduled to PAUSE after current episode completes.{RESET}")
        return

    with open(UPSCALE_STOP_LOCAL, "w") as f:
        f.write(f"Paused at {datetime.now().isoformat()}\n")
    for m in VIDEO_MOUNTS:
        if os.path.exists(m):
            try:
                with open(os.path.join(m, REMOTE_STOP_NAME), "w") as f:
                    f.write(f"Paused at {datetime.now().isoformat()}\n")
            except Exception:
                pass

    if abort_active:
        with open(UPSCALE_ABORT_LOCAL, "w") as f:
            f.write(f"Abort requested at {datetime.now().isoformat()}\n")
        print(f"{RED}AI Upscaling abort requested. Active job will terminate and queue will remain paused.{RESET}")
    else:
        print(f"{YELLOW}AI Upscaling PAUSED. Active job (if running) suspended; queue paused.{RESET}")

def resume_upscale():
    for f in [UPSCALE_STOP_LOCAL, UPSCALE_PAUSE_AFTER_CURRENT, UPSCALE_ABORT_LOCAL]:
        if os.path.exists(f):
            try: os.remove(f)
            except Exception: pass
    for m in VIDEO_MOUNTS:
        if os.path.exists(m):
            remote_stop = os.path.join(m, REMOTE_STOP_NAME)
            if os.path.exists(remote_stop):
                try: os.remove(remote_stop)
                except Exception: pass
    print(f"{GREEN}AI Upscaling RESUMED. Active job (if suspended) resumed; queue active.{RESET}")

def pause_hevc():
    os.makedirs(os.path.dirname(HEVC_STOP_FILE), exist_ok=True)
    with open(HEVC_STOP_FILE, "w") as f:
        f.write(f"Paused at {datetime.now().isoformat()}\n")
    print(f"{YELLOW}HEVC Transcoder PAUSED. Active encode will finish or interrupt safely; queue paused.{RESET}")

def resume_hevc():
    if os.path.exists(HEVC_STOP_FILE):
        try: os.remove(HEVC_STOP_FILE)
        except Exception: pass
    print(f"{GREEN}HEVC Transcoder RESUMED. Queued and interrupted work will resume automatically.{RESET}")

def get_upscale_status():
    status = {}
    for p in [UPSCALE_STATUS_REMOTE, UPSCALE_STATUS_LOCAL]:
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    status = json.load(f)
                break
            except Exception:
                pass
    paused = is_upscale_paused()
    after_current = os.path.exists(UPSCALE_PAUSE_AFTER_CURRENT)
    daemon_status = status.get("daemon_status", "UNKNOWN")
    current_job = status.get("current_job")
    pending_count = status.get("pending_count", 0)
    completed_count = status.get("completed_count", 0)

    # Check if process is running
    r = subprocess.run(["pgrep", "-f", "argolis-upscale"], capture_output=True, text=True)
    has_active_proc = (r.returncode == 0)

    return {
        "paused": paused,
        "pause_after_current": after_current,
        "daemon_status": daemon_status,
        "has_active_proc": has_active_proc,
        "current_job": current_job,
        "pending_count": pending_count,
        "completed_count": completed_count
    }

def get_hevc_status():
    paused = is_hevc_paused()
    worker_state = "unknown"
    worker_detail = ""
    active_job = None
    counts = {}

    if os.path.exists(HEVC_DB):
        try:
            db = sqlite3.connect(f"file:{HEVC_DB}?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT state, detail FROM worker_state WHERE id=1").fetchone()
            if row:
                worker_state = row["state"]
                worker_detail = row["detail"]
            c_rows = db.execute("SELECT status, count(*) as cnt FROM jobs GROUP BY status").fetchall()
            counts = {r["status"]: r["cnt"] for r in c_rows}
            if worker_state in ("encoding", "promoting", "verifying", "syncing") and worker_detail:
                active_job = os.path.basename(worker_detail)
            db.close()
        except Exception:
            pass

    return {
        "paused": paused,
        "worker_state": worker_state,
        "worker_detail": worker_detail,
        "active_job": active_job,
        "counts": counts
    }

def print_status():
    up = get_upscale_status()
    hv = get_hevc_status()

    print(f"\n{BOLD}=== ARGOLIS MEDIA ENGINE STATUS ==={RESET}\n")

    # Upscale Section
    up_state_str = f"{YELLOW}[PAUSED]{RESET}" if up["paused"] else f"{GREEN}[ACTIVE]{RESET}"
    if up["pause_after_current"]:
        up_state_str += f" {CYAN}(Pause After Current Active){RESET}"
    print(f"{BOLD}1. AI Upscaling (Manhattan CoreML):{RESET} {up_state_str}")
    print(f"   Daemon State: {up['daemon_status']}")
    if up["current_job"]:
        job_name = up["current_job"].get("filename", "Unknown")
        print(f"   Active Job:   {CYAN}{job_name}{RESET}")
    else:
        print(f"   Active Job:   None (Idle)")
    print(f"   Queue:        {up['completed_count']} completed, {up['pending_count']} pending")

    print()

    # HEVC Section
    hv_state_str = f"{YELLOW}[PAUSED]{RESET}" if hv["paused"] else f"{GREEN}[ACTIVE]{RESET}"
    print(f"{BOLD}2. HEVC Transcoder (ShadaHEVC VideoToolbox):{RESET} {hv_state_str}")
    print(f"   Worker State: {hv['worker_state']} ({hv['worker_detail'] or 'idle'})")
    if hv["active_job"]:
        print(f"   Active Job:   {CYAN}{hv['active_job']}{RESET}")
    else:
        print(f"   Active Job:   None (Idle)")
    done = hv['counts'].get('complete', 0) + hv['counts'].get('skipped', 0)
    total = sum(hv['counts'].values()) if hv['counts'] else 0
    print(f"   Queue:        {done}/{total} processed ({hv['counts'].get('running', 0)} running, {hv['counts'].get('queued', 0)} queued)")

    print()

def main():
    parser = argparse.ArgumentParser(description="Argolis Unified Media Engine Controller")
    subparsers = parser.add_subparsers(dest="subcommand")

    # status
    subparsers.add_parser("status", help="Show live status of upscaling and HEVC transcoding")

    # pause
    p_pause = subparsers.add_parser("pause", help="Pause processing")
    p_pause.add_argument("target", choices=["upscale", "hevc", "all"], help="Target pipeline to pause")
    p_pause.add_argument("--after-current", action="store_true", help="Pause after current upscale finishes")
    p_pause.add_argument("--abort", action="store_true", help="Abort active upscale job immediately")

    # resume
    p_resume = subparsers.add_parser("resume", help="Resume processing")
    p_resume.add_argument("target", choices=["upscale", "hevc", "all"], help="Target pipeline to resume")

    args = parser.parse_args()

    if not args.subcommand or args.subcommand == "status":
        print_status()
        return

    if args.subcommand == "pause":
        if args.target in ("upscale", "all"):
            pause_upscale(after_current=args.after_current, abort_active=args.abort)
        if args.target in ("hevc", "all"):
            pause_hevc()
        return

    if args.subcommand == "resume":
        if args.target in ("upscale", "all"):
            resume_upscale()
        if args.target in ("hevc", "all"):
            resume_hevc()
        return

if __name__ == "__main__":
    main()
