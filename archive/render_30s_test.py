#!/usr/bin/env python3
import os
import subprocess
import time
import shutil

BASE_DIR = "/Volumes/Seagate External/Development/Manhattan"
TEST_DIR = os.path.join(BASE_DIR, "test_clips")
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
REALESRGAN_BIN = os.path.join(TOOLS_DIR, "realesrgan", "realesrgan-ncnn-vulkan")
MODELS_DIR = os.path.join(TOOLS_DIR, "realesrgan", "models")
SOURCE_VIDEO = os.path.join(BASE_DIR, "Working", "One Foot in The Grave s04e05 5. The Trial.mp4")

TMP_DIR = "/tmp/manhattan_30s"
TMP_IN = os.path.join(TMP_DIR, "in")
TMP_OUT = os.path.join(TMP_DIR, "out")
TMP_AUDIO = os.path.join(TMP_DIR, "audio_30s.aac")
OUTPUT_MASTER = os.path.join(TEST_DIR, "preview_30s_1080p_master.mp4")

def run(cmd, desc=""):
    print(f"\n--- {desc} ---")
    print("Running:", " ".join(cmd) if isinstance(cmd, list) else cmd)
    start = time.time()
    subprocess.run(cmd, check=True)
    elapsed = time.time() - start
    print(f"Completed in {elapsed:.2f}s")
    return elapsed

def main():
    start_total = time.time()
    os.makedirs(TEST_DIR, exist_ok=True)
    
    # 1. Clean and setup fast internal NVMe temp directory
    shutil.rmtree(TMP_DIR, ignore_errors=True)
    os.makedirs(TMP_IN, exist_ok=True)
    os.makedirs(TMP_OUT, exist_ok=True)

    # 2. Extract 30s segment (03:30 to 04:00 = 750 frames at 25 fps)
    print("Extracting 30-second audio and frames from source...")
    run([
        "ffmpeg", "-y", "-ss", "00:03:30", "-i", SOURCE_VIDEO,
        "-t", "30", "-vn", "-c:a", "copy", TMP_AUDIO
    ], "Extracting 30s AAC Audio")

    run([
        "ffmpeg", "-y", "-ss", "00:03:30", "-i", SOURCE_VIDEO,
        "-t", "30", os.path.join(TMP_IN, "frame_%05d.png")
    ], "Extracting 750 Raw Frames (720x540)")

    # 3. Run Real-ESRGAN at native 4x scale on M4 GPU
    print("\n--- Starting Real-ESRGAN Native 4x Upscale on M4 GPU (750 frames) ---")
    start_gpu = time.time()
    subprocess.run([
        REALESRGAN_BIN,
        "-i", TMP_IN,
        "-o", TMP_OUT,
        "-m", MODELS_DIR,
        "-n", "realesrgan-x4plus",
        "-s", "4",
        "-f", "png"
    ], check=True)
    elapsed_gpu = time.time() - start_gpu
    fps_gpu = 750.0 / elapsed_gpu if elapsed_gpu > 0 else 0
    print(f"AI Super-Resolution completed in {elapsed_gpu:.2f}s ({fps_gpu:.2f} fps)")

    # 4. Downscale with Lanczos to 1440x1080 and hardware encode with VideoToolbox
    run([
        "ffmpeg", "-y", "-framerate", "25",
        "-i", os.path.join(TMP_OUT, "frame_%05d.png"),
        "-i", TMP_AUDIO,
        "-vf", "scale=1440:1080:flags=lanczos",
        "-c:v", "h264_videotoolbox", "-b:v", "9M",
        "-c:a", "copy", "-pix_fmt", "yuv420p",
        OUTPUT_MASTER
    ], "Downscaling to 1080p & Multiplexing with Hardware VideoToolbox")

    # 5. Clean up fast temp buffer
    shutil.rmtree(TMP_DIR, ignore_errors=True)
    
    total_time = time.time() - start_total
    print("\n==========================================")
    print("30-SECOND 1080p MASTER COMPLETED!")
    print(f"Output File: {OUTPUT_MASTER}")
    print(f"Total Time: {total_time/60:.2f} minutes ({total_time:.1f}s)")
    print("==========================================")

if __name__ == "__main__":
    main()
