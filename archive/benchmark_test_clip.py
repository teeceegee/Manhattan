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

RAW_CLIP = os.path.join(TEST_DIR, "test_raw_10s.mp4")
AUDIO_CLIP = os.path.join(TEST_DIR, "test_audio_10s.aac")
FRAMES_RAW = os.path.join(TEST_DIR, "frames_raw")
FRAMES_X4PLUS = os.path.join(TEST_DIR, "frames_x4plus")
FRAMES_ANIMEV3 = os.path.join(TEST_DIR, "frames_animev3")

def run(cmd, desc=""):
    print(f"\n--- {desc} ---")
    print("Running:", " ".join(cmd) if isinstance(cmd, list) else cmd)
    start = time.time()
    res = subprocess.run(cmd, check=True, text=True, capture_output=False)
    elapsed = time.time() - start
    print(f"Done in {elapsed:.2f}s")
    return elapsed

def main():
    os.makedirs(FRAMES_RAW, exist_ok=True)
    os.makedirs(FRAMES_X4PLUS, exist_ok=True)
    os.makedirs(FRAMES_ANIMEV3, exist_ok=True)

    # 1. Extract 10-second segment at 03:30 (210s) with 250 frames
    run([
        "ffmpeg", "-y", "-ss", "00:03:30", "-i", SOURCE_VIDEO,
        "-t", "10", "-c:v", "libx264", "-crf", "14", "-preset", "fast",
        "-c:a", "copy", RAW_CLIP
    ], "Extracting 10-second test video (03:30 - 03:40)")

    # 2. Extract lossless audio
    run([
        "ffmpeg", "-y", "-i", RAW_CLIP,
        "-vn", "-c:a", "copy", AUDIO_CLIP
    ], "Extracting lossless AAC audio track")

    # 3. Extract raw frames as PNG
    run([
        "ffmpeg", "-y", "-i", RAW_CLIP,
        os.path.join(FRAMES_RAW, "frame_%05d.png")
    ], "Dumping 250 raw frames to PNG")

    # 4. Generate Bicubic baseline at 1440x1080
    bicubic_out = os.path.join(TEST_DIR, "test_10s_bicubic.mp4")
    run([
        "ffmpeg", "-y", "-i", RAW_CLIP,
        "-vf", "scale=1440:1080:flags=bicubic",
        "-c:v", "h264_videotoolbox", "-b:v", "8M",
        "-c:a", "copy", bicubic_out
    ], "Rendering Bicubic 1440x1080 baseline")

    # 5. Run AI Model 1: realesrgan-x4plus (Scale 2x -> 1440x1080)
    print("\n--- Running AI Model 1: realesrgan-x4plus on Apple M4 GPU ---")
    start_x4 = time.time()
    subprocess.run([
        REALESRGAN_BIN,
        "-i", FRAMES_RAW,
        "-o", FRAMES_X4PLUS,
        "-m", MODELS_DIR,
        "-n", "realesrgan-x4plus",
        "-s", "2",
        "-f", "png",
        "-j", "1:2:2"
    ], check=True)
    time_x4 = time.time() - start_x4
    fps_x4 = 250.0 / time_x4 if time_x4 > 0 else 0
    print(f"realesrgan-x4plus completed in {time_x4:.2f}s ({fps_x4:.2f} fps)")

    # Encode x4plus video
    x4plus_out = os.path.join(TEST_DIR, "test_10s_realesrgan_x4plus.mp4")
    run([
        "ffmpeg", "-y", "-framerate", "25",
        "-i", os.path.join(FRAMES_X4PLUS, "frame_%05d.png"),
        "-i", AUDIO_CLIP,
        "-c:v", "h264_videotoolbox", "-b:v", "8M",
        "-c:a", "copy", "-pix_fmt", "yuv420p",
        x4plus_out
    ], "Assembling realesrgan-x4plus 1440x1080 video")

    # 6. Run AI Model 2: realesr-animevideov3 (Scale 2x -> 1440x1080)
    print("\n--- Running AI Model 2: realesr-animevideov3 on Apple M4 GPU ---")
    start_av3 = time.time()
    subprocess.run([
        REALESRGAN_BIN,
        "-i", FRAMES_RAW,
        "-o", FRAMES_ANIMEV3,
        "-m", MODELS_DIR,
        "-n", "realesr-animevideov3",
        "-s", "2",
        "-f", "png",
        "-j", "1:2:2"
    ], check=True)
    time_av3 = time.time() - start_av3
    fps_av3 = 250.0 / time_av3 if time_av3 > 0 else 0
    print(f"realesr-animevideov3 completed in {time_av3:.2f}s ({fps_av3:.2f} fps)")

    # Encode animevideov3 video
    animev3_out = os.path.join(TEST_DIR, "test_10s_animevideov3.mp4")
    run([
        "ffmpeg", "-y", "-framerate", "25",
        "-i", os.path.join(FRAMES_ANIMEV3, "frame_%05d.png"),
        "-i", AUDIO_CLIP,
        "-c:v", "h264_videotoolbox", "-b:v", "8M",
        "-c:a", "copy", "-pix_fmt", "yuv420p",
        animev3_out
    ], "Assembling animevideov3 1440x1080 video")

    # 7. Create Side-by-Side Split Comparison Video (Left: Bicubic SD Upscale | Right: AI Remaster Real-ESRGAN)
    split_out = os.path.join(TEST_DIR, "comparison_10s_split.mp4")
    run([
        "ffmpeg", "-y",
        "-i", bicubic_out,
        "-i", x4plus_out,
        "-filter_complex",
        "[0:v]crop=720:1080:360:0,drawtext=text='ORIGINAL SD (Bicubic)':x=20:y=30:fontsize=36:fontcolor=white:box=1:boxcolor=black@0.6[left];"
        "[1:v]crop=720:1080:360:0,drawtext=text='AI REMASTER (Real-ESRGAN)':x=20:y=30:fontsize=36:fontcolor=yellow:box=1:boxcolor=black@0.6[right];"
        "[left][right]hstack=inputs=2[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "h264_videotoolbox", "-b:v", "10M",
        "-c:a", "copy", split_out
    ], "Generating 1080p Split Comparison Video (Original SD vs AI Remaster)")

    # 8. Create full side-by-side 1920x1080 overview
    sbs_full_out = os.path.join(TEST_DIR, "comparison_10s_side_by_side_1080p.mp4")
    run([
        "ffmpeg", "-y",
        "-i", bicubic_out,
        "-i", x4plus_out,
        "-filter_complex",
        "[0:v]scale=960:720,pad=960:1080:0:180:black,drawtext=text='Original SD 540p (Bicubic 1080p)':x=(w-text_w)/2:y=120:fontsize=32:fontcolor=white:box=1:boxcolor=black@0.7[v0];"
        "[1:v]scale=960:720,pad=960:1080:0:180:black,drawtext=text='AI Remaster (Real-ESRGAN 1080p)':x=(w-text_w)/2:y=120:fontsize=32:fontcolor=yellow:box=1:boxcolor=black@0.7[v1];"
        "[v0][v1]hstack=inputs=2[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "h264_videotoolbox", "-b:v", "10M",
        "-c:a", "copy", sbs_full_out
    ], "Generating 1920x1080 Widescreen Side-by-Side Comparison")

    print("\n==========================================")
    print("ALL BENCHMARK RENDERS COMPLETED SUCCESSFULLY!")
    print(f"1. Raw 10s: {RAW_CLIP}")
    print(f"2. Bicubic Baseline: {bicubic_out}")
    print(f"3. Real-ESRGAN x4plus (Live-Action): {x4plus_out} (Time: {time_x4:.2f}s, {fps_x4:.2f} fps)")
    print(f"4. Real-ESRGAN animevideov3 (Video): {animev3_out} (Time: {time_av3:.2f}s, {fps_av3:.2f} fps)")
    print(f"5. Split Comparison: {split_out}")
    print(f"6. Side-by-Side Widescreen: {sbs_full_out}")
    print("==========================================")

if __name__ == "__main__":
    main()
