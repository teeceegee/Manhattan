# Argolis AI Video Remastering Pipeline (Manhattan)

An automated, hardware-accelerated video upscaling and restoration pipeline designed for Apple Silicon (M4 Mac Mini). Argolis remasters standard-definition television episodes (PAL/NTSC 4:3) to pristine 1440×1080 HEVC masters using Apple's 16-Core Neural Engine (ANE) and Metal GPU.

---

## System Architecture

```
                    /Volumes/VIDEO/upscale_queue.txt
                                  │
                                  ▼
                   tools/queue_daemon.py (Singleton)
                                  │
       ┌──────────────────────────┴──────────────────────────┐
       │                                                     │
       ▼                                                     ▼
1. Local Cache (~/Working)                        7. Live Telemetry
       │                                             upscale_status.json
       ▼                                                     ▲
2. Content Profiling                                         │
   (detect_monochrome)                            tools/argolis_monitor.py
       │                                          (`argolis-monitor` CLI)
       ▼
3. Zero-Copy Inference Engine
   (tools/native/argolis-upscale)
   • AVAssetReader (32BGRA)
   • Real-ESRGAN CoreML (ANE + Metal GPU)
   • AVAssetWriter (1080p HEVC Main)
       │
       ▼
4. FFmpeg Multiplexing
   • Original 48 kHz AAC audio
   • Preservation of chapters & subtitles
   • FastStart MP4 container
       │
       ▼
5. Atomic NAS Deployment
   • Stage to /Volumes/VIDEO/...mp4.tmp
   • Atomic rename to final master
       │
       ▼
6. Storage & Snapshot Hygiene
   • Remove local working cache & intermediate files
   • `tmutil thinlocalsnapshots /` to prevent APFS bloat
```

---

## Output Master Specification

| Parameter | Value |
| :--- | :--- |
| **Geometry** | 1440 × 1080 (Preserved 4:3 SD Aspect Ratio) |
| **Video Codec** | HEVC / H.265 (`vt_profile_level_hevc_main_autolevel`) |
| **Bitrate Target** | 5.0 Mbps average with variable frame reordering |
| **Audio** | AAC Stereo @ 192 kbps, 48.0 kHz (via Apple AudioToolbox) |
| **Container** | MP4 with faststart atom enabled for instant streaming |
| **Chapters / Subtitles** | Preserved from source media |
| **Model** | Real-ESRGAN 16-convolution Zero-Copy (`ImageType/BGR`) |

---

## Key Components

### 1. Production Engine (`tools/native/argolis-upscale`)
* **Source:** `tools/native/argolis_upscale.swift`
* Compiled with Apple `swiftc -O` for bare-metal execution.
* Interacts directly with AVFoundation and CoreML CVPixelBuffers without intermediate pipe or NumPy overhead, sustaining **~13.5 FPS** on 1080p output.
* Features automatic monochrome luma desaturation for black-and-white archives.

### 2. Queue Daemon (`tools/queue_daemon.py`)
* Background orchestrator running with a singleton `fcntl` file lock (`/tmp/argolis_queue_daemon.lock`).
* Reads `/Volumes/VIDEO/upscale_queue.txt` and automatically processes pending episodes.
* **Corrupt Bitstream Auto-Recovery:** Detects AVFoundation decode rejections (code 118) and executes an ultra-fast FFmpeg stream sanitizer before retrying.
* **Atomic Master Deployment:** Copies output as `.tmp` and renames to guarantee partial transfers never corrupt the library.
* **Storage Hygiene:** Purges working cache and thins local APFS Time Machine snapshots after every completed job.
* **Automatic Log Rotation:** Automatically rotates `upscale_daemon.log` when it exceeds 10 MB.

### 3. Terminal Monitor (`tools/argolis_monitor.py`)
* Plain monochrome live dashboard: CPU per-core utilization, Unified Memory, Internal SSD (`/System/Volumes/Data`), FastStorage, Seagate External HDD, and active neural engine transcoding status.
* Installed globally as `argolis-monitor` (symlinked in `/Users/tony/.local/bin/argolis-monitor`).

### 4. Active Models (`tools/realesrgan/models/`)
* `realesr_1080p_zerocopy.mlmodelc` (Compiled CoreML model used by native Swift engine)
* `realesr_1080p_zerocopy.mlpackage` (Source CoreML package for recompilation)
* `realesr_fast_1080p.mlmodelc` / `.mlpackage` (Fast fallback model)

---

## Usage Guide

### Enqueueing Shows or Episodes
Add relative paths within `/Volumes/VIDEO` (or `/Volumes/VIDEO/TV/COMEDY`) to `/Volumes/VIDEO/upscale_queue.txt`:

```text
TV/COMEDY/The Thin Blue Line
TV/COMEDY/Fawlty Towers
TV/COMEDY/Steptoe and Son/Series 2
```

The daemon automatically discovers all `.mp4` video files in those directories and processes any that lack a `- 1080p (4-3 Master).mp4` master.

### Running the Queue Daemon
```bash
cd "/Volumes/Seagate External/Development/Manhattan"
venv/bin/python3 tools/queue_daemon.py
```

### Viewing Real-Time Telemetry
Run from any terminal:
```bash
argolis-monitor
```
*(Run `sudo argolis-monitor` to also view Apple M4 Metal GPU residency metrics).*

### Recompiling the Swift Engine
```bash
cd "/Volumes/Seagate External/Development/Manhattan"
swiftc -O tools/native/argolis_upscale.swift -o tools/native/argolis-upscale.new
mv tools/native/argolis-upscale.new tools/native/argolis-upscale
```

---

## Directory Layout

```
Manhattan/
├── README.md                     # Project documentation
├── upscale_daemon.log            # Active daemon runtime log (auto-rotated at 10 MB)
├── tools/
│   ├── queue_daemon.py           # Production queue daemon
│   ├── argolis_monitor.py        # System & AI workload monitor
│   ├── remaster_episode_1080p.py # Core Python fallback remaster engine
│   ├── sync_confluence_manifest.py # Manifest sync to Confluence wiki
│   ├── native/
│   │   ├── argolis-upscale       # Native compiled Mach-O binary
│   │   └── argolis_upscale.swift # Swift zero-copy engine source
│   └── realesrgan/
│       └── models/               # Production CoreML models
├── archive/                      # Historical R&D scripts, tests, and models
├── output/                       # Active local scratch output
├── Working/ -> ~/Working         # Fast internal SSD working cache
└── venv/                         # Python virtual environment
```
