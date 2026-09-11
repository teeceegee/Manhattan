#!/usr/bin/env python3
"""
Fix Pillarboxed 1080p Masters
Detects and repairs 1440x1080 masters that have 180px black pillarbox bars.
Crops out the black bars and scales the active 1080x1080 content to full 1440x1080 (4:3)
using Apple VideoToolbox hardware encoding (hevc_videotoolbox).
"""

import os
import sys
import time
import subprocess
import numpy as np

def is_master_pillarboxed(video_path):
    """Checks if a 1440x1080 master has 180px black bars on the sides."""
    cmd = ["ffmpeg", "-ss", "60", "-i", video_path, "-vframes", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if len(res.stdout) < 1440 * 1080 * 3:
        return False, 0
    arr = np.frombuffer(res.stdout[:1440*1080*3], dtype=np.uint8).reshape((1080, 1440, 3))
    left_mean = arr[:, :160, :].mean()
    right_mean = arr[:, 1280:, :].mean()
    center_mean = arr[:, 400:1040, :].mean()
    
    if left_mean < 10.0 and right_mean < 10.0 and center_mean > 15.0:
        return True, 180
    return False, 0

def fix_master(video_path):
    is_pillar, bar_w = is_master_pillarboxed(video_path)
    if not is_pillar:
        print(f"Skipping (not pillarboxed): {os.path.basename(video_path)}")
        return False

    print(f"\n{'='*70}")
    print(f"FIXING PILLARBOXED MASTER: {os.path.basename(video_path)}")
    print(f"Detected {bar_w}px side bars. Uncrushing to full-frame 1440x1080 4:3...")
    print(f"{'='*70}")

    tmp_out = video_path + ".fixed.mp4"
    if os.path.exists(tmp_out):
        os.remove(tmp_out)

    t0 = time.time()
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", "crop=1080:1080:180:0,scale=1440:1080,setdar=4/3",
        "-c:v", "hevc_videotoolbox", "-b:v", "5000k", "-tag:v", "hvc1",
        "-c:a", "copy",
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-map_chapters", "0",
        "-movflags", "+faststart",
        tmp_out
    ]

    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    for line in p.stderr:
        line_s = line.strip()
        if "frame=" in line_s and "time=" in line_s:
            print(f"\r{line_s}", end="", flush=True)
    p.wait()
    print()

    if p.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 10000000:
        os.replace(tmp_out, video_path)
        elapsed = time.time() - t0
        print(f"SUCCESS: Fixed {os.path.basename(video_path)} in {elapsed/60:.2f} mins ({elapsed:.1f}s)")
        return True
    else:
        print(f"ERROR: Failed to fix {os.path.basename(video_path)}")
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        targets = sys.argv[1:]
    else:
        target_dir = "/Volumes/VIDEO/TV/COMEDY/The Thin Blue Line"
        targets = [os.path.join(target_dir, f) for f in sorted(os.listdir(target_dir)) if f.endswith("- 1080p (4-3 Master).mp4") and not f.startswith("._")]

    print(f"Found {len(targets)} masters to inspect.")
    for t in targets:
        fix_master(t)
