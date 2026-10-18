import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from loguru import logger
from app.services import gdrive

def setup_account(account_name: str, label: str):
    print(f"\n==========================================")
    print(f"  SETUP GOOGLE DRIVE: {label.upper()} ({account_name})")
    print(f"==========================================")
    print(f"Browser open hoga, please apne {label} Google Drive account me login karke access allow karein.")
    input("Press Enter to open browser...")
    
    creds = gdrive.get_credentials(account_name, interactive=True)
    if not creds:
        print(f"Failed to authenticate {label} account.")
        return

    config = gdrive.load_gdrive_config()
    folders = gdrive.list_drive_folders(account_name)
    
    print(f"\nAapke {label} Google Drive me available folders:")
    print("0: [Create new folder: 'AI Tech Videos (" + label + ")']")
    for idx, folder in enumerate(folders, start=1):
        print(f"{idx}: {folder['name']} (ID: {folder['id']})")
    
    choice = input(f"\nSelect folder number (default: 0): ").strip()
    if choice and choice.isdigit() and 1 <= int(choice) <= len(folders):
        selected_folder = folders[int(choice) - 1]
        folder_id = selected_folder['id']
        folder_name = selected_folder['name']
    else:
        folder_id = ""
        folder_name = f"AI Tech Videos ({label})"

    config[account_name] = {
        "folder_id": folder_id,
        "folder_name": folder_name
    }
    gdrive.save_gdrive_config(config)
    print(f"Target folder for {label} set to: '{folder_name}'")

def main():
    print("=== Google Drive Multi-Account Setup ===")
    setup_account("english", "English Videos")
    setup_account("hindi", "Hindi Videos")
    print("\n Setup complete! Dono accounts successfully configure ho gaye hain.")

if __name__ == "__main__":
    main()
