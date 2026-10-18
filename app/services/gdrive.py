import os
import json
import time
import socket
from pathlib import Path

# Enforce a 60-second network socket timeout so hung TCP chunks automatically fail over & retry
socket.setdefaulttimeout(60)

from loguru import logger
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = ROOT_DIR / "storage"
CONFIG_FILE = STORAGE_DIR / "gdrive_config.json"
CLIENT_SECRETS_FILE = ROOT_DIR / "client_secrets.json"


def get_token_file(account_name: str) -> Path:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return STORAGE_DIR / f"token_gdrive_{account_name}.json"


def load_gdrive_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading gdrive_config.json: {e}")
    return {
        "english": {"folder_id": "", "folder_name": ""},
        "hindi": {"folder_id": "", "folder_name": ""},
    }


def save_gdrive_config(config: dict):
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_credentials(account_name: str, interactive: bool = True) -> Credentials:
    """Get valid Google Drive credentials for a specific account ('english' or 'hindi')."""
    token_path = get_token_file(account_name)
    creds = None

    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as e:
            logger.warning(f"Error loading token for {account_name}: {e}")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(token_path, "w", encoding="utf-8") as token_file:
                    token_file.write(creds.to_json())
                logger.success(f"Token refreshed for {account_name} Google Drive account.")
                return creds
            except Exception as e:
                logger.warning(f"Failed to refresh token for {account_name}: {e}")

        if not interactive:
            logger.error(f"No valid token found for {account_name} Google Drive account.")
            return None

        if not CLIENT_SECRETS_FILE.exists():
            raise FileNotFoundError(f"Missing client_secrets.json at {CLIENT_SECRETS_FILE}")

        logger.info(f"Opening browser to authenticate Google Drive account: {account_name.upper()}...")
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), SCOPES)
        creds = flow.run_local_server(port=0, prompt="select_account")

        with open(token_path, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())
        logger.success(f"Authentication successful for {account_name} Google Drive account!")

    return creds


def list_drive_folders(account_name: str) -> list:
    """List folders in the user's Google Drive account."""
    creds = get_credentials(account_name, interactive=False)
    if not creds:
        return []

    service = build("drive", "v3", credentials=creds)
    results = service.files().list(
        q="mimeType='application/vnd.google-apps.folder' and trashed=false",
        spaces="drive",
        fields="files(id, name)",
        pageSize=50,
    ).execute()

    return results.get("files", [])


def create_or_get_folder(service, folder_name: str, parent_id: str = None) -> str:
    """Check if folder exists; if not, create it."""
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    return folder.get("id")


import re

def sanitize_filename(name: str) -> str:
    """Remove characters not allowed in file names and clean whitespace."""
    if not name:
        return "video"
    # Remove invalid filename characters: \ / : * ? " < > |
    cleaned = re.sub(r'[\\/*?:"<>|]', '', name).strip()
    # Normalize multiple spaces
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned[:100]


def upload_video(video_path: str, account_name: str, folder_id: str = None, file_title: str = None) -> dict:
    """Upload a video file to the designated Google Drive account."""
    if not os.path.exists(video_path):
        logger.error(f"Video file not found for upload: {video_path}")
        return None

    creds = get_credentials(account_name, interactive=False)
    if not creds:
        logger.error(f"Cannot upload: Account {account_name} is not authenticated with Google Drive.")
        return None

    service = build("drive", "v3", credentials=creds)
    config = load_gdrive_config()

    target_folder_id = folder_id or config.get(account_name, {}).get("folder_id")
    if not target_folder_id:
        target_name = config.get(account_name, {}).get("folder_name") or (
            "AI Tech Videos (Hindi)" if account_name == "hindi" else "AI Tech Videos (English)"
        )
        target_folder_id = create_or_get_folder(service, target_name)
        config[account_name]["folder_id"] = target_folder_id
        config[account_name]["folder_name"] = target_name
        save_gdrive_config(config)

    if file_title:
        clean_title = sanitize_filename(file_title)
        if not clean_title.lower().endswith(".mp4"):
            file_name = f"{clean_title}.mp4"
        else:
            file_name = clean_title
    else:
        file_name = os.path.basename(video_path)

    file_metadata = {
        "name": file_name,
        "parents": [target_folder_id],
    }

    logger.info(f"Uploading '{file_name}' to Google Drive ({account_name.upper()}) [Folder ID: {target_folder_id}]...")
    media = MediaFileUpload(video_path, mimetype="video/mp4", chunksize=2 * 1024 * 1024, resumable=True)
    request = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink",
    )
    response = None
    retries = 0
    max_retries = 15
    while response is None:
        try:
            status, response = request.next_chunk()
            retries = 0
            if status:
                progress_pct = int(status.progress() * 100)
                logger.info(f"Uploading '{file_name}': {progress_pct}%")
                try:
                    from app.services import status_service
                    status_service.save_status_files()
                except Exception:
                    pass

        except Exception as chunk_err:
            retries += 1
            if retries > max_retries:
                logger.error(f"Upload failed after {max_retries} retries: {chunk_err}")
                raise chunk_err
            logger.warning(f"Network glitch during upload ({chunk_err}), retrying chunk ({retries}/{max_retries}) in 5s...")
            time.sleep(5)

    logger.success(f"Upload complete! File ID: {response.get('id')}, Link: {response.get('webViewLink')}")
    return response
