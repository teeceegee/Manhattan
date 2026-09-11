#!/usr/bin/env python3
"""
Automated Batch Remastering Orchestrator for One Foot in the Grave (All Series)
Processes all episodes on Shada into Native 4:3 1080p HEVC Masters
"""

import os
import sys
import json
import time
import shutil
import argparse
import subprocess
from datetime import datetime

BASE_DIR = "/Volumes/Seagate External/Development/Manhattan"
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
WORKING_DIR = os.path.join(BASE_DIR, "Working")
SCRATCH_ROOT = os.path.join(BASE_DIR, "scratch_batch")
LOG_FILE = os.path.join(BASE_DIR, "batch_remaster.log")
PROGRESS_JSON = os.path.join(TOOLS_DIR, "oftg_batch_progress.json")

SHADA_BASE = "/Users/tony/VIDEO/TV/COMEDY/One Foot in The Grave"

# Ensure venv Python is used if available
sys.path.insert(0, TOOLS_DIR)
from remaster_episode_1080p import remaster_episode, get_video_info

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def load_progress():
    if os.path.exists(PROGRESS_JSON):
        try:
            with open(PROGRESS_JSON, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"episodes": {}, "last_updated": None}

def save_progress(data):
    data["last_updated"] = datetime.now().isoformat()
    with open(PROGRESS_JSON, "w") as f:
        json.dump(data, f, indent=2)

def discover_episodes(series_filter=None):
    episodes = []
    if not os.path.exists(SHADA_BASE):
        log(f"ERROR: Shada base path not found at {SHADA_BASE}")
        return episodes

    for root, dirs, files in sorted(os.walk(SHADA_BASE)):
        rel_series = os.path.basename(root)
        if not rel_series.startswith("Series"):
            continue
        
        if series_filter and rel_series != f"Series {series_filter}":
            continue

        for f in sorted(files):
            if f.endswith(".mp4") and not f.startswith("._") and "- 1080p" not in f and "- 4K" not in f and "Side-by-Side" not in f and "Split-Screen" not in f:
                src_path = os.path.join(root, f)
                base_name = os.path.splitext(f)[0]
                target_name = f"{base_name} - 1080p (4-3 Master).mp4"
                target_path = os.path.join(root, target_name)
                local_target_path = os.path.join(OUTPUT_DIR, target_name)

                ep_id = base_name.replace(" ", "_")
                episodes.append({
                    "id": ep_id,
                    "series": rel_series,
                    "filename": f,
                    "src_path": src_path,
                    "target_name": target_name,
                    "shada_target_path": target_path,
                    "local_target_path": local_target_path,
                })
    return episodes

def process_batch(episodes, dry_run=False):
    progress = load_progress()
    total_eps = len(episodes)
    log("="*70)
    log(f"STARTING BATCH REMASTER PIPELINE ({total_eps} total episodes discovered)")
    log("="*70)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(WORKING_DIR, exist_ok=True)
    os.makedirs(SCRATCH_ROOT, exist_ok=True)

    completed_count = 0
    start_batch_time = time.time()

    for idx, ep in enumerate(episodes):
        ep_id = ep["id"]
        ep_info = progress["episodes"].get(ep_id, {})
        shada_target = ep["shada_target_path"]
        local_target = ep["local_target_path"]

        # Check if already complete on Shada
        if os.path.exists(shada_target) and os.path.getsize(shada_target) > 500000000:
            log(f"[{idx+1}/{total_eps}] [SKIPPED] {ep['series']} - {ep['filename']} is already complete on Shada ({os.path.getsize(shada_target)/(1024*1024):.1f} MB).")
            progress["episodes"][ep_id] = {
                "status": "COMPLETED",
                "series": ep["series"],
                "filename": ep["filename"],
                "target_name": ep["target_name"],
                "shada_path": shada_target,
                "size_mb": round(os.path.getsize(shada_target) / (1024*1024), 2),
                "completed_at": ep_info.get("completed_at", datetime.now().isoformat())
            }
            save_progress(progress)
            completed_count += 1
            continue

        # Check if complete locally
        if os.path.exists(local_target) and os.path.getsize(local_target) > 500000000:
            log(f"[{idx+1}/{total_eps}] [SYNCING] {ep['series']} - {ep['filename']} exists locally. Copying to Shada...")
            if not dry_run:
                subprocess.run(["cp", "-X", local_target, shada_target], check=True)
                progress["episodes"][ep_id] = {
                    "status": "COMPLETED",
                    "series": ep["series"],
                    "filename": ep["filename"],
                    "target_name": ep["target_name"],
                    "shada_path": shada_target,
                    "size_mb": round(os.path.getsize(shada_target) / (1024*1024), 2),
                    "completed_at": datetime.now().isoformat()
                }
                save_progress(progress)
            completed_count += 1
            continue

        log(f"\n>>> [{idx+1}/{total_eps}] PROCESSING: {ep['series']} / {ep['filename']}")

        if dry_run:
            log(f"DRY RUN: Would process {ep['src_path']} -> {local_target} -> {shada_target}")
            continue

        # Copy source video to local fast storage to avoid network bottleneck
        local_src = os.path.join(WORKING_DIR, ep["filename"])
        if not os.path.exists(local_src) or os.path.getsize(local_src) != os.path.getsize(ep["src_path"]):
            log(f"Copying {ep['filename']} to local working cache ({os.path.getsize(ep['src_path'])/(1024*1024):.1f} MB)...")
            subprocess.run(["cp", "-X", ep["src_path"], local_src], check=True)

        ep_scratch = os.path.join(SCRATCH_ROOT, ep_id)
        t_ep_start = time.time()
        is_mono = "steptoe" in ep["filename"].lower() or "steptoe" in ep["src_path"].lower()

        try:
            remaster_episode(local_src, local_target, ep_scratch, is_monochrome=is_mono, log_func=log)
            
            # Copy to Shada
            log(f"Copying master to Shada: {shada_target}...")
            subprocess.run(["cp", "-X", local_target, shada_target], check=True)

            # Cleanup scratch & working input
            shutil.rmtree(ep_scratch, ignore_errors=True)
            if os.path.exists(local_src):
                os.remove(local_src)

            t_ep_elapsed = time.time() - t_ep_start
            progress["episodes"][ep_id] = {
                "status": "COMPLETED",
                "series": ep["series"],
                "filename": ep["filename"],
                "target_name": ep["target_name"],
                "shada_path": shada_target,
                "size_mb": round(os.path.getsize(shada_target) / (1024*1024), 2),
                "runtime_seconds": round(t_ep_elapsed, 1),
                "completed_at": datetime.now().isoformat()
            }
            save_progress(progress)
            completed_count += 1

            # Auto-sync live manifest to Confluence Page 6455298
            try:
                from sync_confluence_manifest import update_confluence
                update_confluence()
            except Exception as e_conf:
                log(f"Warning updating Confluence manifest: {e_conf}")

            # Log overall progress & ETA
            remaining = total_eps - completed_count
            avg_time = (time.time() - start_batch_time) / (completed_count if completed_count > 0 else 1)
            eta_hours = (remaining * avg_time) / 3600
            log(f"Batch Progress: {completed_count}/{total_eps} complete ({completed_count/total_eps*100:.1f}%). Estimated Remaining: {eta_hours:.1f} hours.")

        except Exception as e:
            log(f"ERROR processing episode {ep_id}: {str(e)}")
            progress["episodes"][ep_id] = {
                "status": "FAILED",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
            save_progress(progress)

    log("\n" + "="*70)
    log(f"BATCH RUN FINISHED: {completed_count}/{total_eps} episodes completed.")
    log("="*70)

def main():
    parser = argparse.ArgumentParser(description="Batch Remaster Pipeline for One Foot in the Grave")
    parser.add_argument("--series", type=int, default=None, help="Specific series number to process (e.g. 1)")
    parser.add_argument("--dry-run", action="store_true", help="Inspect batch plan without executing")
    args = parser.parse_args()

    episodes = discover_episodes(args.series)
    process_batch(episodes, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
