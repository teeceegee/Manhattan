#!/usr/bin/env python3
"""
GPU Parallel Stream Launcher
Runs One Foot in the Grave S01E06 on the 10-Core Metal GPU (CPU_AND_GPU)
concurrently alongside the Apple Neural Engine stream.
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
SCRATCH_ROOT = os.path.join(BASE_DIR, "scratch_gpu")
LOG_FILE = os.path.join(BASE_DIR, "batch_remaster.log")
GPU_LOG = os.path.join(BASE_DIR, "gpu_stream.log")

sys.path.insert(0, TOOLS_DIR)
from remaster_episode_1080p import remaster_episode
from sync_confluence_manifest import update_confluence

OFTG_SRC = "/Volumes/VIDEO/TV/COMEDY/One Foot in The Grave/Series 1/One Foot in The Grave s01e06 6. The Return of the Speckled Band.mp4"
OFTG_SHADA_OUT = "/Volumes/VIDEO/TV/COMEDY/One Foot in The Grave/Series 1/One Foot in The Grave s01e06 6. The Return of the Speckled Band - 1080p (4-3 Master).mp4"
OFTG_LOCAL_OUT = os.path.join(OUTPUT_DIR, "One Foot in The Grave s01e06 6. The Return of the Speckled Band - 1080p (4-3 Master).mp4")
OFTG_WORKING = os.path.join(WORKING_DIR, "gpu_worker_s01e06.mp4")
OFTG_SCRATCH = os.path.join(SCRATCH_ROOT, "s01e06_gpu")

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [GPU-STREAM-2] {msg}"
    print(line, flush=True)
    with open(GPU_LOG, "a") as f:
        f.write(line + "\n")

def main():
    os.makedirs(SCRATCH_ROOT, exist_ok=True)
    os.makedirs(WORKING_DIR, exist_ok=True)

    log("="*70)
    log("STARTING CONCURRENT GPU STREAM 2: One Foot in The Grave S01E06 (Metal GPU)")
    log(f"Source: {OFTG_SRC}")
    log(f"Target: {OFTG_SHADA_OUT}")
    log("Compute Engine: Apple M4 10-Core Metal GPU (CPU_AND_GPU)")
    log("="*70)

    # 1. Copy source video to local working scratch
    if not os.path.exists(OFTG_WORKING) or os.path.getsize(OFTG_WORKING) != os.path.getsize(OFTG_SRC):
        log(f"Copying S01E06 to local working cache ({os.path.getsize(OFTG_SRC)/(1024*1024):.1f} MB)...")
        subprocess.run(["cp", "-X", OFTG_SRC, OFTG_WORKING], check=True)

    t0 = time.time()
    try:
        # Run on Metal GPU
        remaster_episode(OFTG_WORKING, OFTG_LOCAL_OUT, OFTG_SCRATCH, is_monochrome=False, compute_units="GPU", log_func=log)

        # 2. Sync to Shada
        log(f"Syncing master to Shada: {OFTG_SHADA_OUT}...")
        subprocess.run(["cp", "-X", OFTG_LOCAL_OUT, OFTG_SHADA_OUT], check=True)

        # 3. Cleanup
        shutil.rmtree(OFTG_SCRATCH, ignore_errors=True)
        if os.path.exists(OFTG_WORKING):
            os.remove(OFTG_WORKING)

        elapsed = time.time() - t0
        log(f"SUCCESS: OFTG S01E06 finished on GPU in {elapsed/60:.2f} mins ({elapsed:.1f}s)")

        # 4. Sync Confluence
        try:
            update_confluence()
        except Exception as e_conf:
            log(f"Warning updating Confluence: {e_conf}")

    except Exception as e:
        log(f"ERROR in GPU stream: {str(e)}")

if __name__ == "__main__":
    main()
