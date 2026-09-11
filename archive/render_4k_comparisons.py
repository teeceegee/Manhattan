#!/usr/bin/env python3
import os
import subprocess
import time

BASE_DIR = "/Volumes/Seagate External/Development/Manhattan"
WORKING_DIR = os.path.join(BASE_DIR, "Working")
OUTPUT_4K_DIR = os.path.join(BASE_DIR, "output_4k")

SOURCE_SD = os.path.join(WORKING_DIR, "One Foot in The Grave s04e05 5. The Trial.mp4")
MASTER_4K = os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s04e05 - 4K UHD (4-3 Master).mp4")

OUTPUT_4K_SBS = os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s04e05 - Full Episode 4K Side-by-Side (3840x2160).mp4")
OUTPUT_4K_SPLIT = os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s04e05 - Full Episode 4K Split-Screen (2880x2160).mp4")

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

    # 1. Full Episode 4K Widescreen Side-by-Side (3840x2160 HEVC)
    run([
        "ffmpeg", "-y",
        "-i", SOURCE_SD,
        "-i", MASTER_4K,
        "-filter_complex",
        "[0:v]scale=1920:1440,pad=1920:2160:0:360:black[v0];"
        "[1:v]scale=1920:1440,pad=1920:2160:0:360:black[v1];"
        "[v0][v1]hstack=inputs=2[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "hevc_videotoolbox", "-b:v", "30M",
        "-tag:v", "hvc1",
        "-c:a", "copy",
        OUTPUT_4K_SBS
    ], "Rendering 4K Widescreen Side-by-Side Full Episode (3840x2160 HEVC)")

    # 2. Full Episode 4K Split-Screen 1:1 Center Crop (2880x2160 HEVC)
    run([
        "ffmpeg", "-y",
        "-i", SOURCE_SD,
        "-i", MASTER_4K,
        "-filter_complex",
        "[0:v]scale=2880:2160:flags=bicubic,crop=1440:2160:0:0[left];"
        "[1:v]crop=1440:2160:1440:0[right];"
        "[left][right]hstack=inputs=2[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "hevc_videotoolbox", "-b:v", "30M",
        "-tag:v", "hvc1",
        "-c:a", "copy",
        OUTPUT_4K_SPLIT
    ], "Rendering 4K Split-Screen 1:1 Full Episode (2880x2160 HEVC)")

    total_time = time.time() - start_total
    print(f"\n{'='*60}")
    print(f"BOTH FULL-EPISODE 4K COMPARISONS COMPLETED SUCCESSFULLY!")
    print(f"1. 4K Side-by-Side (3840x2160): {OUTPUT_4K_SBS}")
    print(f"2. 4K Split-Screen (2880x2160): {OUTPUT_4K_SPLIT}")
    print(f"Total Time: {total_time/60:.2f} minutes ({total_time:.1f}s)")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
