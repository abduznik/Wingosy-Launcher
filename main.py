import os
import sys

# Fix certifi path for PyInstaller frozen exe BEFORE 
# any other imports cache the wrong path
if getattr(sys, 'frozen', False):
    # We are running as a PyInstaller bundle
    # certifi is bundled in the _MEIPASS/certifi/ folder
    _mei = getattr(sys, '_MEIPASS', None)
    if _mei:
        _ca_bundle = os.path.join(_mei, 'certifi', 'cacert.pem')
        if os.path.exists(_ca_bundle):
            os.environ['REQUESTS_CA_BUNDLE'] = _ca_bundle
            os.environ['SSL_CERT_FILE'] = _ca_bundle
            os.environ['CURL_CA_BUNDLE'] = _ca_bundle

import logging
from pathlib import Path

_log_path = Path.home() / ".wingosy" / "app.log"
_log_path.parent.mkdir(parents=True, exist_ok=True)
# Overwrite log on each launch so it stays small
logging.basicConfig(
    filename=str(_log_path),
    filemode='w',
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8"
)
logging.info("=== Wingosy starting ===")
logging.info(f"frozen={getattr(sys, 'frozen', False)}")
logging.info(f"executable={sys.executable}")
logging.info(f"argv={sys.argv}")
logging.info(f"cwd={os.getcwd()}")

from PySide6.QtWidgets import QApplication, QMessageBox
from src.config import ConfigManager
from src.api import RomMClient
from src.watcher import WingosyWatcher
from src.ui import WingosyMainWindow, SetupDialog

import io
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr and hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding='utf-8', errors='replace')

VERSION = "0.6.0"

def _cleanup_old_mei_folders():
    """Delete stale PyInstaller _MEI temp folders from previous runs."""
    try:
        if not getattr(sys, 'frozen', False):
            return
        import time, shutil
        mei_parent = Path(sys._MEIPASS).parent
        current = Path(sys._MEIPASS).name
        now = time.time()
        for item in mei_parent.iterdir():
            if (item.is_dir() 
                    and item.name.startswith('_MEI')
                    and item.name != current):
                try:
                    # Only delete if older than 60 seconds
                    age = now - item.stat().st_mtime
                    if age > 60:
                        shutil.rmtree(str(item))
                        logging.info(
                            f"[MEI] Cleaned up {item.name} "
                            f"(age={age:.0f}s)")
                except Exception as e:
                    logging.info(f"[MEI] Skip {item}: {e}")
    except Exception as e:
        logging.info(f"[MEI cleanup] Error: {e}")

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Wingosy Launcher")
    app.setOrganizationName("Wingosy")
    app.setQuitOnLastWindowClosed(False) # For system tray
    app.setStyle("Fusion")
    
    # Cleanup old executable from previous update
    try:
        current_exe = Path(sys.executable).resolve() if getattr(sys, 'frozen', False) else Path(sys.argv[0]).resolve()
        old_exe = current_exe.parent / "Wingosy_old.exe"
        if old_exe.exists():
            old_exe.unlink(missing_ok=True)
    except Exception:
        pass
    
    config = ConfigManager()
    
    # Migrate emulator paths to new emulators.json schema if needed
    from src.emulators import migrate_old_config
    migrate_old_config(config)
    
    # Set log level from config
    log_level_str = config.get("log_level", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    logging.getLogger().setLevel(log_level)
    logging.info(f"Log level set to {log_level_str}")
    
    # Attempt login with token first if available (loaded from keyring by client)
    client = RomMClient(config.get("host"), config=config)
    
    success = False
    if client.token:
        # Verify token by fetching library
        if client.fetch_library():
            success = True
    
    if not success:
        # Try login with password if available (legacy or fresh setup)
        password = config.get("password")
        if password:
            success, result = client.login(config.get("username"), password)
            if success:
                # Discard password now that we have a token
                config.set("password", None)
            else:
                QMessageBox.warning(None, "Login Failed", f"Stored credentials failed: {result}")
        
    if not success:
        # Force SetupDialog
        setup = SetupDialog(config)
        if setup.exec() == SetupDialog.Accepted:
            data = setup.get_data()
            config.set("host", data["host"])
            config.set("username", data["username"])
            # Attempt login with new credentials
            client = RomMClient(data["host"], config=config)
            success, result = client.login(data["username"], data["password"])
            if not success:
                QMessageBox.critical(None, "Login Failed", result)
                sys.exit(1)
        else:
            sys.exit(0)

    window = WingosyMainWindow(config, client, WingosyWatcher, VERSION)
    window.show()
    
    # Delay MEI cleanup to ensure certifi bundle is loaded
    from PySide6.QtCore import QTimer
    QTimer.singleShot(30000, _cleanup_old_mei_folders)
    
    sys.exit(app.exec())

if __name__ == "__main__":
    try:
        logging.info("Calling main()")
        main()
        logging.info("main() returned normally")
    except Exception as e:
        logging.exception(f"FATAL: {e}")
        raise
