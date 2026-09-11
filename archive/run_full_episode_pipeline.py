#!/usr/bin/env python3
import os
import sys
import json
import time
import shutil
import subprocess
from datetime import datetime

# --- CONFIGURATION ---
BASE_DIR = "/Volumes/Seagate External/Development/Manhattan"
WORKING_DIR = os.path.join(BASE_DIR, "Working")
SOURCE_VIDEO = os.path.join(WORKING_DIR, "One Foot in The Grave s04e05 5. The Trial.mp4")

TOOLS_DIR = os.path.join(BASE_DIR, "tools")
REALESRGAN_BIN = os.path.join(TOOLS_DIR, "realesrgan", "realesrgan-ncnn-vulkan")
MODELS_DIR = os.path.join(TOOLS_DIR, "realesrgan", "models")

CHUNKS_DIR = os.path.join(BASE_DIR, "chunks")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
LOG_FILE = os.path.join(BASE_DIR, "pipeline.log")
PROGRESS_JSON = os.path.join(BASE_DIR, "progress.json")

TMP_ROOT = "/tmp/oftg_full_pipeline"
CHUNK_DURATION = 60  # 60-second chunks (1,500 frames each)
TOTAL_DURATION = 1770.08  # 29m 30.08s
MODEL_NAME = "realesr-animevideov3"  # Compact high-speed 4x model
SCALE = "4"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def save_progress(current_chunk, total_chunks, chunk_start_time, total_start_time):
    elapsed_total = time.time() - total_start_time
    chunks_done = current_chunk
    percent = (chunks_done / total_chunks) * 100.0
    
    if chunks_done > 0:
        avg_chunk_time = elapsed_total / chunks_done
        remaining_chunks = total_chunks - chunks_done
        eta_seconds = remaining_chunks * avg_chunk_time
    else:
        avg_chunk_time = 0
        eta_seconds = total_chunks * 1800  # Default ~30m per chunk

    data = {
        "current_chunk": current_chunk,
        "total_chunks": total_chunks,
        "percent_complete": round(percent, 2),
        "elapsed_seconds": round(elapsed_total, 1),
        "elapsed_hours": round(elapsed_total / 3600, 2),
        "eta_seconds": round(eta_seconds, 1),
        "eta_hours": round(eta_seconds / 3600, 2),
        "updated_at": datetime.now().isoformat()
    }
    with open(PROGRESS_JSON, "w") as f:
        json.dump(data, f, indent=2)

def main():
    total_start = time.time()
    os.makedirs(CHUNKS_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TMP_ROOT, exist_ok=True)

    log("="*60)
    log("STARTING FULL EPISODE AI 1080p UPSCALING PIPELINE")
    log(f"Source Video: {SOURCE_VIDEO}")
    log(f"Model: {MODEL_NAME} (Scale {SCALE}x native + Lanczos 1080p downscale)")
    log(f"Total Duration: {TOTAL_DURATION}s (~29.5 minutes, 44,252 frames)")
    log(f"Chunk Size: {CHUNK_DURATION} seconds per chunk")
    log("="*60)

    # 1. Extract Full Lossless Audio Track
    full_audio = os.path.join(OUTPUT_DIR, "audio_full.aac")
    if not os.path.exists(full_audio):
        log("Extracting lossless full episode AAC audio track...")
        subprocess.run([
            "ffmpeg", "-y", "-i", SOURCE_VIDEO,
            "-vn", "-c:a", "copy", full_audio
        ], check=True)
        log("Full audio extracted successfully.")

    # 2. Calculate Chunks
    num_chunks = int(TOTAL_DURATION // CHUNK_DURATION) + (1 if TOTAL_DURATION % CHUNK_DURATION > 0 else 0)
    log(f"Total Chunks to Process: {num_chunks}")

    chunk_files = []
    for chunk_idx in range(num_chunks):
        start_sec = chunk_idx * CHUNK_DURATION
        duration = min(CHUNK_DURATION, TOTAL_DURATION - start_sec)
        chunk_out = os.path.join(CHUNKS_DIR, f"chunk_{chunk_idx:02d}_1080p.mp4")
        chunk_files.append(chunk_out)

        if os.path.exists(chunk_out) and os.path.getsize(chunk_out) > 100000:
            log(f"Chunk {chunk_idx + 1}/{num_chunks} already completed ({chunk_out}). Skipping.")
            continue

        log(f"\n--- PROCESSING CHUNK {chunk_idx + 1}/{num_chunks} (Start: {start_sec}s, Duration: {duration:.2f}s) ---")
        chunk_start = time.time()
        
        # Temp paths on internal fast SSD
        tmp_in = os.path.join(TMP_ROOT, f"chunk_{chunk_idx:02d}_in")
        tmp_out = os.path.join(TMP_ROOT, f"chunk_{chunk_idx:02d}_out")
        shutil.rmtree(tmp_in, ignore_errors=True)
        shutil.rmtree(tmp_out, ignore_errors=True)
        os.makedirs(tmp_in, exist_ok=True)
        os.makedirs(tmp_out, exist_ok=True)

        try:
            # A. Extract frames for this chunk
            log(f"Extracting frames for chunk {chunk_idx + 1}...")
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(start_sec), "-i", SOURCE_VIDEO,
                "-t", str(duration), os.path.join(tmp_in, "frame_%05d.png")
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            num_frames = len(os.listdir(tmp_in))
            log(f"Extracted {num_frames} frames to {tmp_in}.")

            # B. Run AI Super-Resolution on M4 GPU
            log(f"Running Real-ESRGAN on M4 GPU ({num_frames} frames)...")
            infer_start = time.time()
            subprocess.run([
                REALESRGAN_BIN,
                "-i", tmp_in,
                "-o", tmp_out,
                "-m", MODELS_DIR,
                "-n", MODEL_NAME,
                "-s", SCALE,
                "-f", "png"
            ], check=True)
            infer_time = time.time() - infer_start
            fps = num_frames / infer_time if infer_time > 0 else 0
            log(f"GPU Super-Resolution complete in {infer_time:.2f}s ({fps:.2f} fps).")

            # C. Encode chunk to 1080p with VideoToolbox hardware encoder
            log(f"Downscaling and hardware encoding chunk {chunk_idx + 1} to 1080p...")
            subprocess.run([
                "ffmpeg", "-y", "-framerate", "25",
                "-i", os.path.join(tmp_out, "frame_%05d.png"),
                "-vf", "scale=1440:1080:flags=lanczos",
                "-c:v", "h264_videotoolbox", "-b:v", "9M",
                "-pix_fmt", "yuv420p",
                chunk_out
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            chunk_elapsed = time.time() - chunk_start
            log(f"Chunk {chunk_idx + 1}/{num_chunks} finished in {chunk_elapsed/60:.2f} minutes -> {chunk_out}")

        finally:
            # Clean up temp frames immediately to conserve disk space
            shutil.rmtree(tmp_in, ignore_errors=True)
            shutil.rmtree(tmp_out, ignore_errors=True)
            save_progress(chunk_idx + 1, num_chunks, chunk_start, total_start)

    # 3. Concatenate all Chunks
    log("\n" + "="*60)
    log("ALL CHUNKS COMPLETED. ASSEMBLING FINAL MASTER RELEASES...")
    log("="*60)

    concat_list = os.path.join(CHUNKS_DIR, "concat_list.txt")
    with open(concat_list, "w") as f:
        for c in chunk_files:
            f.write(f"file '{c}'\n")

    raw_concat_video = os.path.join(TMP_ROOT, "concat_video_only.mp4")
    log("Concatenating video stream...")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list, "-c", "copy", raw_concat_video
    ], check=True)

    # 4. Final Deliverable 1: Native 4:3 Master (1440x1080)
    master_43 = os.path.join(OUTPUT_DIR, "One Foot in The Grave s04e05 - 1080p (4-3 Master).mp4")
    log(f"Multiplexing final Native 4:3 Master -> {master_43}...")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", raw_concat_video,
        "-i", full_audio,
        "-c:v", "copy",
        "-c:a", "copy",
        master_43
    ], check=True)

    # 5. Final Deliverable 2: Broadcast 16:9 Pillarbox Master (1920x1080)
    master_169 = os.path.join(OUTPUT_DIR, "One Foot in The Grave s04e05 - 1080p (16-9 Pillarbox).mp4")
    log(f"Generating Broadcast 16:9 Pillarbox Master -> {master_169}...")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", master_43,
        "-vf", "pad=1920:1080:240:0:black",
        "-c:v", "h264_videotoolbox", "-b:v", "10M",
        "-c:a", "copy",
        master_169
    ], check=True)

    # Clean up temp root
    shutil.rmtree(TMP_ROOT, ignore_errors=True)

    total_time = time.time() - total_start
    log("="*60)
    log("FULL EPISODE 1080p REMASTERING COMPLETED SUCCESSFULLY!")
    log(f"Native 4:3 Master: {master_43}")
    log(f"Broadcast 16:9 Master: {master_169}")
    log(f"Total Execution Time: {total_time/3600:.2f} hours ({total_time/60:.1f} minutes)")
    log("="*60)

if __name__ == "__main__":
    main()
