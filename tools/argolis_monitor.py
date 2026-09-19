#!/usr/bin/env python3
"""
Argolis Real-Time System & AI Workload Monitor (Plain Monochrome UI)
Displays live CPU (E-Cores & P-Cores), Unified Memory, Storage,
and human-readable progress cards for active Neural Engine & GPU AI video streams.
"""

import os
import re
import sys
import glob
import time
import subprocess
import json
import sqlite3

# Ensure Manhattan virtualenv site-packages are accessible
venv_site = glob.glob("/Volumes/Seagate External/Development/Manhattan/venv/lib/python*/site-packages")
for p in venv_site:
    if p not in sys.path:
        sys.path.insert(0, p)

import psutil
from datetime import datetime

BASE_DIR = "/Volumes/Seagate External/Development/Manhattan"
LOG_DAEMON = os.path.join(BASE_DIR, "upscale_daemon.log")
LOG_BATCH = os.path.join(BASE_DIR, "batch_remaster.log")
HEVC_DB = "/Users/tony/Library/Application Support/ShadaHEVC/argolis-library-jobs.sqlite3"
HEVC_STAGING = "/Volumes/FastStorage/ShadaHEVC-Staging"

def get_latest_log():
    logs = [LOG_DAEMON, LOG_BATCH]
    existing = [f for f in logs if os.path.exists(f)]
    if not existing:
        return None
    return max(existing, key=os.path.getmtime)

def make_bar(percent, width=22):
    filled = int(width * (max(0.0, min(100.0, percent)) / 100.0))
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {percent:5.1f}%"

def fmt_bytes(value):
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1000

def live_upscale_active():
    """Use the real process list; a stale queue state must not imply activity."""
    try:
        for proc in psutil.process_iter(["cmdline"]):
            cmd = " ".join(proc.info.get("cmdline") or [])
            if "argolis-upscale" in cmd and "argolis_monitor" not in cmd and not any(cmd.lstrip().startswith(prefix) for prefix in ("sh -c", "bash -c", "zsh -c")):
                return True
    except (psutil.Error, OSError):
        pass
    return False

def hevc_progress():
    """Read the HEVC queue and active encoder without changing its state."""
    try:
        db = sqlite3.connect(f"file:{HEVC_DB}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        counts = dict(db.execute("select status,count(*) from jobs group by status").fetchall())
        total = sum(counts.values())
        done = counts.get("complete", 0) + counts.get("skipped", 0) + counts.get("permanent_failed", 0)
        saved = db.execute("select coalesce(sum(source_size-output_size),0) from jobs where status in ('complete','promoted') and source_size is not null and output_size is not null").fetchone()[0]
        original = db.execute("select coalesce(sum(source_size),0) from jobs where status in ('complete','promoted') and source_size is not null and output_size is not null").fetchone()[0]
        state = db.execute("select state,detail from worker_state where id=1").fetchone()
        active = db.execute("select source,output,duration_seconds from jobs where status='running' order by id desc limit 1").fetchone()
        db.close()
    except (OSError, sqlite3.Error):
        return {"error": "queue unavailable"}

    upscale_active = live_upscale_active()
    result = {"pct": done / total * 100 if total else 0, "done": done, "total": total,
              "saved": saved, "original": original, "state": state, "active": active,
              "upscale_active": upscale_active}
    if not active:
        return result
    output = active["output"]
    try:
        prefix = os.path.basename(output) + ".part."
        part = next((os.path.join(root, name) for root, _, files in os.walk(os.path.dirname(output)) for name in files if name.startswith(prefix) and not name.endswith(".log")), None)
        log = part + ".log" if part else None
        line = ""
        if log and os.path.exists(log):
            with open(log, errors="replace") as handle:
                for candidate in handle:
                    if "time=" in candidate and "speed=" in candidate:
                        line = candidate.strip()
        tm = re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
        speed = re.search(r"speed=\s*([\w.]+)", line)
        elapsed = (int(tm[1]) * 3600 + int(tm[2]) * 60 + float(tm[3])) if tm else 0
        duration = float(active["duration_seconds"] or 0)
        pct = elapsed / duration * 100 if duration else 0
        result["active_detail"] = f"{os.path.basename(active['source'])} | {make_bar(pct, 18)} | speed {speed[1] if speed else '?'} | temp {fmt_bytes(os.path.getsize(part)) if part else '?'}"
    except (OSError, ValueError, TypeError):
        result["active_detail"] = f"{os.path.basename(active['source'])} | progress unavailable"
    return result

def get_active_scratch_progress():
    for s_root in ["scratch_queue", "scratch_batch", "scratch_steptoe"]:
        s_path = os.path.join(BASE_DIR, s_root)
        if os.path.exists(s_path):
            subdirs = [os.path.join(s_path, d) for d in os.listdir(s_path) if os.path.isdir(os.path.join(s_path, d))]
            if subdirs:
                latest_subdir = max(subdirs, key=os.path.getmtime)
                # Count files > 500 KB (fully rendered chunks)
                done_files = [f for f in os.listdir(latest_subdir) if f.startswith("chunk_") and f.endswith(".mp4") and os.path.getsize(os.path.join(latest_subdir, f)) > 500000]
                return len(done_files), os.path.basename(latest_subdir)
    return 0, None

def parse_stream_telemetry(default_name):
    # 1. First check upscale_status.json on VIDEO mount
    episode = default_name
    for v_mount in ["/Volumes/VIDEO", "/Users/tony/VIDEO"]:
        status_f = os.path.join(v_mount, "upscale_status.json")
        if os.path.exists(status_f):
            try:
                with open(status_f, "r") as sf:
                    s_data = json.load(sf)
                    if "current_job" in s_data and s_data["current_job"] is None:
                        return {"episode": "Idle / Waiting for Queue Job...", "chunk": "—", "fps": "—", "mode": "—"}
                    cur_job = s_data.get("current_job")
                    if cur_job and cur_job.get("filename"):
                        episode = os.path.splitext(cur_job["filename"])[0]
            except Exception:
                pass

    log_file = get_latest_log()
    if not log_file or not os.path.exists(log_file):
        return None
    try:
        with open(log_file, "r") as f:
            lines = f.readlines()[-2000:]
    except Exception:
        return None

    chunk_str = "Initializing..."
    fps_str = "—"
    mode = "Full Color 1080p HEVC"
    total_chunks = 30

    # Find the most recent STARTING banner index
    start_idx = 0
    for idx, line in enumerate(lines):
        if "ARGOLIS NATIVE SWIFT ZERO-COPY" in line or "STARTING DUAL-ENGINE" in line or "STARTING DIRECT 1080p" in line or "STARTING 1080p HEVC" in line or "STARTING TEST REMASTER:" in line:
            start_idx = idx
            parts = line.split(":")
            if len(parts) > 1 and "ARGOLIS" not in line:
                ep_raw = parts[-1].strip().replace(".mp4", "")
                if "gpu_worker" not in ep_raw:
                    episode = ep_raw
        if "Input:" in line and idx >= start_idx:
            parts = line.split("Input:")
            if len(parts) > 1:
                episode = os.path.splitext(os.path.basename(parts[1].strip()))[0]
        if "Populating Work-Stealing Queue" in line and idx >= start_idx:
            m_total = re.search(r"with (\d+) streaming chunks", line)
            if m_total:
                total_chunks = int(m_total.group(1))
                chunk_str = f"Chunk 1/{total_chunks} (In progress...)"
        elif "Splitting into" in line and idx >= start_idx:
            m_total = re.search(r"Splitting into (\d+) streaming chunks", line)
            if m_total:
                total_chunks = int(m_total.group(1))
                chunk_str = f"Chunk 1/{total_chunks} (In progress...)"

    # Check direct live scratch inspection
    done_count, scratch_name = get_active_scratch_progress()
    if done_count > 0:
        chunk_str = f"Chunk {done_count}/{total_chunks} ({done_count/total_chunks*100:.1f}%)"

    # Only process lines from the current active run session
    for line in lines[start_idx:]:
        if "Mode:" in line:
            mode = line.split("Mode:")[-1].strip()
        if "Frame " in line and "Live Speed:" in line:
            m_f = re.search(r"Frame\s+(\d+/\d+\s+\(\d+\.\d+%\))\s+\|\s+Live Speed:\s+(\d+\.\d+\s+fps)", line)
            if m_f:
                chunk_str = f"Frame {m_f.group(1)}"
                fps_str = m_f.group(2)
        elif "Chunk " in line and "done:" in line:
            m = re.search(r"Chunk\s+(\d+/\d+)\s+done.*?\((\d+\.\d+\s+fps)\)", line)
            if m:
                fps_str = m.group(2)
        elif "Chunk " in line and "already complete" in line:
            m = re.search(r"Chunk\s+(\d+/\d+)\s+already complete", line)
            if m:
                chunk_str = f"Chunk {m.group(1)} (Skipped)"

    return {
        "episode": episode,
        "chunk": chunk_str,
        "fps": fps_str,
        "mode": mode
    }

def get_ai_processes():
    ai_procs = []
    for proc in psutil.process_iter():
        try:
            p_name = proc.name().lower()
            if not ("python" in p_name or "ffmpeg" in p_name or "argolis" in p_name or "swift" in p_name):
                continue

            cmd_list = proc.cmdline()
            cmd = " ".join(cmd_list) if cmd_list else ""
            if ("remaster" in cmd or "realesr" in cmd or "queue_daemon" in cmd or "gpu_stream" in cmd or "steptoe_piano" in cmd or "ffmpeg" in cmd or "argolis-upscale" in cmd or "argolis_upscale" in cmd) and not ("tail" in cmd or "grep" in cmd or "argolis_monitor" in cmd):
                mem_info = proc.memory_info()
                cpu_p = proc.cpu_percent(interval=None)
                ai_procs.append({
                    "pid": proc.pid,
                    "name": proc.name(),
                    "cmd": cmd,
                    "cpu": cpu_p,
                    "mem_mb": mem_info.rss / (1024 * 1024) if mem_info else 0
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, PermissionError, SystemError, Exception):
            continue
    return ai_procs

def main():
    sys.stdout.write("\033[?25l\033[2J")
    sys.stdout.flush()

    psutil.cpu_percent(percpu=True)
    time.sleep(0.2)

    hw_gpu_residency = "N/A"
    hw_ane_power = "N/A"
    
    is_root = os.geteuid() == 0
    power_proc = None
    import queue
    import threading
    
    if is_root:
        # Launch powermetrics in background
        power_proc = subprocess.Popen(
            ["powermetrics", "--samplers", "ane_power,gpu_power", "-i", "1000"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        q = queue.Queue()
        def reader_thread(out, queue):
            for line in iter(out.readline, b''):
                queue.put(line)
            out.close()
        t = threading.Thread(target=reader_thread, args=(power_proc.stdout, q))
        t.daemon = True
        t.start()
        
    try:
        while True:
            if is_root and power_proc:
                while not q.empty():
                    line = q.get()
                    if "GPU active residency:" in line or "GPU HW active residency:" in line or "GPU idle residency" in line:
                        # Sometimes GPU active residency: 14.5%
                        m = re.search(r"active residency:\s+([\d\.]+)%", line)
                        if m: hw_gpu_residency = f"{m.group(1)}%"
                    if "ANE Power:" in line or "ANE power:" in line or "ANE active" in line:
                        if "power:" in line.lower():
                            m = re.search(r"power:\s+(\d+\s+mW)", line, re.IGNORECASE)
                            if m: hw_ane_power = m.group(1)
                        if "residency:" in line.lower():
                            m = re.search(r"residency:\s+([\d\.]+)%", line, re.IGNORECASE)
                            if m: hw_ane_power = f"{m.group(1)}%"

            per_cpu = psutil.cpu_percent(interval=None, percpu=True)
            total_cpu = sum(per_cpu) / len(per_cpu) if per_cpu else 0
            mem = psutil.virtual_memory()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            buf = []
            buf.append("\033[H")
            buf.append("================================================================================\033[K")
            buf.append(f" ARGOLIS SYSTEM & AI WORKLOAD MONITOR (Apple M4 Mac Mini)  [{now_str}]\033[K")
            buf.append("================================================================================\033[K")
            buf.append("\033[K")

            # CPU Breakdown
            lbl_cpu = "[CPU USAGE]".ljust(18)
            buf.append(f"{lbl_cpu}{make_bar(total_cpu, 22)}  ({len(per_cpu)} Cores Active)\033[K")
            buf.append("Per-Core Breakdown:\033[K")
            for i in range(0, len(per_cpu), 2):
                c1 = f"  Core {i+1:02d}: {make_bar(per_cpu[i], 15)}"
                c2 = f"  Core {i+2:02d}: {make_bar(per_cpu[i+1], 15)}" if i+1 < len(per_cpu) else ""
                buf.append(f"{c1}  {c2}\033[K")

            buf.append("\033[K")
            if is_root:
                buf.append(f"[HARDWARE ACCELERATORS]\033[K")
                buf.append(f"  • 16-Core Neural Engine (ANE):  [Telemetry Blocked by Apple on M4]\033[K")
                buf.append(f"  • 10-Core Metal GPU:            {hw_gpu_residency}\033[K")
            else:
                buf.append(f"[HARDWARE ACCELERATORS] (To view GPU usage, run: sudo argolis-monitor)\033[K")
            
            # Memory & Storage
            buf.append("\033[K")
            buf.append("[MEMORY & STORAGE]\033[K")
            lbl_mem  = "  [UNIFIED RAM]".ljust(18)
            lbl_ssd  = "  [INTERNAL SSD]".ljust(18)
            lbl_fast = "  [FAST STORAGE]".ljust(18)
            lbl_ext  = "  [SEAGATE EXT]".ljust(18)

            buf.append(f"{lbl_mem}{make_bar(mem.percent, 22)}  Used: {mem.used/(1024**3):6.1f} GB / {mem.total/(1024**3):6.1f} GB  (Free: {mem.available/(1024**3):5.1f} GB)\033[K")
            
            data_mount = '/System/Volumes/Data' if os.path.exists('/System/Volumes/Data') else '/'
            disk = psutil.disk_usage(data_mount)
            ssd_total = disk.total / (1024**3)
            ssd_free = disk.free / (1024**3)
            ssd_used = (disk.total - disk.free) / (1024**3)
            ssd_pct = (ssd_used / ssd_total) * 100.0 if ssd_total > 0 else 0.0
            buf.append(f"{lbl_ssd}{make_bar(ssd_pct, 22)}  Used: {ssd_used:6.1f} GB / {ssd_total:6.1f} GB  (Free: {ssd_free:5.1f} GB)\033[K")

            if os.path.exists("/Volumes/FastStorage"):
                fast_disk = psutil.disk_usage("/Volumes/FastStorage")
                fast_pct = (fast_disk.used / fast_disk.total) * 100.0 if fast_disk.total > 0 else 0.0
                buf.append(f"{lbl_fast}{make_bar(fast_pct, 22)}  Used: {fast_disk.used/(1024**3):6.1f} GB / {fast_disk.total/(1024**3):6.1f} GB  (Free: {fast_disk.free/(1024**3):5.1f} GB)\033[K")

            if os.path.exists("/Volumes/Seagate External"):
                ext_disk = psutil.disk_usage("/Volumes/Seagate External")
                ext_pct = (ext_disk.used / ext_disk.total) * 100.0 if ext_disk.total > 0 else 0.0
                buf.append(f"{lbl_ext}{make_bar(ext_pct, 22)}  Used: {ext_disk.used/(1024**3):6.1f} GB / {ext_disk.total/(1024**3):6.1f} GB  (Free: {ext_disk.free/(1024**3):5.1f} GB)\033[K")

            # Active AI Transcoding Workers
            buf.append("\033[K")
            buf.append("[ACTIVE AI TRANSCODING & MEDIA WORKERS]\033[K")

            upscale_paused = os.path.exists("/Users/tony/Library/Application Support/ShadaHEVC/argolis-upscale.stop") or \
                             os.path.exists("/Volumes/VIDEO/upscale.stop")
            t_ane = parse_stream_telemetry("Idle / Waiting for Queue Job...")
            if upscale_paused:
                buf.append("  • Status:        \033[33m[PAUSED BY USER]\033[0m — Run 'argolis resume upscale' to resume\033[K")
                if t_ane and t_ane['episode'] != "Idle / Waiting for Queue Job...":
                    buf.append(f"  > SUSPENDED:     {t_ane['episode']}\033[K")
                    buf.append(f"  • Last Progress: {t_ane['chunk']}\033[K")
            elif t_ane and t_ane['episode'] != "Idle / Waiting for Queue Job...":
                buf.append(f"  > ACTIVE EPISODE: {t_ane['episode']}\033[K")
                buf.append(f"  • Acceleration:  16-Core Neural Engine (Primary) + Metal GPU\033[K")
                buf.append(f"  • Progress:      {t_ane['chunk']} (Throughput: {t_ane['fps']})\033[K")
                buf.append(f"  • Profile:       {t_ane['mode']}\033[K")
            else:
                buf.append("  • Status:        Idle — Watching /Volumes/VIDEO/upscale_queue.txt\033[K")

            # HEVC library worker (read-only queue/dashboard integration)
            hevc = hevc_progress()
            buf.append("\033[K")
            buf.append("[HEVC TRANSCODING]\033[K")
            hevc_paused = os.path.exists("/Users/tony/Library/Application Support/ShadaHEVC/argolis-library-jobs.stop")
            if hevc_paused:
                buf.append("  • Status:        \033[33m[PAUSED BY USER]\033[0m — Run 'argolis resume hevc' to resume\033[K")
            if "error" in hevc:
                buf.append(f"  • Status:        {hevc['error']}\033[K")
            else:
                state = hevc.get("state")
                if hevc.get("upscale_active"):
                    state_text = f"{state['state']} — {state['detail']}" if state else "upscale active"
                elif state and state['detail'] == 'Argolis upscale is active':
                    state_text = "ready — upscale is not active; worker retry pending"
                else:
                    state_text = f"{state['state']} — {state['detail']}" if state else "state unavailable"
                buf.append(f"  • Worker:        {state_text}\033[K")
                buf.append(f"  • Queue:         {make_bar(hevc['pct'], 22)}  ({hevc['done']}/{hevc['total']} done)\033[K")
                saved_pct = hevc['saved'] / hevc['original'] * 100 if hevc['original'] else 0
                buf.append(f"  • Saved:         {fmt_bytes(hevc['saved'])}  ({saved_pct:.1f}% across completed files)\033[K")
                if hevc.get("active_detail"):
                    buf.append(f"  > Active:        {hevc['active_detail']}\033[K")
                else:
                    buf.append("  • Active:        No HEVC encode\033[K")

            # Low-level process breakdown
            procs = get_ai_processes()
            if procs:
                buf.append("\033[K")
                buf.append("Underlying OS Processes:\033[K")
                for p in procs:
                    buf.append(f"  PID: {p['pid']:<7} | CPU: {p['cpu']:5.1f}% | RAM: {p['mem_mb']:6.1f} MB | Process: {p['name']}\033[K")

            buf.append("\033[K")
            buf.append("Press Ctrl+C to exit monitor.\033[K")
            buf.append("\033[J")

            sys.stdout.write("\n".join(buf))
            sys.stdout.flush()

            time.sleep(1.0)

    except KeyboardInterrupt:
        pass
    finally:
        if power_proc:
            power_proc.kill()
        sys.stdout.write("\033[?25h\n\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
