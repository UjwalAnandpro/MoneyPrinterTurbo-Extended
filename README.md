# MoneyPrinterTurbo - Extended Edition 🚀

An enterprise-grade, fully automated AI short-video generation and publishing pipeline. This extended edition builds upon [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) by introducing automated daily production workflows, dual-language synthesis (Hindi & English), multi-account Google Drive cloud sync, real-time status monitoring, and copyright-free audio library management.

---

## 🌟 Key New Features in This Extended Edition

### 1. 🤖 Fully Automated Daily Tech Video Pipeline (`daily_tech_video.py`)
- **End-to-End Hands-Free Generation**: One command generates complete, publication-ready vertical shorts (9:16) with scriptwriting, voiceover, stock footage matching, animated subtitles, and background music.
- **Dual-Language Support**:
  - **Hindi Mode**: High-engagement Hinglish/Hindi tech script, natural Edge TTS / bilingual voice synthesis, and native Hindi subtitle rendering with [Nirmala.ttc](resource/fonts/Nirmala.ttc).
  - **English Mode**: Global audience tech scripts with studio-quality English voice synthesis and dynamic font styling.
- **Cinematic Pan & Zoom Effects**: Applies automatic Ken Burns (smooth zoom-in, zoom-out, pan) animations on all clips to boost viewer retention.
- **Smart Fallback Material Matching**: Semantic keyword search across Pexels and Pixabay with automatic retry logic and fallback video matching.

---

### 2. ☁️ Multi-Account Google Drive Cloud Integration (`app/services/gdrive.py`)
- **Dual-Account / Dual-Channel Sync**: Automatically uploads generated videos to dedicated Google Drive folders based on language:
  - English videos ➔ English Channel Drive Folder
  - Hindi videos ➔ Hindi Channel Drive Folder
- **Interactive OAuth Setup (`connect_gdrive.py` / `connect_gdrive.bat`)**: One-click authentication in your browser to link your Google accounts.
- **Robust Resumable Uploads**: 2MB chunked uploads with automatic retry upon network hiccups and socket timeouts.
- **Drive Status Verifier (`check_drive_status.py`)**: Quickly check authentication validity and folder mapping without starting a video build.

---

### 3. 📊 Real-Time Status Board & Monitoring (`status_board.html` & `status_monitor.py`)
- **Live Visual Dashboard**: Modern, glassmorphism dark-mode web dashboard to monitor video rendering progress in real time.
- **Granular Pipeline Tracking**:
  - 📝 **Topic & Script Generation**
  - 🎙️ **TTS Voice Synthesis**
  - 🎬 **Video Material & Clip Gathering**
  - 💬 **Dynamic Subtitle Synchronization**
  - 🎞️ **Final Video Compositing & FX**
  - ☁️ **Cloud Upload Status**
- **One-Click Launch**: Double-click `view_status_board.bat` to open the live board.

---

### 4. 🎵 Curated Copyright-Free Audio Library
- **Integrated YouTube Audio Library (`download_youtube_audio_library.py`)**: Curated copyright-free background scores tailored for high-paced tech content.
- **Automatic Audio Mixing**: Background music automatically loops, ducks, and mixes at calibrated volume levels beneath spoken dialogue.

---

### 5. ⏱️ 24/7 Silent Background Scheduling
- **`run_daily.bat`**: Full automation execution script.
- **`run_daily_silent.vbs`**: Completely hidden VBS launcher designed for Windows Task Scheduler (runs without showing annoying command prompt windows).

---

## 🏗️ Architecture & Pipeline Flow

```
[ Scheduled Trigger (run_daily_silent.vbs) ]
                     │
                     ▼
         [ daily_tech_video.py ]
                     │
     ┌───────────────┴───────────────┐
     ▼                               ▼
[ English Pipeline ]          [ Hindi Pipeline ]
  • Viral Prompt (LLM)          • Tech Viral Prompt (LLM)
  • English Voice (TTS)         • Hindi Voice (Edge/Custom TTS)
  • Pexels/Pixabay Media        • Pexels/Pixabay Media
  • Pan/Zoom Compositing        • Nirmala.ttc Hindi Subtitles
  • BG Music Mix                • BG Music Mix
     │                               │
     └───────────────┬───────────────┘
                     ▼
         [ Multi-Account Google Drive ]
          ├─► English Channel Drive
          └─► Hindi Channel Drive
                     │
                     ▼
        [ Live Status Board Dashboard ]
```

---

## 🚀 Quick Start Guide

### 1. Installation

```bash
# Clone this repository
git clone https://github.com/UjwalAnandpro/MoneyPrinterTurbo-Extended.git
cd MoneyPrinterTurbo-Extended

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration Setup

Copy the example configuration files and add your API keys:

```bash
# Copy main configuration
copy config.example.toml config.toml

# Copy Google OAuth credentials template
copy client_secrets.example.json client_secrets.json
```

Edit `config.toml` to specify your LLM (OpenAI, Gemini, Ollama, etc.) and stock footage API keys (Pexels, Pixabay).

---

### 3. Google Drive Multi-Account Setup

Run the interactive setup helper:

```cmd
connect_gdrive.bat
```
Follow the browser prompts to link your Google accounts for Hindi and English target folders.

---

### 4. Running the Pipelines

#### Option A: Run Full Automated Daily Video Pipeline
```cmd
run_daily.bat
```
Or run directly via Python:
```bash
python daily_tech_video.py
```

#### Option B: Launch Live Status Board
```cmd
view_status_board.bat
```

#### Option C: Interactive Streamlit Web Interface
```cmd
webui.bat
```
Opens the visual studio interface at `http://localhost:8501`.

---

## 🔒 Security Best Practices

This repository is configured with strict `.gitignore` rules to prevent credential leaks:
- `client_secrets.json` and OAuth token files (`token*.json`) are never committed.
- `config.toml` (containing private API keys) is kept local only.
- Rendered video caches and task artifacts in `storage/` are excluded.

---

## 📜 Credits & License

- Based on the open-source [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) project.
- Enhanced with automated daily tech production, bilingual TTS/subtitles, live dashboarding, and multi-account Google Drive sync by **Ujwal Anand**.
- Released under the [MIT License](LICENSE).
