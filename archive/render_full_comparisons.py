#!/usr/bin/env python3
import os
import subprocess
import time

BASE_DIR = "/Volumes/Seagate External/Development/Manhattan"
WORKING_DIR = os.path.join(BASE_DIR, "Working")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

SOURCE_SD = os.path.join(WORKING_DIR, "One Foot in The Grave s04e05 5. The Trial.mp4")
MASTER_1080P = os.path.join(OUTPUT_DIR, "One Foot in The Grave s04e05 - 1080p (4-3 Master).mp4")

OUTPUT_SBS = os.path.join(OUTPUT_DIR, "One Foot in The Grave s04e05 - Full Episode Side-by-Side (1920x1080).mp4")
OUTPUT_SPLIT = os.path.join(OUTPUT_DIR, "One Foot in The Grave s04e05 - Full Episode Split-Screen (1440x1080).mp4")

def run(cmd, desc=""):
    print(f"\n{'='*60}")
    print(f"STARTING: {desc}")
    print(f"{'='*60}")
    start = time.time()
    subprocess.run(cmd, check=True)
    elapsed = time.time() - start
    print(f"COMPLETED in {elapsed/60:.2f} minutes ({elapsed:.1f}s)")
    return elapsed

def main():
    start_total = time.time()

    # 1. Full Episode Widescreen Side-by-Side (1920x1080)
    run([
        "ffmpeg", "-y",
        "-i", SOURCE_SD,
        "-i", MASTER_1080P,
        "-filter_complex",
        "[0:v]scale=960:720,pad=960:1080:0:180:black[v0];"
        "[1:v]scale=960:720,pad=960:1080:0:180:black[v1];"
        "[v0][v1]hstack=inputs=2[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "h264_videotoolbox", "-b:v", "10M",
        "-c:a", "copy",
        OUTPUT_SBS
    ], "Rendering 1920x1080 Widescreen Side-by-Side Full Episode")

    # 2. Full Episode Split-Screen 1:1 Center Crop (1440x1080)
    run([
        "ffmpeg", "-y",
        "-i", SOURCE_SD,
        "-i", MASTER_1080P,
        "-filter_complex",
        "[0:v]scale=1440:1080:flags=bicubic,crop=720:1080:0:0[left];"
        "[1:v]crop=720:1080:720:0[right];"
        "[left][right]hstack=inputs=2[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "h264_videotoolbox", "-b:v", "10M",
        "-c:a", "copy",
        OUTPUT_SPLIT
    ], "Rendering 1440x1080 Split-Screen 1:1 Full Episode")

    total_time = time.time() - start_total
    print(f"\n{'='*60}")
    print(f"BOTH FULL-EPISODE COMPARISONS COMPLETED SUCCESSFULLY!")
    print(f"1. Side-by-Side (1920x1080): {OUTPUT_SBS}")
    print(f"2. Split-Screen (1440x1080): {OUTPUT_SPLIT}")
    print(f"Total Time: {total_time/60:.2f} minutes ({total_time:.1f}s)")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
