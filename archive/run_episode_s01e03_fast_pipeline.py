#!/usr/bin/env python3
import os
import sys
import json
import time
import shutil
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- CONFIGURATION ---
BASE_DIR = "/Volumes/Seagate External/Development/Manhattan"
WORKING_DIR = os.path.join(BASE_DIR, "Working")
SOURCE_VIDEO = os.path.join(WORKING_DIR, "One Foot in The Grave s01e03 3. The Valley of Fear.mp4")

TOOLS_DIR = os.path.join(BASE_DIR, "tools")
REALESRGAN_BIN = os.path.join(TOOLS_DIR, "realesrgan", "realesrgan-ncnn-vulkan")
MODELS_DIR = os.path.join(TOOLS_DIR, "realesrgan", "models")

CHUNKS_DIR = os.path.join(BASE_DIR, "chunks_s01e03")
OUTPUT_DIR = os.path.join(BASE_DIR, "output_s01e03")
LOG_FILE = os.path.join(BASE_DIR, "s01e03_pipeline.log")
PROGRESS_JSON = os.path.join(BASE_DIR, "s01e03_progress.json")
TIMING_REPORT_JSON = os.path.join(BASE_DIR, "s01e03_timing_report.json")

RAM_DISK = "/Volumes/ManhattanRAM"
CHUNK_DURATION = 60  # 60-second chunks (1,500 frames each)
TOTAL_DURATION = 1745.72  # 29m 05.72s (43,643 frames)
MODEL_NAME = "realesr-animevideov3"  # Compact high-speed 4x model
SCALE = "4"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def ensure_ram_disk():
    if not os.path.exists(RAM_DISK):
        log("Mounting 4GB APFS RAM Disk at /Volumes/ManhattanRAM...")
        res = subprocess.run("hdiutil attach -nomount ram://8388608", shell=True, capture_output=True, text=True, check=True)
        dev = res.stdout.strip()
        subprocess.run(f"diskutil erasevolume APFS ManhattanRAM {dev}", shell=True, check=True)
        log(f"RAM Disk mounted successfully on {dev}.")

def main():
    total_start = time.time()
    ensure_ram_disk()
    os.makedirs(CHUNKS_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    log("="*60)
    log("STARTING HIGH-SPEED IN-MEMORY AI REMASTERING PIPELINE (S01E03)")
    log(f"Source Video: {SOURCE_VIDEO}")
    log(f"Memory Architecture: 4.0 GB APFS RAM Disk in Unified Memory ({RAM_DISK})")
    log(f"Threading: Multi-thread tuned (-j 2:2:2)")
    log(f"Total Duration: {TOTAL_DURATION}s (43,643 frames @ 25.0 fps)")
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

    chunk_files_1080p = []
    chunk_files_4k = []
    chunk_timings = []

    for chunk_idx in range(num_chunks):
        start_sec = chunk_idx * CHUNK_DURATION
        duration = min(CHUNK_DURATION, TOTAL_DURATION - start_sec)
        
        c_1080p = os.path.join(CHUNKS_DIR, f"chunk_{chunk_idx:02d}_1080p.mp4")
        c_4k = os.path.join(CHUNKS_DIR, f"chunk_{chunk_idx:02d}_4k.mp4")
        chunk_files_1080p.append(c_1080p)
        chunk_files_4k.append(c_4k)

        if os.path.exists(c_1080p) and os.path.exists(c_4k) and os.path.getsize(c_1080p) > 500000 and os.path.getsize(c_4k) > 1000000:
            log(f"Chunk {chunk_idx + 1}/{num_chunks} already completed. Skipping.")
            continue

        log(f"\n--- PROCESSING CHUNK {chunk_idx + 1}/{num_chunks} in RAM (Start: {start_sec}s, Duration: {duration:.2f}s) ---")
        chunk_start = time.time()

        ram_in = os.path.join(RAM_DISK, f"c{chunk_idx:02d}_in")
        ram_out = os.path.join(RAM_DISK, f"c{chunk_idx:02d}_out")
        shutil.rmtree(ram_in, ignore_errors=True)
        shutil.rmtree(ram_out, ignore_errors=True)
        os.makedirs(ram_in, exist_ok=True)
        os.makedirs(ram_out, exist_ok=True)

        try:
            # A. Extract frames to RAM Disk
            t0 = time.time()
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(start_sec), "-i", SOURCE_VIDEO,
                "-t", str(duration), os.path.join(ram_in, "frame_%05d.png")
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            t_extract = time.time() - t0
            num_frames = len(os.listdir(ram_in))

            # B. AI Super-Resolution in RAM on M4 GPU
            t0 = time.time()
            subprocess.run([
                REALESRGAN_BIN,
                "-i", ram_in,
                "-o", ram_out,
                "-m", MODELS_DIR,
                "-n", MODEL_NAME,
                "-s", SCALE,
                "-j", "2:2:2",
                "-f", "png"
            ], check=True)
            t_infer = time.time() - t0
            fps_infer = num_frames / t_infer if t_infer > 0 else 0

            # C. Dual Hardware Encode (1080p Lanczos + Native 4K HEVC)
            t0 = time.time()
            # 1080p
            subprocess.run([
                "ffmpeg", "-y", "-framerate", "25",
                "-i", os.path.join(ram_out, "frame_%05d.png"),
                "-vf", "scale=1440:1080:flags=lanczos",
                "-c:v", "h264_videotoolbox", "-b:v", "9M",
                "-pix_fmt", "yuv420p",
                c_1080p
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # 4K HEVC
            subprocess.run([
                "ffmpeg", "-y", "-framerate", "25",
                "-i", os.path.join(ram_out, "frame_%05d.png"),
                "-c:v", "hevc_videotoolbox", "-b:v", "28M",
                "-tag:v", "hvc1", "-pix_fmt", "yuv420p",
                c_4k
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            t_encode = time.time() - t0

            chunk_total = time.time() - chunk_start
            timing_entry = {
                "chunk_index": chunk_idx + 1,
                "frames": num_frames,
                "extract_seconds": round(t_extract, 2),
                "inference_seconds": round(t_infer, 2),
                "encode_seconds": round(t_encode, 2),
                "total_chunk_seconds": round(chunk_total, 2),
                "inference_fps": round(fps_infer, 2)
            }
            chunk_timings.append(timing_entry)

            log(f"Chunk {chunk_idx + 1}/{num_chunks} Completed in {chunk_total/60:.2f} mins (AI Speed: {fps_infer:.2f} fps)")

        finally:
            shutil.rmtree(ram_in, ignore_errors=True)
            shutil.rmtree(ram_out, ignore_errors=True)
            
            elapsed_so_far = time.time() - total_start
            pct = ((chunk_idx + 1) / num_chunks) * 100.0
            avg_per_chunk = elapsed_so_far / (chunk_idx + 1)
            eta = (num_chunks - (chunk_idx + 1)) * avg_per_chunk
            with open(PROGRESS_JSON, "w") as pf:
                json.dump({
                    "current_chunk": chunk_idx + 1,
                    "total_chunks": num_chunks,
                    "percent_complete": round(pct, 2),
                    "elapsed_hours": round(elapsed_so_far / 3600, 2),
                    "eta_hours": round(eta / 3600, 2),
                    "updated_at": datetime.now().isoformat()
                }, pf, indent=2)

    # 3. Assemble Masters
    log("\n" + "="*60)
    log("ASSEMBLING FINAL HD & 4K MASTERS FOR S01E03...")
    log("="*60)

    # Concat 1080p
    concat_1080p_list = os.path.join(CHUNKS_DIR, "concat_1080p.txt")
    with open(concat_1080p_list, "w") as f:
        for c in chunk_files_1080p:
            f.write(f"file '{c}'\n")
    
    master_1080p_43 = os.path.join(OUTPUT_DIR, "One Foot in The Grave s01e03 - 1080p (4-3 Master).mp4")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_1080p_list,
        "-i", full_audio, "-c:v", "copy", "-c:a", "copy", master_1080p_43
    ], check=True)

    master_1080p_169 = os.path.join(OUTPUT_DIR, "One Foot in The Grave s01e03 - 1080p (16-9 Pillarbox).mp4")
    subprocess.run([
        "ffmpeg", "-y", "-i", master_1080p_43, "-vf", "pad=1920:1080:240:0:black",
        "-c:v", "h264_videotoolbox", "-b:v", "10M", "-c:a", "copy", master_1080p_169
    ], check=True)

    # Concat 4K
    concat_4k_list = os.path.join(CHUNKS_DIR, "concat_4k.txt")
    with open(concat_4k_list, "w") as f:
        for c in chunk_files_4k:
            f.write(f"file '{c}'\n")

    master_4k_43 = os.path.join(OUTPUT_DIR, "One Foot in The Grave s01e03 - 4K UHD (4-3 Master).mp4")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_4k_list,
        "-i", full_audio, "-c:v", "copy", "-c:a", "copy", master_4k_43
    ], check=True)

    master_4k_169 = os.path.join(OUTPUT_DIR, "One Foot in The Grave s01e03 - 4K UHD (16-9 Pillarbox).mp4")
    subprocess.run([
        "ffmpeg", "-y", "-i", master_4k_43, "-vf", "pad=3840:2160:480:0:black",
        "-c:v", "hevc_videotoolbox", "-b:v", "30M", "-tag:v", "hvc1", "-c:a", "copy", master_4k_169
    ], check=True)

    total_time = time.time() - total_start
    log("="*60)
    log("S01E03 REMASTERING COMPLETED SUCCESSFULLY!")
    log(f"1080p Master: {master_1080p_43}")
    log(f"4K UHD Master: {master_4k_43}")
    log(f"Total Execution Time: {total_time/3600:.2f} hours ({total_time/60:.1f} minutes)")
    log("="*60)

    # Write Final Timing Comparison Report
    with open(TIMING_REPORT_JSON, "w") as tf:
        json.dump({
            "episode": "One Foot in The Grave s01e03 (The Valley of Fear)",
            "total_frames": 43643,
            "total_duration_seconds": TOTAL_DURATION,
            "total_runtime_seconds": round(total_time, 2),
            "total_runtime_hours": round(total_time / 3600, 2),
            "average_fps": round(43643 / total_time, 2),
            "chunk_timings": chunk_timings
        }, tf, indent=2)

if __name__ == "__main__":
    main()
