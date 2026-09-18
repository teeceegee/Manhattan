#!/usr/bin/env python3
"""
Argolis Automated AI Upscaling Queue Daemon
Features:
- Process Singleton Guard via fcntl file lock
- Native Swift Bare-Metal Zero-Copy Engine (argolis-upscale) execution with Python fallback
- 100% In-Memory RAM Disk support (/Volumes/ArgolisRAM)
- Atomic Master Staging & Sync to Shada (.tmp -> atomic replace)
- Automatic Post-Mux Local Storage Purge (Zero duplicate disk footprint)
- Auto-sync to Confluence Page 6455298
"""

import os
import sys
import time
import json
import fcntl
import shutil
import argparse
import subprocess
import numpy as np
from datetime import datetime

BASE_DIR = "/Volumes/Seagate External/Development/Manhattan"
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
WORKING_DIR = os.path.join(BASE_DIR, "Working")
SCRATCH_ROOT = os.path.join(BASE_DIR, "scratch_queue")
LOG_FILE = os.path.join(BASE_DIR, "upscale_daemon.log")
LOCK_FILE = "/tmp/argolis_queue_daemon.lock"
SWIFT_BIN = os.path.join(TOOLS_DIR, "native", "argolis-upscale")
SWIFT_MODEL_4X3 = os.path.join(TOOLS_DIR, "realesrgan", "models", "realesr_1080p_zerocopy.mlmodelc")
SWIFT_MODEL_16X9 = os.path.join(TOOLS_DIR, "realesrgan", "models", "realesr_1080p_16x9_zerocopy.mlmodelc")
SWIFT_MODEL = SWIFT_MODEL_4X3

# Find VIDEO share mount
VIDEO_MOUNTS = ["/Volumes/VIDEO", "/Users/tony/VIDEO"]
def get_video_mount():
    for m in VIDEO_MOUNTS:
        if os.path.exists(m) and os.path.isdir(m):
            return m
    # Attempt auto-remount via AppleScript if unmounted
    try:
        subprocess.run(
            ["osascript", "-e", 'mount volume "smb://shada.local/VIDEO"'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10
        )
        for m in VIDEO_MOUNTS:
            if os.path.exists(m) and os.path.isdir(m):
                return m
    except Exception:
        pass
    return None

QUEUE_FILE_REL = "upscale_queue.txt"
STATUS_FILE_REL = "upscale_status.json"

sys.path.insert(0, TOOLS_DIR)
from remaster_episode_1080p import remaster_episode, get_video_info, detect_monochrome

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [QUEUE-DAEMON] {msg}"
    print(line, flush=True)
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 10 * 1024 * 1024:
            rot = LOG_FILE + ".1"
            if os.path.exists(rot):
                os.remove(rot)
            os.rename(LOG_FILE, rot)
    except Exception:
        pass
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def read_queue(queue_path):
    if not os.path.exists(queue_path):
        return []
    items = []
    with open(queue_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                items.append(line)
    return items

def update_status(status_path, current_job=None, completed_jobs=None, pending_jobs=None):
    data = {
        "last_updated": datetime.now().isoformat(),
        "daemon_status": "RUNNING",
        "current_job": current_job,
        "completed_count": len(completed_jobs) if completed_jobs else 0,
        "pending_count": len(pending_jobs) if pending_jobs else 0,
        "pending_jobs": pending_jobs[:15] if pending_jobs else [],
        "recent_completed": completed_jobs[-10:] if completed_jobs else []
    }
    try:
        with open(status_path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log(f"Warning updating status file: {e}")

def resolve_target(video_mount, entry):
    if os.path.isabs(entry) and os.path.exists(entry):
        target = entry
    else:
        target = os.path.join(video_mount, entry.lstrip("/"))
    
    if not os.path.exists(target):
        alt = os.path.join(video_mount, "TV", "COMEDY", entry.lstrip("/"))
        if os.path.exists(alt):
            return alt
        return None
    return target

def find_pending_episodes(video_mount, queue_items, ignore_set=None):
    if ignore_set is None:
        ignore_set = set()
    pending = []
    seen = set()

    for item in queue_items:
        full_path = resolve_target(video_mount, item)
        if not full_path:
            continue

        if os.path.isfile(full_path) and full_path.endswith(".mp4"):
            if "- 1080p" not in full_path and "- 4K" not in full_path and not os.path.basename(full_path).startswith("._") and not full_path.endswith(".corrupt"):
                base, ext = os.path.splitext(full_path)
                out_4x3 = f"{base} - 1080p (4-3 Master).mp4"
                out_16x9 = f"{base} - 1080p (16-9 Master).mp4"
                has_master = (os.path.exists(out_4x3) and os.path.getsize(out_4x3) > 10000000) or \
                             (os.path.exists(out_16x9) and os.path.getsize(out_16x9) > 10000000)
                if not has_master:
                    if full_path not in seen and full_path not in ignore_set:
                        seen.add(full_path)
                        pending.append({"src": full_path, "base": base, "name": os.path.basename(full_path)})
        elif os.path.isdir(full_path):
            for root, dirs, files in sorted(os.walk(full_path)):
                if "Corrupted" in root or "corrupt" in root.lower():
                    continue
                for f in sorted(files):
                    if f.endswith(".mp4") and not f.startswith("._") and not f.endswith(".corrupt") and "- 1080p" not in f and "- 4K" not in f and "Side-by-Side" not in f and "Split-Screen" not in f:
                        src_file = os.path.join(root, f)
                        base, ext = os.path.splitext(src_file)
                        out_4x3 = f"{base} - 1080p (4-3 Master).mp4"
                        out_16x9 = f"{base} - 1080p (16-9 Master).mp4"
                        has_master = (os.path.exists(out_4x3) and os.path.getsize(out_4x3) > 10000000) or \
                                     (os.path.exists(out_16x9) and os.path.getsize(out_16x9) > 10000000)
                        if not has_master:
                            if src_file not in seen and src_file not in ignore_set:
                                seen.add(src_file)
                                pending.append({"src": src_file, "base": base, "name": f})
    return pending

def detect_and_normalize_pillarbox(video_path, width, height, log_func):
    """Detects 4:3 content pillarboxed inside a 16:9 canvas and crops it to a native 4:3 frame (720x540)."""
    if height == 0:
        return False
    ratio = width / height
    if abs(ratio - (16.0 / 9.0)) > 0.05:
        return False

    target_w = int(round(height * 4.0 / 3.0))
    if target_w % 2 != 0:
        target_w -= 1
    pillar_w = (width - target_w) // 2
    if pillar_w < 20:
        return False

    # Sample 3 frames across video
    sample_secs = ["60", "300", "600"]
    is_pillar = True
    for s in sample_secs:
        cmd = ["ffmpeg", "-ss", s, "-i", video_path, "-vframes", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        expected_bytes = width * height * 3
        if len(res.stdout) < expected_bytes:
            continue
        frame = np.frombuffer(res.stdout[:expected_bytes], dtype=np.uint8).reshape((height, width, 3))
        left_val = frame[:, :pillar_w - 10, :].mean()
        right_val = frame[:, width - pillar_w + 10:, :].mean()
        if left_val > 12.0 or right_val > 12.0:
            is_pillar = False
            break

    if not is_pillar:
        return False

    log_func(f"Aspect Ratio Check: Detected 4:3 content pillarboxed inside 16:9 canvas ({width}x{height}).")
    log_func(f"Pre-Crop Normalization: Removing {pillar_w}px side bars to produce clean 4:3 frame ({target_w}x{height} -> 720x540)...")

    t_crop = time.time()
    cropped_tmp = video_path + ".cropped.mp4"
    if os.path.exists(cropped_tmp):
        os.remove(cropped_tmp)

    if height == 540 and target_w == 720:
        vf = f"crop=720:540:{pillar_w}:0"
    else:
        vf = f"crop={target_w}:{height}:{pillar_w}:0,scale=720:540"

    crop_cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "17",
        "-c:a", "copy",
        cropped_tmp
    ]
    subprocess.run(crop_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.replace(cropped_tmp, video_path)
    log_func(f"Pillarbox normalization complete in {time.time() - t_crop:.1f}s. Input is now native 720x540 4:3.")
    return True

def run_transcode(src_file, out_file, is_mono, is_widescreen, log_func):
    """Executes Native Swift Zero-Copy bare-metal engine with automatic bitstream sanitization, then multiplexes original audio/chapters via FFmpeg."""
    if os.path.exists(SWIFT_BIN):
        swift_out = out_file + ".video_only.mp4"
        
        def execute_swift(input_path):
            if os.path.exists(swift_out):
                os.remove(swift_out)
            cmd = [SWIFT_BIN, input_path, swift_out]
            if is_widescreen:
                cmd.append("--16x9")
                if os.path.exists(SWIFT_MODEL_16X9):
                    cmd.extend(["--model", SWIFT_MODEL_16X9])
            else:
                if os.path.exists(SWIFT_MODEL_4X3):
                    cmd.extend(["--model", SWIFT_MODEL_4X3])
            if is_mono:
                cmd.append("--mono")
            log_func(f"Executing Native Swift Engine (Video Only): {' '.join(cmd)}")
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in p.stdout:
                line_s = line.strip()
                if line_s:
                    log_func(line_s)
            p.wait()
            return p.returncode

        code = execute_swift(src_file)

        # If AVFoundation rejected the bitstream (Code 118 or missing output), auto-sanitize stream via FFmpeg
        if code == 118 or not (os.path.exists(swift_out) and os.path.getsize(swift_out) > 10000000):
            log_func("Bitstream/header issue detected. Running ultra-fast FFmpeg stream sanitizer...")
            sanitized_input = src_file + ".sanitized.mp4"
            sanitize_cmd = [
                "ffmpeg", "-y", "-i", src_file,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                "-c:a", "copy", sanitized_input
            ]
            subprocess.run(sanitize_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log_func("Stream sanitization complete. Re-executing Native Swift Engine on sanitized stream...")
            code = execute_swift(sanitized_input)
            if os.path.exists(sanitized_input):
                os.remove(sanitized_input)

        if code == 0 and os.path.exists(swift_out) and os.path.getsize(swift_out) > 10000000:
            log_func("Swift engine completed. Multiplexing audio, chapters, and subtitles via FFmpeg...")
            mux_cmd = [
                "ffmpeg", "-y",
                "-i", swift_out,
                "-i", src_file,
                "-map", "0:v:0",
                "-map", "1:a:0?",
                "-map", "1:s?",
                "-map_chapters", "1",
                "-c:v", "copy",
                "-c:a", "aac_at", "-b:a", "192k", "-ar", "48000",
                "-c:s", "copy",
                "-shortest",
                "-movflags", "+faststart",
                out_file
            ]
            subprocess.run(mux_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(swift_out):
                os.remove(swift_out)
            return True
            
        log_func(f"Swift engine failed (Exit Code {code}).")
        raise Exception(f"Swift engine failed with exit code {code}")

    # Fallback if binary missing
    return remaster_episode(src_file, out_file, scratch_dir=None, is_monochrome=is_mono, log_func=log_func)

def run_daemon():
    # 1. Acquire Process Singleton Lock
    lock_file = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, IOError):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Another Argolis Queue Daemon instance is already running. Exiting.")
        sys.exit(0)

    log("="*70)
    log("ARGOLIS AUTOMATED AI UPSCALE QUEUE DAEMON STARTED (Native Zero-Copy Enabled)")
    log("="*70)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(WORKING_DIR, exist_ok=True)
    os.makedirs(SCRATCH_ROOT, exist_ok=True)

    completed_history = []
    failed_jobs = set()

    while True:
        video_mount = get_video_mount()
        if not video_mount:
            log("Waiting for VIDEO share mount (/Volumes/VIDEO)...")
            time.sleep(30)
            continue

        try:
            queue_file = os.path.join(video_mount, QUEUE_FILE_REL)
            status_file = os.path.join(video_mount, STATUS_FILE_REL)

            if not os.path.exists(queue_file):
                with open(queue_file, "w") as f:
                    f.write("# ==============================================================================\n")
                    f.write("# ARGOLIS AI UPSCALE QUEUE\n")
                    f.write("# Add show paths, series folders, or single video files below.\n")
                    f.write("# Processing runs automatically on the 16-Core Apple Neural Engine.\n")
                    f.write("# ==============================================================================\n\n")

            queue_items = read_queue(queue_file)
            pending_jobs = find_pending_episodes(video_mount, queue_items, ignore_set=failed_jobs)

            if not pending_jobs:
                update_status(status_file, current_job=None, completed_jobs=completed_history, pending_jobs=[])
                time.sleep(20)
                continue
        except Exception as e:
            log(f"Transient error checking queue on {video_mount}: {e}")
            time.sleep(15)
            continue

        job = pending_jobs[0]
        src_path = job["src"]
        base_path = job["base"]
        filename = job["name"]
        local_src = os.path.join(WORKING_DIR, filename)

        t0 = time.time()
        try:
            # 1. Copy source locally for ultra-fast SSD streaming
            if not os.path.exists(local_src) or os.path.getsize(local_src) != os.path.getsize(src_path):
                log(f"Copying {filename} to local working cache ({os.path.getsize(src_path)/(1024*1024):.1f} MB)...")
                subprocess.run(["cp", "-X", src_path, local_src], check=True)

            # 2. Detect Content Profile & Aspect Ratio
            duration, width, height, has_subs = get_video_info(local_src)
            is_mono, chroma_score = detect_monochrome(local_src, duration, width, height)
            is_widescreen = (height > 0 and (width / height) > 1.55)
            log(f"Content Profile: {'Monochrome (B&W)' if is_mono else 'Full Color'} (Chroma Score: {chroma_score:.2f})")

            # 2b. Auto-Detect & Normalize 16:9 Pillarboxed 4:3 Content
            was_cropped = detect_and_normalize_pillarbox(local_src, width, height, log)
            if was_cropped:
                is_widescreen = False

            master_tag = "(16-9 Master)" if is_widescreen else "(4-3 Master)"
            shada_out = f"{base_path} - 1080p {master_tag}.mp4"
            local_out = os.path.join(OUTPUT_DIR, os.path.basename(shada_out))

            current_job_info = {
                "filename": filename,
                "src": src_path,
                "target": shada_out,
                "started_at": datetime.now().isoformat()
            }
            update_status(status_file, current_job=current_job_info, completed_jobs=completed_history, pending_jobs=pending_jobs[1:])

            log(f"\n>>> PICKED UP QUEUE JOB: {filename}")
            log(f"Source: {src_path}")
            log(f"Aspect Ratio: {'16:9 Widescreen' if is_widescreen else '4:3 Fullscreen'} ({width}x{height})")
            log(f"Destination: {shada_out}")

            # 3. Run Hardware Remaster
            run_transcode(local_src, local_out, is_mono, is_widescreen, log)

            # 4. Atomic sync of master directly to Shada alongside original
            log(f"Syncing completed master atomically to Shada: {shada_out}...")
            shada_tmp = shada_out + ".tmp"
            subprocess.run(["cp", "-X", local_out, shada_tmp], check=True)
            if os.path.exists(shada_out):
                os.remove(shada_out)
            os.rename(shada_tmp, shada_out)

            # 5. Cleanup working inputs & local output master (Maintain Zero-Waste Disk Footprint)
            if os.path.exists(local_src):
                os.remove(local_src)
            if os.path.exists(local_out):
                os.remove(local_out)
            try:
                subprocess.run(["tmutil", "thinlocalsnapshots", "/", "10000000000", "4"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

            elapsed = time.time() - t0
            completed_history.append(current_job_info)
            log(f"SUCCESS: Completed {filename} in {elapsed/60:.2f} mins ({elapsed:.1f}s)")

            # Auto-sync live manifest to Confluence Page 6455298
            try:
                from sync_confluence_manifest import update_confluence
                update_confluence()
            except Exception as e_conf:
                log(f"Warning updating Confluence manifest: {e_conf}")

        except Exception as e:
            log(f"ERROR processing {filename}: {str(e)}")
            failed_jobs.add(src_path)
            # Cleanup any partial files
            if os.path.exists(local_src):
                try: os.remove(local_src)
                except Exception: pass
            if os.path.exists(local_out):
                try: os.remove(local_out)
                except Exception: pass
            time.sleep(5)

if __name__ == "__main__":
    run_daemon()
