#!/usr/bin/env python3
"""
Priority Episode Insertion Manager
Monitors the completion of One Foot in the Grave S01E05,
then immediately runs Steptoe and Son S01E03 ("The Piano") 1080p HEVC Remaster,
syncs it to Shada, and resumes the One Foot in the Grave batch queue.
"""

import os
import sys
import time
import json
import subprocess
from datetime import datetime

BASE_DIR = "/Volumes/Seagate External/Development/Manhattan"
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
WORKING_DIR = os.path.join(BASE_DIR, "Working")
SCRATCH_ROOT = os.path.join(BASE_DIR, "scratch_batch")
LOG_FILE = os.path.join(BASE_DIR, "batch_remaster.log")
PROGRESS_JSON = os.path.join(TOOLS_DIR, "oftg_batch_progress.json")
VENV_PYTHON = os.path.join(BASE_DIR, "venv", "bin", "python3")

sys.path.insert(0, TOOLS_DIR)
from remaster_episode_1080p import remaster_episode

STEPTOE_SRC = "/Volumes/VIDEO/TV/COMEDY/Steptoe and Son/Series 1/Steptoe and Son s01e03 The Piano.mp4"
STEPTOE_SHADA_OUT = "/Volumes/VIDEO/TV/COMEDY/Steptoe and Son/Series 1/Steptoe and Son s01e03 The Piano - 1080p (4-3 Master).mp4"
STEPTOE_LOCAL_OUT = os.path.join(OUTPUT_DIR, "Steptoe and Son s01e03 The Piano - 1080p (4-3 Master).mp4")
STEPTOE_WORKING = os.path.join(WORKING_DIR, "Steptoe and Son s01e03 The Piano.mp4")
STEPTOE_SCRATCH = os.path.join(SCRATCH_ROOT, "Steptoe_and_Son_s01e03_The_Piano")

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [STEPTOE-INSERT] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def is_s01e05_complete():
    # Check if S01E05 master is synced to Shada or completed in progress.json
    s01e05_shada = "/Volumes/VIDEO/TV/COMEDY/One Foot in The Grave/Series 1/One Foot in The Grave s01e05 5. The Eternal Quadrangle - 1080p (4-3 Master).mp4"
    if os.path.exists(s01e05_shada) and os.path.getsize(s01e05_shada) > 500000000:
        return True
    if os.path.exists(PROGRESS_JSON):
        try:
            with open(PROGRESS_JSON, "r") as f:
                data = json.load(f)
                ep = data.get("episodes", {}).get("One_Foot_in_The_Grave_s01e05_5._The_Eternal_Quadrangle", {})
                if ep.get("status") == "COMPLETED":
                    return True
        except Exception:
            pass
    return False

def stop_active_batch_runner():
    log("Checking for running OFTG batch runner processes...")
    try:
        res = subprocess.run(["pgrep", "-f", "run_batch_remaster_pipeline.py"], stdout=subprocess.PIPE, text=True)
        pids = res.stdout.strip().split()
        for pid in pids:
            log(f"Stopping OFTG batch runner PID {pid} to insert Steptoe and Son...")
            subprocess.run(["kill", "-TERM", pid])
    except Exception as e:
        log(f"Warning checking runner PID: {e}")

def run_steptoe_pipeline():
    log("="*70)
    log("STARTING TEST REMASTER: Steptoe and Son S01E03 ('The Piano' - 1962 B&W Master)")
    log(f"Source: {STEPTOE_SRC}")
    log(f"Target: {STEPTOE_SHADA_OUT}")
    log("="*70)

    # 1. Copy source locally to Working directory
    if not os.path.exists(STEPTOE_WORKING) or os.path.getsize(STEPTOE_WORKING) != os.path.getsize(STEPTOE_SRC):
        log(f"Copying {os.path.basename(STEPTOE_SRC)} to local working cache ({os.path.getsize(STEPTOE_SRC)/(1024*1024):.1f} MB)...")
        subprocess.run(["cp", "-X", STEPTOE_SRC, STEPTOE_WORKING], check=True)

    t0 = time.time()
    try:
        remaster_episode(STEPTOE_WORKING, STEPTOE_LOCAL_OUT, STEPTOE_SCRATCH, is_monochrome=True, log_func=log)

        # Copy to Shada
        log(f"Copying Steptoe 1080p master to Shada: {STEPTOE_SHADA_OUT}...")
        subprocess.run(["cp", "-X", STEPTOE_LOCAL_OUT, STEPTOE_SHADA_OUT], check=True)

        # Cleanup scratch & working
        import shutil
        shutil.rmtree(STEPTOE_SCRATCH, ignore_errors=True)
        if os.path.exists(STEPTOE_WORKING):
            os.remove(STEPTOE_WORKING)

        elapsed = time.time() - t0
        log(f"SUCCESS: Steptoe and Son S01E03 remastered and synced in {elapsed/60:.2f} mins ({elapsed:.1f}s)")

        # Auto-sync live manifest to Confluence Page 6455298
        try:
            from sync_confluence_manifest import update_confluence
            update_confluence()
        except Exception as e_conf:
            log(f"Warning updating Confluence manifest: {e_conf}")

    except Exception as e:
        log(f"ERROR in Steptoe remaster: {str(e)}")

def resume_oftg_batch():
    log("\n" + "="*70)
    log("RESUMING ONE FOOT IN THE GRAVE BATCH QUEUE (Series 1 Episode 6 onwards)...")
    log("="*70)
    cmd = [
        VENV_PYTHON,
        os.path.join(TOOLS_DIR, "run_batch_remaster_pipeline.py"),
        "--series", "1"
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("OFTG batch pipeline resumed in background.")

def main():
    log("Waiting for One Foot in the Grave S01E05 ('The Eternal Quadrangle') to finish...")
    while not is_s01e05_complete():
        time.sleep(30)

    log("S01E05 has completed!")
    # Allow 10 seconds for file sync
    time.sleep(10)

    # Stop current batch runner if still looping
    stop_active_batch_runner()
    time.sleep(3)

    # Run Steptoe and Son
    run_steptoe_pipeline()

    # Resume OFTG batch
    resume_oftg_batch()

if __name__ == "__main__":
    main()
