#!/usr/bin/env python3
import os
import subprocess
import time

BASE_DIR = "/Volumes/Seagate External/Development/Manhattan"
WORKING_DIR = os.path.join(BASE_DIR, "Working")
OUTPUT_4K_DIR = os.path.join(BASE_DIR, "output_4k")
OUTPUT_1080P_DIR = os.path.join(BASE_DIR, "output")

SRC_S01E03 = os.path.join(WORKING_DIR, "One Foot in The Grave s01e03 3. The Valley of Fear.mp4")
SRC_S04E05 = os.path.join(WORKING_DIR, "One Foot in The Grave s04e05 5. The Trial.mp4")

FILES_TO_FIX = [
    # S01E03 (4K)
    (SRC_S01E03, os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s01e03 - 4K UHD (4-3 Master).mp4")),
    (SRC_S01E03, os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s01e03 - 4K UHD (16-9 Pillarbox).mp4")),

    # S04E05 (4K)
    (SRC_S04E05, os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s04e05 - 4K UHD (4-3 Master).mp4")),
    (SRC_S04E05, os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s04e05 - 4K UHD (16-9 Pillarbox).mp4")),
    (SRC_S04E05, os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s04e05 - Full Episode 4K Side-by-Side (3840x2160).mp4")),
    (SRC_S04E05, os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s04e05 - Full Episode 4K Split-Screen (2880x2160).mp4")),

    # S04E05 (1080p)
    (SRC_S04E05, os.path.join(OUTPUT_1080P_DIR, "One Foot in The Grave s04e05 - 1080p (4-3 Master).mp4")),
    (SRC_S04E05, os.path.join(OUTPUT_1080P_DIR, "One Foot in The Grave s04e05 - 1080p (16-9 Pillarbox).mp4")),
    (SRC_S04E05, os.path.join(OUTPUT_1080P_DIR, "One Foot in The Grave s04e05 - Full Episode Side-by-Side (1920x1080).mp4")),
    (SRC_S04E05, os.path.join(OUTPUT_1080P_DIR, "One Foot in The Grave s04e05 - Full Episode Split-Screen (1440x1080).mp4")),
]

def fix_file(src_audio_file, target_video_file):
    if not os.path.exists(target_video_file):
        print(f"Skipping missing file: {target_video_file}")
        return

    tmp_out = target_video_file + ".fixed.mp4"
    print(f"\n{'='*60}")
    print(f"Fixing: {os.path.basename(target_video_file)}")
    print(f"Source Audio: {os.path.basename(src_audio_file)}")
    print(f"{'='*60}")
    
    t0 = time.time()
    cmd = [
        "ffmpeg", "-y",
        "-i", target_video_file,
        "-i", src_audio_file,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac_at", "-b:a", "192k", "-ar", "48000",
        "-shortest",
        "-movflags", "+faststart",
        "-max_interleave_delta", "0",
        tmp_out
    ]
    subprocess.run(cmd, check=True)
    
    # Replace original file atomically
    os.replace(tmp_out, target_video_file)
    elapsed = time.time() - t0
    print(f"SUCCESS: Fixed in {elapsed:.1f}s -> {target_video_file}")

def main():
    total_start = time.time()
    for src_audio, target_video in FILES_TO_FIX:
        fix_file(src_audio, target_video)
    
    total_time = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"ALL FILES FIXED SUCCESSFULLY in {total_time/60:.2f} mins ({total_time:.1f}s)")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
