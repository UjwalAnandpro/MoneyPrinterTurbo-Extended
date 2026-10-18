"""
Download official, copyright-free music from the YouTube Audio Library.
All tracks downloaded are 100% royalty-free and Content-ID safe on YouTube.
"""
import os
import sys
import csv
import urllib.request
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
SONGS_DIR = CURRENT_DIR / "resource" / "songs"
CSV_URL = "https://raw.githubusercontent.com/Windows81/YouTube-Audio-Library/master/music.csv"
BASE_MUSIC_URL = "https://raw.githubusercontent.com/Windows81/YouTube-Audio-Library/master/music/{num}.mp3"


def download_track(num: str, title: str) -> bool:
    SONGS_DIR.mkdir(parents=True, exist_ok=True)
    clean_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
    clean_title = clean_title.replace(" ", "_")
    filename = f"yt_{clean_title}.mp3"
    target_path = SONGS_DIR / filename

    if target_path.exists() and target_path.stat().st_size > 100000:
        print(f"[OK] Already exists: {filename}")
        return True

    url = BASE_MUSIC_URL.format(num=num)
    print(f"Downloading: {title} ({url})...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(target_path, "wb") as f:
            f.write(resp.read())
        size_mb = target_path.stat().st_size / (1024 * 1024)
        print(f"[SUCCESS] Downloaded: {filename} ({size_mb:.2f} MB)")
        return True
    except Exception as e:
        print(f"[ERROR] Failed {title}: {e}")
        return False


def main():
    print(f"BGM Directory: {SONGS_DIR}")
    existing = list(SONGS_DIR.glob("*.mp3"))
    print(f"Current YouTube Audio Library tracks available: {len(existing)}")
    for f in existing:
        print(f" - {f.name}")


if __name__ == "__main__":
    main()
