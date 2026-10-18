import time
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.status_service import save_status_files

def run_monitor():
    print("Daily Status Monitor started. Updating status every 3 seconds...")
    consecutive_completed = 0
    while True:
        try:
            data = save_status_files()
            if data.get("is_completed"):
                consecutive_completed += 1
                if consecutive_completed >= 5:
                    print("All tasks completed. Status finalized.")
                    break
            else:
                consecutive_completed = 0
        except Exception as e:
            print(f"Error updating status: {e}")
        time.sleep(3)

if __name__ == "__main__":
    run_monitor()
