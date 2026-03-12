import os
import shutil
import logging
import requests
from pathlib import Path

WINGOSY_DIR = Path.home() / ".wingosy"
LOCAL_7Z = WINGOSY_DIR / "7z.exe"

# Direct download URL for 7-Zip standalone console executable (7zr.exe)
SEVENZIP_URL = "https://www.7-zip.org/a/7zr.exe"

def get_7zip_exe() -> str | None:
    """
    Returns path to 7z/7zr executable.
    Priority:
    1. System 7z.exe (from PATH or common dirs)
    2. Cached .wingosy/7z.exe
    3. Download 7zr.exe to .wingosy/7z.exe
    4. None (use py7zr fallback)
    """
    # 1. Check PATH
    found = shutil.which("7z")
    if found:
        logging.debug(f"[7zip] Found system 7z: {found}")
        return found
    
    # Check common Windows install paths
    candidates = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            logging.debug(f"[7zip] Found at: {c}")
            return c
    
    # 2. Check cached .wingosy/7z.exe
    if LOCAL_7Z.exists():
        logging.debug(f"[7zip] Using cached: {LOCAL_7Z}")
        return str(LOCAL_7Z)
    
    # 3. Download 7zr.exe
    logging.info("[7zip] 7-Zip not found — downloading portable 7zr.exe...")
    try:
        WINGOSY_DIR.mkdir(parents=True, exist_ok=True)
        # Use verify=False or certifi if needed, usually requests handles it
        r = requests.get(SEVENZIP_URL, timeout=30, stream=True)
        r.raise_for_status()
        
        with open(LOCAL_7Z, 'wb') as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        
        logging.info(f"[7zip] Downloaded to {LOCAL_7Z}")
        return str(LOCAL_7Z)
    
    except Exception as e:
        logging.error(f"[7zip] Download failed: {e}")
        return None
