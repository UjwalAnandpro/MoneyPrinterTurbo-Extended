from app.services.gdrive import get_credentials, build, load_gdrive_config

def check():
    cfg = load_gdrive_config()
    for acc in ["english", "hindi"]:
        creds = get_credentials(acc, interactive=False)
        service = build("drive", "v3", credentials=creds)
        fid = cfg.get(acc, {}).get("folder_id")
        q = f"'{fid}' in parents and trashed=false"
        res = service.files().list(q=q, fields="files(id, name, size)").execute()
        files = res.get("files", [])
        print(f"=== {acc.upper()} FOLDER ({len(files)} files) ===")
        for f in files:
            size_mb = int(f.get('size', 0)) / (1024 * 1024)
            print(f"  - {f.get('name')} ({size_mb:.2f} MB) [ID: {f.get('id')}]")

if __name__ == "__main__":
    check()
