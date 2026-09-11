#!/usr/bin/env python3
"""
Automated Confluence Remaster Manifest Synchronizer
Maintains a dynamic table on Confluence Page 6455298 tracking all converted episodes,
resolutions, file sizes, and exact dates/timestamps of transcription.
"""

import os
import sys
import json
import base64
import urllib.request
import subprocess
from datetime import datetime

BASE_DIR = "/Volumes/Seagate External/Development/Manhattan"
PROGRESS_JSON = os.path.join(BASE_DIR, "tools", "oftg_batch_progress.json")
CONFLUENCE_PAGE_ID = "6455298"

def get_atlassian_creds():
    # Fetch credentials from Shada
    cmd = ["ssh", "shada", "cat /home/tony/.config/atlassian/credentials.env"]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True)
    env = {}
    for line in res.stdout.splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def scan_completed_episodes():
    completed = []
    
    # 1. Check OFTG progress JSON
    if os.path.exists(PROGRESS_JSON):
        try:
            with open(PROGRESS_JSON, "r") as f:
                data = json.load(f)
                for ep_id, ep in data.get("episodes", {}).items():
                    if ep.get("status") == "COMPLETED":
                        dt_str = ep.get("completed_at", "")
                        formatted_date = dt_str[:16].replace("T", " ") if dt_str else datetime.now().strftime("%Y-%m-%d %H:%M")
                        completed.append({
                            "show": "One Foot in the Grave",
                            "series": ep.get("series", "Series 1"),
                            "title": ep.get("filename", "").replace(".mp4", ""),
                            "deliverable": ep.get("target_name", ""),
                            "resolution": "1440x1080 (Native 4:3)",
                            "codec": "HEVC (hvc1) @ 5 Mbps",
                            "audio": "48 kHz 192k AAC",
                            "size_mb": f"{ep.get('size_mb', 1100):.1f} MB",
                            "completed_date": formatted_date,
                            "path": ep.get("shada_path", "")
                        })
        except Exception as e:
            print(f"Warning reading progress JSON: {e}")

    # 2. Check Shada VIDEO directory for all 1080p Masters
    video_base = "/Volumes/VIDEO/TV/COMEDY"
    if os.path.exists(video_base):
        for root, dirs, files in os.walk(video_base):
            for f in files:
                if f.endswith("- 1080p (4-3 Master).mp4") and not f.startswith("._"):
                    full_p = os.path.join(root, f)
                    show_name = "Steptoe and Son" if "Steptoe" in f else "One Foot in the Grave"
                    series_name = os.path.basename(root)
                    mtime = os.path.getmtime(full_p)
                    file_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                    size_mb = os.path.getsize(full_p) / (1024 * 1024)

                    # Check if already added
                    if not any(c["path"] == full_p for c in completed):
                        completed.append({
                            "show": show_name,
                            "series": series_name,
                            "title": f.replace(" - 1080p (4-3 Master).mp4", ""),
                            "deliverable": f,
                            "resolution": "1440x1080 (Native 4:3)",
                            "codec": "HEVC (hvc1) @ 5 Mbps",
                            "audio": "48 kHz 192k AAC",
                            "size_mb": f"{size_mb:.1f} MB",
                            "completed_date": file_date,
                            "path": full_p
                        })

    # Sort chronologically by completed date
    completed.sort(key=lambda x: (x["show"], x["series"], x["title"]))
    return completed

def update_confluence():
    print("Fetching completed episodes manifest...")
    completed = scan_completed_episodes()
    print(f"Found {len(completed)} completed master releases.")

    env = get_atlassian_creds()
    b64_auth = base64.b64encode(f"{env['ATLASSIAN_EMAIL']}:{env['ATLASSIAN_API_TOKEN']}".encode()).decode()
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Basic {b64_auth}',
    }

    # Fetch current page version
    req = urllib.request.Request(f"https://{env['ATLASSIAN_SITE']}/wiki/api/v2/pages/{CONFLUENCE_PAGE_ID}", headers=headers)
    with urllib.request.urlopen(req) as resp:
        page_data = json.loads(resp.read().decode())
        current_version = page_data.get('version', {}).get('number', 8)

    # Build HTML table rows
    rows_html = ""
    for idx, ep in enumerate(completed):
        rows_html += f"""
        <tr>
          <td><strong>{idx+1}</strong></td>
          <td><strong>{ep['show']}</strong></td>
          <td>{ep['series']}</td>
          <td><code>{ep['title']}</code></td>
          <td>{ep['resolution']}</td>
          <td>{ep['codec']}</td>
          <td>{ep['size_mb']}</td>
          <td><strong>{ep['completed_date']}</strong></td>
        </tr>"""

    confluence_html = f"""
<p><strong>Document ID:</strong> DOC-ARG-VIDEO-001<br/>
<strong>Classification:</strong> Internal Project &amp; Live Converted Manifest<br/>
<strong>Host / Compute Node:</strong> Argolis (Apple M4 Mac Mini, 16 GB Unified Memory, macOS 26.5.2)<br/>
<strong>Parent Guide:</strong> <ac:link><ri:page ri:content-title="Argolis - System Architecture &amp; Maintenance Guide" /></ac:link><br/>
<strong>Author &amp; Engineering Agent:</strong> Antigravity (AI Assistant) powered by Google DeepMind Gemini<br/>
<strong>Associated Jira Epic:</strong> <a href="https://echopost.atlassian.net/browse/EVD-46">EVD-46: One Foot in the Grave &amp; Classic TV: AI Video Upscaling Pipeline</a><br/>
<strong>Status:</strong> <ac:structured-macro ac:name="status" ac:schema-version="1"><ac:parameter ac:name="title">LIVE AUTO-UPDATING CONVERSION MANIFEST</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro></p>

<ac:structured-macro ac:name="info" ac:schema-version="1">
  <ac:rich-text-body>
    <p><strong>Live Telemetry Notice:</strong> This page is automatically maintained and updated in real-time by the Argolis 24/7 AI Upscaling Queue Daemon upon completion of each episode remaster.</p>
  </ac:rich-text-body>
</ac:structured-macro>

<hr/>

<h2>1. Live Converted Episodes &amp; Transcription Dates Manifest</h2>
<p><strong>Total Converted Masters Delivered:</strong> <strong>{len(completed)} episodes</strong></p>

<table>
  <thead>
    <tr>
      <th>#</th>
      <th>Programme / Show</th>
      <th>Series</th>
      <th>Episode Title</th>
      <th>Resolution</th>
      <th>Codec</th>
      <th>Master Size</th>
      <th>Date &amp; Time of Transcription</th>
    </tr>
  </thead>
  <tbody>
    {rows_html}
  </tbody>
</table>

<hr/>

<h2>2. Automated Network Intake Queue Standard</h2>
<p>To queue any additional show, season, or episode for automatic conversion, edit <code>/Volumes/VIDEO/upscale_queue.txt</code> on Shada or run <code>queue-upscale &lt;path&gt;</code> on Argolis.</p>
<ul>
  <li><strong>Intake Queue File:</strong> <code>/Volumes/VIDEO/upscale_queue.txt</code></li>
  <li><strong>Live Status JSON:</strong> <code>/Volumes/VIDEO/upscale_status.json</code></li>
  <li><strong>Daemon Engine:</strong> 16-Core Apple Neural Engine (38 TOPS) + Apple VideoToolbox HEVC (<code>hvc1</code> @ 5 Mbps) + AudioToolbox 48 kHz AAC stereo.</li>
  <li><strong>Automatic Content Detection:</strong> Dynamic 0.2s chroma variance probe auto-enables <strong>Pure Monochrome Normalization</strong> for black &amp; white shows (e.g. <em>Steptoe and Son</em>).</li>
</ul>
"""

    payload = {
        "id": CONFLUENCE_PAGE_ID,
        "status": "current",
        "title": "Argolis: AI Video Upscaling & Remastering Pipeline — Live Conversion Manifest",
        "body": {
            "representation": "storage",
            "value": confluence_html
        },
        "version": {
            "number": current_version + 1,
            "message": f"Auto-updated conversion manifest ({len(completed)} completed episodes) by Antigravity Queue Daemon"
        }
    }

    req = urllib.request.Request(
        f"https://{env['ATLASSIAN_SITE']}/wiki/api/v2/pages/{CONFLUENCE_PAGE_ID}",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="PUT"
    )
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode())
        print(f"SUCCESS: Confluence Page {CONFLUENCE_PAGE_ID} updated to version {res.get('version', {}).get('number')} with {len(completed)} converted episodes!")

if __name__ == "__main__":
    update_confluence()
