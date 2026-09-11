#!/usr/bin/env python3
import os
import sys
import json
import time
import shutil
import subprocess
from datetime import datetime
import numpy as np
import cv2
import coremltools as ct

# --- CONFIGURATION ---
BASE_DIR = "/Volumes/Seagate External/Development/Manhattan"
WORKING_DIR = os.path.join(BASE_DIR, "Working")
SOURCE_VIDEO = os.path.join(WORKING_DIR, "One Foot in The Grave s01e03 3. The Valley of Fear.mp4")

TOOLS_DIR = os.path.join(BASE_DIR, "tools")
MODEL_PATH = os.path.join(TOOLS_DIR, "realesrgan", "models", "realesr_animevideov3_4k.mlpackage")

CHUNKS_4K_DIR = os.path.join(BASE_DIR, "chunks_s01e03_4k")
OUTPUT_4K_DIR = os.path.join(BASE_DIR, "output_4k")
LOG_FILE = os.path.join(BASE_DIR, "s01e03_4k_coreml.log")
PROGRESS_JSON = os.path.join(BASE_DIR, "s01e03_4k_progress.json")
TIMING_REPORT_JSON = os.path.join(BASE_DIR, "s01e03_4k_timing_report.json")

RAM_DISK = "/Volumes/ManhattanRAM"
CHUNK_DURATION = 60  # 60-second chunks (1,500 frames each)
TOTAL_DURATION = 1745.72  # 29m 05.72s (43,643 frames)

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
    os.makedirs(CHUNKS_4K_DIR, exist_ok=True)
    os.makedirs(OUTPUT_4K_DIR, exist_ok=True)

    log("="*60)
    log("STARTING NATIVE APPLE NEURAL ENGINE (ANE) 4K REMASTERING (S01E03)")
    log(f"Source Video: {SOURCE_VIDEO}")
    log(f"Engine: Native Apple CoreML (16-Core ANE + Metal GPU) @ {MODEL_PATH}")
    log(f"Target Output: 4K UHD Only (2880x2160 Native 4:3 & 3840x2160 16:9 HEVC)")
    log(f"Total Duration: {TOTAL_DURATION}s (43,643 frames @ 25.0 fps)")
    log(f"Chunk Size: {CHUNK_DURATION} seconds per chunk")
    log("="*60)

    # 1. Load CoreML Model
    log("Loading CoreML Neural Engine Model...")
    mlmodel = ct.models.MLModel(MODEL_PATH, compute_units=ct.ComputeUnit.ALL)
    log("CoreML Model loaded successfully with compute_units=ALL (ANE+GPU).")

    # 2. Extract Full Lossless Audio Track
    full_audio = os.path.join(OUTPUT_4K_DIR, "s01e03_audio_full.aac")
    if not os.path.exists(full_audio):
        log("Extracting lossless full episode AAC audio track...")
        subprocess.run([
            "ffmpeg", "-y", "-i", SOURCE_VIDEO,
            "-vn", "-c:a", "copy", full_audio
        ], check=True)
        log("Full audio extracted successfully.")

    # 3. Calculate Chunks
    num_chunks = int(TOTAL_DURATION // CHUNK_DURATION) + (1 if TOTAL_DURATION % CHUNK_DURATION > 0 else 0)
    log(f"Total Chunks to Process: {num_chunks}")

    chunk_files_4k = []
    chunk_timings = []

    for chunk_idx in range(num_chunks):
        start_sec = chunk_idx * CHUNK_DURATION
        duration = min(CHUNK_DURATION, TOTAL_DURATION - start_sec)
        c_4k = os.path.join(CHUNKS_4K_DIR, f"chunk_{chunk_idx:02d}_4k.mp4")
        chunk_files_4k.append(c_4k)

        if os.path.exists(c_4k) and os.path.getsize(c_4k) > 1000000:
            log(f"Chunk {chunk_idx + 1}/{num_chunks} already completed ({c_4k}). Skipping.")
            continue

        log(f"\n--- PROCESSING 4K CHUNK {chunk_idx + 1}/{num_chunks} on ANE (Start: {start_sec}s, Duration: {duration:.2f}s) ---")
        chunk_start = time.time()

        # Direct in-memory extraction & upscale
        raw_in_dir = os.path.join(RAM_DISK, f"c{chunk_idx:02d}_in")
        raw_out_dir = os.path.join(RAM_DISK, f"c{chunk_idx:02d}_out")
        shutil.rmtree(raw_in_dir, ignore_errors=True)
        shutil.rmtree(raw_out_dir, ignore_errors=True)
        os.makedirs(raw_in_dir, exist_ok=True)
        os.makedirs(raw_out_dir, exist_ok=True)

        try:
            # A. Extract frames to RAM
            t0 = time.time()
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(start_sec), "-i", SOURCE_VIDEO,
                "-t", str(duration), os.path.join(raw_in_dir, "frame_%05d.png")
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            t_extract = time.time() - t0
            
            frame_names = sorted(os.listdir(raw_in_dir))
            num_frames = len(frame_names)

            # B. Run CoreML Apple Neural Engine Super-Resolution
            t0 = time.time()
            for fname in frame_names:
                in_path = os.path.join(raw_in_dir, fname)
                out_path = os.path.join(raw_out_dir, fname)

                # Read image
                img_bgr = cv2.imread(in_path)
                img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
                input_tensor = np.transpose(img_rgb, (2, 0, 1))[np.newaxis, ...]

                # CoreML inference on ANE
                res = mlmodel.predict({'input': input_tensor})
                out_var = list(res.keys())[0]
                out_tensor = res[out_var][0]

                # Convert to BGR and save
                out_img = np.clip(np.transpose(out_tensor, (1, 2, 0)) * 255.0, 0, 255).astype(np.uint8)
                out_bgr = cv2.cvtColor(out_img, cv2.COLOR_RGB2BGR)
                cv2.imwrite(out_path, out_bgr)

            t_infer = time.time() - t0
            fps_infer = num_frames / t_infer if t_infer > 0 else 0

            # C. Encode to 4K HEVC with VideoToolbox hardware encoder
            t0 = time.time()
            subprocess.run([
                "ffmpeg", "-y", "-framerate", "25",
                "-i", os.path.join(raw_out_dir, "frame_%05d.png"),
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

            log(f"4K Chunk {chunk_idx + 1}/{num_chunks} Completed in {chunk_total/60:.2f} mins (ANE Speed: {fps_infer:.2f} fps)")

        finally:
            shutil.rmtree(raw_in_dir, ignore_errors=True)
            shutil.rmtree(raw_out_dir, ignore_errors=True)
            
            elapsed_so_far = time.time() - total_start
            pct = ((chunk_idx + 1) / num_chunks) * 100.0
            avg_per_chunk = elapsed_so_far / (chunk_idx + 1)
            eta = (num_chunks - (chunk_idx + 1)) * avg_per_chunk
            with open(PROGRESS_JSON, "w") as pf:
                json.dump({
                    "current_chunk": chunk_idx + 1,
                    "total_chunks": num_chunks,
                    "percent_complete": round(pct, 2),
                    "elapsed_minutes": round(elapsed_so_far / 60, 2),
                    "elapsed_hours": round(elapsed_so_far / 3600, 2),
                    "eta_minutes": round(eta / 60, 2),
                    "eta_hours": round(eta / 3600, 2),
                    "updated_at": datetime.now().isoformat()
                }, pf, indent=2)

    # 4. Assemble Final 4K Masters
    log("\n" + "="*60)
    log("ALL 4K CHUNKS COMPLETED. ASSEMBLING FINAL 4K UHD MASTERS FOR S01E03...")
    log("="*60)

    concat_4k_list = os.path.join(CHUNKS_4K_DIR, "concat_4k.txt")
    with open(concat_4k_list, "w") as f:
        for c in chunk_files_4k:
            f.write(f"file '{c}'\n")

    raw_concat_video = os.path.join(CHUNKS_4K_DIR, "concat_video_4k_only.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_4k_list,
        "-c", "copy", raw_concat_video
    ], check=True)

    # Deliverable 1: Native 4:3 4K Master (2880x2160 HEVC)
    master_4k_43 = os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s01e03 - 4K UHD (4-3 Master).mp4")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", raw_concat_video,
        "-i", full_audio,
        "-c:v", "copy",
        "-c:a", "copy",
        master_4k_43
    ], check=True)

    # Deliverable 2: Broadcast 16:9 4K UHD Pillarbox Master (3840x2160 HEVC)
    master_4k_169 = os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s01e03 - 4K UHD (16-9 Pillarbox).mp4")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", master_4k_43,
        "-vf", "pad=3840:2160:480:0:black",
        "-c:v", "hevc_videotoolbox", "-b:v", "30M",
        "-tag:v", "hvc1",
        "-c:a", "copy",
        master_4k_169
    ], check=True)

    if os.path.exists(raw_concat_video):
        os.remove(raw_concat_video)

    total_time = time.time() - total_start
    log("="*60)
    log("S01E03 4K UHD COREML REMASTERING COMPLETED SUCCESSFULLY!")
    log(f"Native 4:3 4K Master (2880x2160): {master_4k_43}")
    log(f"Broadcast 16:9 4K UHD Master (3840x2160): {master_4k_169}")
    log(f"Total Execution Time: {total_time/60:.2f} minutes ({total_time/3600:.2f} hours)")
    log("="*60)

    # Write Final Timing Comparison Report
    with open(TIMING_REPORT_JSON, "w") as tf:
        json.dump({
            "episode": "One Foot in The Grave s01e03 (The Valley of Fear)",
            "total_frames": 43643,
            "total_duration_seconds": TOTAL_DURATION,
            "total_runtime_seconds": round(total_time, 2),
            "total_runtime_minutes": round(total_time / 60, 2),
            "total_runtime_hours": round(total_time / 3600, 2),
            "average_fps": round(43643 / total_time, 2),
            "chunk_timings": chunk_timings
        }, tf, indent=2)

if __name__ == "__main__":
    main()
