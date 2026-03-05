import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
from src.config import ConfigManager
from src.api import RomMClient
from src.watcher import WingosyWatcher
from src.ui import WingosyMainWindow, SetupDialog

VERSION = "0.4.1"

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
    
    # Attempt login with token first if available
    client = RomMClient(config.get("host"), config=config)
    token = config.get("token")
    
    success = False
    if token:
        client.token = token
        # Verify token by fetching library
        if client.fetch_library():
            success = True
    
    if not success:
        # Try login with password if available (legacy or fresh setup)
        password = config.get("password")
        if password:
            success, result = client.login(config.get("username"), password)
            if success:
                config.set("token", result)
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
            client = RomMClient(data["host"])
            success, result = client.login(data["username"], data["password"])
            if success:
                config.set("token", result)
                # DO NOT save password to config.json
            else:
                QMessageBox.critical(None, "Login Failed", result)
                sys.exit(1)
        else:
            sys.exit(0)

    window = WingosyMainWindow(config, client, WingosyWatcher, VERSION)
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
