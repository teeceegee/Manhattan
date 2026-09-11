#!/usr/bin/env python3
import os
import sys
import json
import time
import subprocess
from datetime import datetime
import numpy as np
import coremltools as ct

# --- CONFIGURATION ---
BASE_DIR = "/Volumes/Seagate External/Development/Manhattan"
WORKING_DIR = os.path.join(BASE_DIR, "Working")
SOURCE_VIDEO = os.path.join(WORKING_DIR, "One Foot in The Grave s01e03 3. The Valley of Fear.mp4")

TOOLS_DIR = os.path.join(BASE_DIR, "tools")
MODEL_PATH = os.path.join(TOOLS_DIR, "realesrgan", "models", "realesr_animevideov3_4k.mlpackage")

CHUNKS_4K_DIR = os.path.join(BASE_DIR, "chunks_s01e03_4k")
OUTPUT_4K_DIR = os.path.join(BASE_DIR, "output_4k")
LOG_FILE = os.path.join(BASE_DIR, "s01e03_4k_streaming.log")
PROGRESS_JSON = os.path.join(BASE_DIR, "s01e03_4k_progress.json")
TIMING_REPORT_JSON = os.path.join(BASE_DIR, "s01e03_4k_timing_report.json")

CHUNK_DURATION = 60  # 60-second chunks (1,500 frames each)
TOTAL_DURATION = 1745.72  # 29m 05.72s (43,643 frames)
IN_W, IN_H = 720, 540
OUT_W, OUT_H = 2880, 2160
FRAME_IN_BYTES = IN_W * IN_H * 3

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def main():
    total_start = time.time()
    os.makedirs(CHUNKS_4K_DIR, exist_ok=True)
    os.makedirs(OUTPUT_4K_DIR, exist_ok=True)

    log("="*60)
    log("STARTING ZERO-DISK STREAMING APPLE NEURAL ENGINE 4K REMASTERING")
    log(f"Source Video: {SOURCE_VIDEO}")
    log(f"Architecture: Direct In-Memory Video Pipe -> CoreML (ANE 38 TOPS + GPU) -> VideoToolbox HEVC")
    log(f"Model: {MODEL_PATH}")
    log(f"Total Video Duration: {TOTAL_DURATION}s (43,643 frames @ 25.0 fps)")
    log(f"Target Master: 4K UHD Only (2880x2160 Native & 3840x2160 Broadcast HEVC)")
    log("="*60)

    # 1. Load CoreML Model
    log("Loading CoreML Apple Neural Engine Model...")
    mlmodel = ct.models.MLModel(MODEL_PATH, compute_units=ct.ComputeUnit.ALL)
    log("CoreML Model loaded with compute_units=ALL.")

    # 2. Extract Lossless Full Episode Audio Track
    full_audio = os.path.join(OUTPUT_4K_DIR, "s01e03_audio_full.aac")
    if not os.path.exists(full_audio):
        log("Extracting lossless AAC audio track...")
        subprocess.run([
            "ffmpeg", "-y", "-i", SOURCE_VIDEO,
            "-vn", "-c:a", "copy", full_audio
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("Lossless audio extracted.")

    # 3. Calculate Chunks
    num_chunks = int(TOTAL_DURATION // CHUNK_DURATION) + (1 if TOTAL_DURATION % CHUNK_DURATION > 0 else 0)
    log(f"Total Chunks: {num_chunks}")

    chunk_files_4k = []
    chunk_timings = []

    for chunk_idx in range(num_chunks):
        start_sec = chunk_idx * CHUNK_DURATION
        duration = min(CHUNK_DURATION, TOTAL_DURATION - start_sec)
        c_4k = os.path.join(CHUNKS_4K_DIR, f"chunk_{chunk_idx:02d}_4k.mp4")
        chunk_files_4k.append(c_4k)

        if os.path.exists(c_4k) and os.path.getsize(c_4k) > 1000000:
            log(f"Chunk {chunk_idx + 1}/{num_chunks} already completed. Skipping.")
            continue

        log(f"\n--- PROCESSING CHUNK {chunk_idx + 1}/{num_chunks} via Direct Memory Streaming (Start: {start_sec}s, Duration: {duration:.2f}s) ---")
        chunk_start = time.time()

        cmd_in = [
            "ffmpeg", "-y", "-ss", str(start_sec), "-i", SOURCE_VIDEO,
            "-t", str(duration),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"
        ]
        cmd_out = [
            "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{OUT_W}x{OUT_H}", "-r", "25", "-i", "-",
            "-c:v", "hevc_videotoolbox", "-b:v", "28M",
            "-tag:v", "hvc1", "-pix_fmt", "yuv420p",
            c_4k
        ]

        p_in = subprocess.Popen(cmd_in, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        p_out = subprocess.Popen(cmd_out, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

        num_frames = 0
        try:
            while True:
                raw_bytes = p_in.stdout.read(FRAME_IN_BYTES)
                if not raw_bytes or len(raw_bytes) < FRAME_IN_BYTES:
                    break
                
                # In-memory numpy array (540, 720, 3) normalized [0, 1]
                in_arr = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((IN_H, IN_W, 3)).astype(np.float32) / 255.0
                input_tensor = np.transpose(in_arr, (2, 0, 1))[np.newaxis, ...]

                # CoreML ANE Super-Resolution
                res = mlmodel.predict({'input': input_tensor})
                out_var = list(res.keys())[0]
                out_tensor = res[out_var][0]

                # Convert to uint8 and stream directly to VideoToolbox encoder
                out_arr = np.clip(np.transpose(out_tensor, (1, 2, 0)) * 255.0, 0, 255).astype(np.uint8)
                p_out.stdin.write(out_arr.tobytes())
                num_frames += 1

        finally:
            p_in.stdout.close()
            p_out.stdin.close()
            p_in.wait()
            p_out.wait()

        chunk_total = time.time() - chunk_start
        fps_chunk = num_frames / chunk_total if chunk_total > 0 else 0

        timing_entry = {
            "chunk_index": chunk_idx + 1,
            "frames": num_frames,
            "total_chunk_seconds": round(chunk_total, 2),
            "effective_fps": round(fps_chunk, 2)
        }
        chunk_timings.append(timing_entry)

        log(f"Chunk {chunk_idx + 1}/{num_chunks} Completed in {chunk_total/60:.2f} mins ({num_frames} frames @ {fps_chunk:.2f} fps)")

        # Update progress
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
                "average_fps": round(fps_chunk, 2),
                "updated_at": datetime.now().isoformat()
            }, pf, indent=2)

    # 4. Assemble Final 4K Masters
    log("\n" + "="*60)
    log("ALL CHUNKS FINISHED. ASSEMBLING FINAL 4K UHD MASTERS...")
    log("="*60)

    concat_4k_list = os.path.join(CHUNKS_4K_DIR, "concat_4k.txt")
    with open(concat_4k_list, "w") as f:
        for c in chunk_files_4k:
            f.write(f"file '{c}'\n")

    raw_concat_video = os.path.join(CHUNKS_4K_DIR, "concat_video_4k_only.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_4k_list,
        "-c", "copy", raw_concat_video
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Master 1: Native 4:3 4K Master (2880x2160 HEVC)
    master_4k_43 = os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s01e03 - 4K UHD (4-3 Master).mp4")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", raw_concat_video,
        "-i", full_audio,
        "-c:v", "copy",
        "-c:a", "copy",
        master_4k_43
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Master 2: Broadcast 16:9 4K UHD Pillarbox Master (3840x2160 HEVC)
    master_4k_169 = os.path.join(OUTPUT_4K_DIR, "One Foot in The Grave s01e03 - 4K UHD (16-9 Pillarbox).mp4")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", master_4k_43,
        "-vf", "pad=3840:2160:480:0:black",
        "-c:v", "hevc_videotoolbox", "-b:v", "30M",
        "-tag:v", "hvc1",
        "-c:a", "copy",
        master_4k_169
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if os.path.exists(raw_concat_video):
        os.remove(raw_concat_video)

    total_time = time.time() - total_start
    log("="*60)
    log("S01E03 4K UHD REMASTERING FULLY COMPLETED!")
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
