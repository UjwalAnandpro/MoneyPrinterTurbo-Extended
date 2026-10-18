import os
import json
import re
import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = ROOT_DIR / "storage"
STATE_FILE = STORAGE_DIR / "daily_state.json"
GDRIVE_CONFIG_FILE = STORAGE_DIR / "gdrive_config.json"
STATUS_JSON_FILE = STORAGE_DIR / "daily_status.json"
STATUS_JS_FILE = STORAGE_DIR / "daily_status.js"

# Path to potential log files
RUNNER_LOG_FILE = STORAGE_DIR / "daily_runner.log"


def get_file_size_str(file_path: str) -> str:
    if not file_path or not os.path.exists(file_path):
        return "N/A"
    try:
        size_bytes = os.path.getsize(file_path)
        if size_bytes >= 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
        if size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        if size_bytes >= 1024:
            return f"{size_bytes / 1024:.1f} KB"
        return f"{size_bytes} B"
    except Exception:
        return "N/A"


def find_latest_log_content() -> list[str]:
    """Find the most relevant log file (daily_runner.log or task log) and return last lines."""
    log_candidates = []
    if RUNNER_LOG_FILE.exists():
        log_candidates.append(RUNNER_LOG_FILE)

    brain_dir = Path(r"C:\Users\ujwal\.gemini\antigravity-ide\brain")
    if brain_dir.exists():
        try:
            for task_log in brain_dir.glob("*/.system_generated/tasks/task-*.log"):
                try:
                    with open(task_log, "r", encoding="utf-8", errors="replace") as f:
                        head = "".join([f.readline() for _ in range(8)])
                        if "daily_tech_video" in head or "gdrive" in head or "upload_video" in head:
                            log_candidates.append(task_log)
                except Exception:
                    pass
        except Exception:
            pass

    valid_logs = [p for p in log_candidates if p.exists()]
    if not valid_logs:
        return []

    valid_logs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    newest_log = valid_logs[0]

    try:
        with open(newest_log, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return [line.strip() for line in lines[-40:] if line.strip()]
    except Exception:
        return []


def parse_upload_progress(log_lines: list[str], filename_substr: str = "") -> int:
    """Parse upload percentage from log lines for a specific file."""
    pct = 0
    pattern = re.compile(r"Uploading\s+['\"](.*?)['\"]\s*:\s*(\d+)%")
    for line in log_lines:
        m = pattern.search(line)
        if m:
            logged_name = m.group(1)
            try:
                val = int(m.group(2))
                if not filename_substr or filename_substr.lower() in logged_name.lower():
                    pct = val
            except ValueError:
                pass
    return pct



def compute_daily_status() -> dict:
    today_str = datetime.date.today().isoformat()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    state = {}
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}

    gdrive_cfg = {}
    if GDRIVE_CONFIG_FILE.exists():
        try:
            with open(GDRIVE_CONFIG_FILE, "r", encoding="utf-8") as f:
                gdrive_cfg = json.load(f)
        except Exception:
            gdrive_cfg = {}

    log_lines = find_latest_log_content()

    topics = state.get("topics", {})
    en_topic = topics.get("en", "US Announces Super Intelligence Force for AI Oversight and Regulation")
    hi_topic = topics.get("hi", "यूएस ने एआई निगरानी और नियमन के लिए सुपर इंटेलिजेंस फोर्स की घोषणा की")

    scripts = state.get("scripts", {})
    en_script_data = scripts.get("en", {})
    hi_script_data = scripts.get("hi", {})

    videos = state.get("videos", {})
    en_video_path = videos.get("en", "")
    hi_video_path = videos.get("hi", "")

    uploads = state.get("uploads", {})
    en_upload = uploads.get("en", {})
    hi_upload = uploads.get("hi", {})

    # Fallback to task directories if scripts missing
    if not en_script_data and en_video_path:
        task_dir = Path(en_video_path).parent
        script_file = task_dir / "script.json"
        if script_file.exists():
            try:
                with open(script_file, "r", encoding="utf-8") as f:
                    s_data = json.load(f)
                    en_script_data = {
                        "script": s_data.get("script", "") or s_data.get("params", {}).get("video_script", ""),
                        "terms": s_data.get("search_terms", []) or s_data.get("params", {}).get("video_terms", [])
                    }
            except Exception:
                pass


    # Check local video files
    en_video_exists = bool(en_video_path and os.path.exists(en_video_path))
    hi_video_exists = bool(hi_video_path and os.path.exists(hi_video_path))

    # Determine English status
    en_size = get_file_size_str(en_video_path)
    en_upload_pct = 0
    if en_upload and en_upload.get("id"):
        en_upload_pct = 100
        en_phase = "COMPLETED"
    elif en_video_exists:
        en_upload_pct = parse_upload_progress(log_lines, filename_substr=en_topic[:10])
        if en_upload_pct > 0:
            en_phase = "UPLOADING"
        else:
            en_phase = "READY_TO_UPLOAD"
    elif en_script_data:
        en_phase = "RENDERING"
    else:
        en_phase = "GENERATING_SCRIPT"

    # Determine Hindi status
    hi_size = get_file_size_str(hi_video_path)
    hi_upload_pct = 0
    if hi_upload and hi_upload.get("id"):
        hi_upload_pct = 100
        hi_phase = "COMPLETED"
    elif hi_video_exists:
        if en_phase == "COMPLETED":
            hi_upload_pct = parse_upload_progress(log_lines, filename_substr=hi_topic[:6])
            if hi_upload_pct > 0:
                hi_phase = "UPLOADING"
            else:
                hi_phase = "UPLOADING"
        else:
            hi_phase = "QUEUED_FOR_UPLOAD"

    elif hi_script_data:
        hi_phase = "RENDERING"
    else:
        hi_phase = "GENERATING_SCRIPT"

    # Overall pipeline stage
    is_all_completed = bool(en_upload and en_upload.get("id") and hi_upload and hi_upload.get("id"))
    if is_all_completed:
        overall_status = "ALL COMPLETED"
        overall_pct = 100
        status_message = "Both English and Hindi videos generated & uploaded successfully to Google Drive!"
    elif en_upload and en_upload.get("id"):
        overall_status = "UPLOADING HINDI VIDEO"
        overall_pct = 75 + int(hi_upload_pct * 0.25)
        status_message = f"English video uploaded! Hindi video upload in progress ({hi_upload_pct}%)..."
    elif en_video_exists and hi_video_exists:
        overall_status = "UPLOADING TO GOOGLE DRIVE"
        overall_pct = 50 + int(en_upload_pct * 0.25)
        status_message = f"Both videos rendered locally (100%). Uploading English video ({en_upload_pct}%)..."
    elif en_video_exists:
        overall_status = "RENDERING HINDI VIDEO"
        overall_pct = 35
        status_message = "English video rendered! Now rendering Hindi video..."
    else:
        overall_status = "GENERATING VIDEOS"
        overall_pct = 15
        status_message = "Generating scripts and rendering videos..."

    data = {
        "date": today_str,
        "updated_at": now_str,
        "overall_status": overall_status,
        "overall_pct": overall_pct,
        "status_message": status_message,
        "is_completed": is_all_completed,
        "videos": {
            "english": {
                "language": "English (en)",
                "topic": en_topic,
                "voice": "Edge-TTS (en-US-ChristopherNeural)",
                "aspect": "16:9 Landscape (1080p)",
                "duration": "~2 Minutes",
                "phase": en_phase,
                "render_status": "DONE (100%)" if en_video_exists else "In Progress",
                "local_path": en_video_path,
                "file_size": en_size,
                "upload_pct": en_upload_pct,
                "gdrive_folder": gdrive_cfg.get("english", {}).get("folder_name", "AI Tech Videos (English Videos)"),
                "gdrive_folder_id": gdrive_cfg.get("english", {}).get("folder_id", ""),
                "gdrive_link": en_upload.get("webViewLink", ""),
                "gdrive_file_id": en_upload.get("id", ""),
                "script_preview": (en_script_data.get("script") or "")[:280] + "..." if en_script_data.get("script") else "Script ready",
                "search_terms": en_script_data.get("terms", []),
            },
            "hindi": {
                "language": "Hindi (hi)",
                "topic": hi_topic,
                "voice": "Edge-TTS (hi-IN-MadhurNeural)",
                "aspect": "16:9 Landscape (1080p)",
                "duration": "~2 Minutes",
                "phase": hi_phase,
                "render_status": "DONE (100%)" if hi_video_exists else "In Progress",
                "local_path": hi_video_path,
                "file_size": hi_size,
                "upload_pct": hi_upload_pct,
                "gdrive_folder": gdrive_cfg.get("hindi", {}).get("folder_name", "AI Tech Videos (Hindi Videos)"),
                "gdrive_folder_id": gdrive_cfg.get("hindi", {}).get("folder_id", ""),
                "gdrive_link": hi_upload.get("webViewLink", ""),
                "gdrive_file_id": hi_upload.get("id", ""),
                "script_preview": (hi_script_data.get("script") or "")[:280] + "..." if hi_script_data.get("script") else "Script ready",
                "search_terms": hi_script_data.get("terms", []),
            }
        },
        "recent_logs": log_lines[-20:]
    }

    return data


def save_status_files():
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    status_data = compute_daily_status()

    # Save JSON
    with open(STATUS_JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(status_data, f, indent=2, ensure_ascii=False)

    # Save JS for direct browser access without CORS
    with open(STATUS_JS_FILE, "w", encoding="utf-8") as f:
        f.write("window.DAILY_STATUS = " + json.dumps(status_data, indent=2, ensure_ascii=False) + ";\n")

    return status_data


if __name__ == "__main__":
    data = save_status_files()
    print("Status updated successfully:")
    print(f"Overall: {data['overall_status']} ({data['overall_pct']}%)")
    print(f"English: {data['videos']['english']['phase']} ({data['videos']['english']['upload_pct']}%)")
    print(f"Hindi: {data['videos']['hindi']['phase']} ({data['videos']['hindi']['upload_pct']}%)")
