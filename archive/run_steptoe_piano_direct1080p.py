#!/usr/bin/env python3
"""
Steptoe and Son S01E03 ("The Piano") Direct 1080p Remaster
Runs with Pure Monochrome Chroma Normalization on the 16-Core Apple Neural Engine.
"""

import os
import sys
import time
import shutil
import subprocess
from datetime import datetime

BASE_DIR = "/Volumes/Seagate External/Development/Manhattan"
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
WORKING_DIR = os.path.join(BASE_DIR, "Working")
SCRATCH_ROOT = os.path.join(BASE_DIR, "scratch_steptoe")
LOG_FILE = os.path.join(BASE_DIR, "batch_remaster.log")

sys.path.insert(0, TOOLS_DIR)
from remaster_episode_1080p import remaster_episode
from sync_confluence_manifest import update_confluence

STEPTOE_SRC = "/Volumes/VIDEO/TV/COMEDY/Steptoe and Son/Series 1/Steptoe and Son s01e03 The Piano.mp4"
STEPTOE_SHADA_OUT = "/Volumes/VIDEO/TV/COMEDY/Steptoe and Son/Series 1/Steptoe and Son s01e03 The Piano - 1080p (4-3 Master).mp4"
STEPTOE_LOCAL_OUT = os.path.join(OUTPUT_DIR, "Steptoe and Son s01e03 The Piano - 1080p (4-3 Master).mp4")
STEPTOE_WORKING = os.path.join(WORKING_DIR, "Steptoe and Son s01e03 The Piano.mp4")
STEPTOE_SCRATCH = os.path.join(SCRATCH_ROOT, "Steptoe_and_Son_s01e03_The_Piano")

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [STEPTOE-ANE] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def main():
    os.makedirs(SCRATCH_ROOT, exist_ok=True)
    os.makedirs(WORKING_DIR, exist_ok=True)

    log("="*70)
    log("RESTARTING DIRECT 1080p REMASTER: Steptoe and Son S01E03 ('The Piano')")
    log(f"Source: {STEPTOE_SRC}")
    log(f"Target: {STEPTOE_SHADA_OUT}")
    log("Engine: Apple Neural Engine (ANE) | Mode: Pure Monochrome 1080p HEVC")
    log("="*70)

    if not os.path.exists(STEPTOE_WORKING) or os.path.getsize(STEPTOE_WORKING) != os.path.getsize(STEPTOE_SRC):
        log(f"Copying {os.path.basename(STEPTOE_SRC)} to local working cache ({os.path.getsize(STEPTOE_SRC)/(1024*1024):.1f} MB)...")
        subprocess.run(["cp", "-X", STEPTOE_SRC, STEPTOE_WORKING], check=True)

    t0 = time.time()
    try:
        remaster_episode(STEPTOE_WORKING, STEPTOE_LOCAL_OUT, STEPTOE_SCRATCH, is_monochrome=True, compute_units="ANE", log_func=log)

        log(f"Syncing completed master to Shada: {STEPTOE_SHADA_OUT}...")
        subprocess.run(["cp", "-X", STEPTOE_LOCAL_OUT, STEPTOE_SHADA_OUT], check=True)

        shutil.rmtree(STEPTOE_SCRATCH, ignore_errors=True)
        if os.path.exists(STEPTOE_WORKING):
            os.remove(STEPTOE_WORKING)

        elapsed = time.time() - t0
        log(f"SUCCESS: Steptoe and Son S01E03 remastered and synced in {elapsed/60:.2f} mins ({elapsed:.1f}s)")

        try:
            update_confluence()
        except Exception as e_conf:
            log(f"Warning updating Confluence: {e_conf}")

    except Exception as e:
        log(f"ERROR in Steptoe remaster: {str(e)}")

if __name__ == "__main__":
    main()
