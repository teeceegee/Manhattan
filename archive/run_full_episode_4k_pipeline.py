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

CHUNKS_4K_DIR = os.path.join(BASE_DIR, "chunks_4k")
OUTPUT_4K_DIR = os.path.join(BASE_DIR, "output_4k")
LOG_FILE = os.path.join(BASE_DIR, "pipeline_4k.log")
PROGRESS_JSON = os.path.join(BASE_DIR, "progress_4k.json")

TMP_ROOT = "/tmp/oftg_4k_pipeline"
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
        eta_seconds = total_chunks * 540  # Default ~9m per chunk

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
    os.makedirs(CHUNKS_4K_DIR, exist_ok=True)
    os.makedirs(OUTPUT_4K_DIR, exist_ok=True)
    os.makedirs(TMP_ROOT, exist_ok=True)

    log("="*60)
    log("STARTING FULL EPISODE AI 4K UHD REMASTERING PIPELINE")
    log(f"Source Video: {SOURCE_VIDEO}")
    log(f"Model: {MODEL_NAME} (Native 4x UHD Tensor Synthesis -> 2880x2160)")
    log(f"Target Codec: HEVC/H.265 (Apple VideoToolbox hevc_videotoolbox @ 28 Mbps)")
    log(f"Total Duration: {TOTAL_DURATION}s (~29.5 minutes, 44,252 frames)")
    log(f"Chunk Size: {CHUNK_DURATION} seconds per chunk (30 chunks total)")
    log("="*60)

    # 1. Extract Full Lossless Audio Track
    full_audio = os.path.join(OUTPUT_4K_DIR, "audio_full.aac")
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
        chunk_out = os.path.join(CHUNKS_4K_DIR, f"chunk_{chunk_idx:02d}_4k.mp4")
        chunk_files.append(chunk_out)

        if os.path.exists(chunk_out) and os.path.getsize(chunk_out) > 1000000:
            log(f"Chunk {chunk_idx + 1}/{num_chunks} already completed ({chunk_out}). Skipping.")
            continue

        log(f"\n--- PROCESSING 4K CHUNK {chunk_idx + 1}/{num_chunks} (Start: {start_sec}s, Duration: {duration:.2f}s) ---")
        chunk_start = time.time()
        
        # Temp paths on internal fast NVMe SSD
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

            # B. Run AI Super-Resolution on M4 GPU (Native 4x = 2880x2160)
            log(f"Running Real-ESRGAN 4x on M4 GPU ({num_frames} frames)...")
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

            # C. Encode full 4K frame sequence with Apple Silicon hevc_videotoolbox
            log(f"Encoding full 4K UHD chunk {chunk_idx + 1} with HEVC VideoToolbox...")
            subprocess.run([
                "ffmpeg", "-y", "-framerate", "25",
                "-i", os.path.join(tmp_out, "frame_%05d.png"),
                "-c:v", "hevc_videotoolbox", "-b:v", "28M",
                "-tag:v", "hvc1", "-pix_fmt", "yuv420p",
                chunk_out
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            chunk_elapsed = time.time() - chunk_start
            log(f"4K Chunk {chunk_idx + 1}/{num_chunks} finished in {chunk_elapsed/60:.2f} minutes -> {chunk_out}")

        finally:
            # Clean up temp frames immediately to conserve internal SSD space
            shutil.rmtree(tmp_in, ignore_errors=True)
            shutil.rmtree(tmp_out, ignore_errors=True)
            save_progress(chunk_idx + 1, num_chunks, chunk_start, total_start)

    # 3. Concatenate all 4K Chunks
    log("\n" + "="*60)
    log("ALL 4K CHUNKS COMPLETED. ASSEMBLING FINAL 4K UHD MASTER RELEASES...")
    log("="*60)

    concat_list = os.path.join(CHUNKS_4K_DIR, "concat_list.txt")
    with open(concat_list, "w") as f:
        for c in chunk_files:
            f.write(f"file '{c}'\n")

    raw_concat_video = os.path.join(TMP_ROOT, "concat_video_4k_only.mp4")
    log("Concatenating 4K video streams...")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list, "-c", "copy", raw_concat_video
    ], check=True)

    # 4. Final Deliverable 1: Native 4:3 4K Master (2880x2160 HEVC)
    master_43 = os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s04e05 - 4K UHD (4-3 Master).mp4")
    log(f"Multiplexing final Native 4:3 4K Master -> {master_43}...")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", raw_concat_video,
        "-i", full_audio,
        "-c:v", "copy",
        "-c:a", "copy",
        master_43
    ], check=True)

    # 5. Final Deliverable 2: Broadcast 16:9 Pillarbox 4K Master (3840x2160 HEVC)
    master_169 = os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s04e05 - 4K UHD (16-9 Pillarbox).mp4")
    log(f"Generating Broadcast 16:9 4K UHD Pillarbox Master -> {master_169}...")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", master_43,
        "-vf", "pad=3840:2160:480:0:black",
        "-c:v", "hevc_videotoolbox", "-b:v", "30M",
        "-tag:v", "hvc1",
        "-c:a", "copy",
        master_169
    ], check=True)

    # Clean up temp root
    shutil.rmtree(TMP_ROOT, ignore_errors=True)

    total_time = time.time() - total_start
    log("="*60)
    log("FULL EPISODE 4K UHD REMASTERING COMPLETED SUCCESSFULLY!")
    log(f"Native 4:3 4K Master (2880x2160): {master_43}")
    log(f"Broadcast 16:9 4K UHD Master (3840x2160): {master_169}")
    log(f"Total Execution Time: {total_time/3600:.2f} hours ({total_time/60:.1f} minutes)")
    log("="*60)

if __name__ == "__main__":
    main()
