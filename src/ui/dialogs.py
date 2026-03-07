import sys
import os
import re
import webbrowser
import zipfile
import shutil
import subprocess
import logging
from pathlib import Path
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, 
                             QLabel, QLineEdit, QPushButton, QDialogButtonBox, 
                             QMessageBox, QProgressBar, QComboBox, QFileDialog, 
                             QSizePolicy, QApplication, QWidget, QSpinBox, QScrollArea,
                             QCheckBox, QListWidget, QListWidgetItem)
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QEventLoop
from PySide6.QtGui import QPixmap, QDesktopServices

from src.ui.threads import (UpdaterThread, SelfUpdateThread,
                             ConnectionTestThread, RomDownloader, CoreDownloadThread, ImageFetcher, ConflictResolveThread, GameDescriptionFetcher, ExtractionThread, WikiFetcherThread)
from src.ui.widgets import format_speed, format_size, get_resource_path
from src.platforms import RETROARCH_PLATFORMS, RETROARCH_CORES, platform_matches
from src import emulators, windows_saves
from src.utils import read_retroarch_cfg, write_retroarch_cfg_values, zip_path

_retroarch_autosave_checked = False
_ppsspp_assets_checked = False

WINDOWS_PLATFORM_SLUGS = ["windows", "win", "pc", "pc-windows", "windows-games", "win95", "win98"]
EXCLUDED_EXES = [
    "unins000.exe", "uninstall.exe", "setup.exe",
    "vcredist", "directx", "dxsetup.exe",
    "vc_redist", "crashpad_handler.exe",
    "notification_helper.exe", "UnityCrashHandler",
    "dotnet", "netfx", "oalinst.exe",
    "DXSETUP.exe", "installscript",
    "dx_setup", "redist"
]

def check_retroarch_autosave(ra_exe_path, platform_slug, parent, config=None):
    """
    Check retroarch.cfg and prompt user to enable auto save/load if needed.
    Only prompts when save mode includes states (state or both).
    PSP is always skipped.
    Fires at most once per app session.
    """
    global _retroarch_autosave_checked
    if _retroarch_autosave_checked:
        return
    _retroarch_autosave_checked = True

    # PSP always uses SAVEDATA folder sync — states not applicable
    if platform_slug in ("psp", "playstation-portable"):
        return

    # Only relevant when the user wants state-based saving
    save_mode = config.get("retroarch_save_mode", "srm") if config else "srm"
    if save_mode == "srm":
        return  # SRM-only mode doesn't need savestates enabled

    cfg_path = Path(ra_exe_path).parent / "retroarch.cfg"
    if not cfg_path.exists():
        return

    cfg = read_retroarch_cfg(str(cfg_path))
    auto_save = cfg.get("savestate_auto_save", "false")
    auto_load = cfg.get("savestate_auto_load", "false")

    if auto_save == "true" and auto_load == "true":
        return  # already good

    missing = []
    if auto_save != "true": missing.append("savestate_auto_save")
    if auto_load != "true": missing.append("savestate_auto_load")

    result = QMessageBox.question(
        parent,
        "RetroArch Auto-Save States",
        f"Your RetroArch save mode is set to '{save_mode}' but auto save/load "
        f"states are disabled in retroarch.cfg.\n\n"
        f"Disabled: {', '.join(missing)}\n\n"
        f"Would you like Wingosy to enable them automatically?\n"
        f"(Writes to: {cfg_path})",
        QMessageBox.Yes | QMessageBox.No
    )
    if result == QMessageBox.Yes:
        write_retroarch_cfg_values(str(cfg_path), {
            "savestate_auto_save": "true",
            "savestate_auto_load": "true"
        })
        QMessageBox.information(
            parent,
            "RetroArch Auto-Save States",
            "✅ Auto save/load states enabled in retroarch.cfg."
        )

def check_ppsspp_assets(ra_exe_path, parent):
    global _ppsspp_assets_checked
    if _ppsspp_assets_checked:
        return
    _ppsspp_assets_checked = True
    
    system_ppsspp = Path(ra_exe_path).parent / "system" / "PPSSPP"
    zim_path = system_ppsspp / "ppge_atlas.zim"
    if zim_path.exists():
        return
    
    result = QMessageBox.question(
        parent,
        "PPSSPP Assets Missing",
        "PPSSPP requires asset files to run correctly.\n\n"
        "ppge_atlas.zim is missing from:\n"
        f"{system_ppsspp}\n\n"
        "Would you like Wingosy to download them now?\n"
        "(~2MB from buildbot.libretro.com)",
        QMessageBox.Yes | QMessageBox.No
    )
    if result != QMessageBox.Yes:
        return
    
    progress = QMessageBox(parent)
    progress.setWindowTitle("Downloading PPSSPP Assets")
    progress.setText("Downloading PPSSPP assets...\nPlease wait.")
    progress.setStandardButtons(QMessageBox.NoButton)
    progress.show()
    QApplication.processEvents()
    
    try:
        import urllib.request, zipfile, tempfile
        url = "https://buildbot.libretro.com/assets/system/PPSSPP.zip"
        system_ppsspp.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".zip",
                                         delete=False) as tmp:
            tmp_path = tmp.name
        urllib.request.urlretrieve(url, tmp_path)
        with zipfile.ZipFile(tmp_path, 'r') as z:
            for member in z.namelist():
                relative = member
                if relative.startswith("PPSSPP/"):
                    relative = relative[len("PPSSPP/"):]
                if not relative:
                    continue
                target = system_ppsspp / relative
                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as src, \
                         open(target, 'wb') as dst:
                        dst.write(src.read())
        Path(tmp_path).unlink(missing_ok=True)
        progress.close()
        QMessageBox.information(parent, "PPSSPP Assets Ready",
            "PPSSPP assets downloaded successfully. ✅")
    except Exception as e:
        progress.close()
        QMessageBox.warning(parent, "Download Failed",
            f"Could not download PPSSPP assets:\n{e}\n\n"
            f"You can manually place them in:\n{system_ppsspp}")

class WelcomeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to Wingosy Launcher")
        self.resize(500, 350)
        layout = QVBoxLayout(self)
        
        title = QLabel("<h1>Welcome to Wingosy!</h1>")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        info = QLabel(
            "<p style='font-size: 12pt;'>Your setup is almost complete. Follow these steps to get started:</p>"
            "<ol style='font-size: 11pt;'>"
            "<li><b>Step 1:</b> Enter your RomM server URL and credentials (done!).</li>"
            "<li><b>Step 2:</b> Go to the <b>Emulators</b> tab to set your ROM and Emulator paths.</li>"
            "<li><b>Step 3:</b> Click any game in your library and hit <b>PLAY</b>. Wingosy handles the rest!</li>"
            "</ol>"
            "<p>Happy gaming!</p>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        
        layout.addStretch()
        btn = QPushButton("Get Started")
        btn.setStyleSheet("background: #1e88e5; color: white; font-weight: bold; padding: 10px;")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)

class ConflictDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Save Conflict: {title}")
        self.resize(450, 200)
        layout = QVBoxLayout(self)
        
        msg = QLabel(
            f"Both local and cloud saves exist for <b>{title}</b>, and they differ.<br><br>"
            "Which one would you like to use?"
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)
        
        layout.addStretch()
        btn_layout = QHBoxLayout()
        
        self.result_mode = None # "cloud", "local", "both"
        
        cloud_btn = QPushButton("☁️ Use Cloud")
        cloud_btn.clicked.connect(lambda: self.finish("cloud"))
        btn_layout.addWidget(cloud_btn)
        
        local_btn = QPushButton("💾 Keep Local")
        local_btn.clicked.connect(lambda: self.finish("local"))
        btn_layout.addWidget(local_btn)
        
        both_btn = QPushButton("📁 Keep Both")
        both_btn.clicked.connect(lambda: self.finish("both"))
        btn_layout.addWidget(both_btn)
        
        layout.addLayout(btn_layout)

    def finish(self, mode):
        self.result_mode = mode
        self.accept()

class SetupDialog(QDialog):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wingosy Setup")
        self.config = config_manager
        self.resize(400, 200)
        layout = QFormLayout(self)
        self.host_input = QLineEdit(self.config.get("host"))
        self.user_input = QLineEdit(self.config.get("username"))
        self.pass_input = QLineEdit("") # Do not load from config
        self.pass_input.setEchoMode(QLineEdit.Password)
        layout.addRow("RomM Host:", self.host_input)
        layout.addRow("Username:", self.user_input)
        layout.addRow("Password:", self.pass_input)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def validate_and_accept(self):
        host = self.host_input.text().strip()
        url_pattern = re.compile(r'^https?://.+')
        if not url_pattern.match(host):
            QMessageBox.warning(self, "Invalid Host", "Please enter a valid URL (starting with http:// or https://)")
            return
        self.accept()

    def get_data(self):
        return {
            "host": self.host_input.text().strip().rstrip('/'),
            "username": self.user_input.text().strip(),
            "password": self.pass_input.text()
        }

class ExePickerDialog(QDialog):
    def __init__(self, exes, game_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Choose Executable — {game_name}")
        self.setMinimumSize(600, 450)
        self.selected_exe = None
        
        self.setStyleSheet("QDialog { background-color: #1e1e1e; color: #ffffff; }")
        
        layout = QVBoxLayout(self)
        title_label = QLabel("Multiple executables found. Please select the one to launch:")
        title_label.setStyleSheet("font-size: 12pt; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title_label)
        
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #555;
                font-size: 10pt;
            }
            QListWidget::item {
                padding: 12px;
                border-bottom: 1px solid #3a3a3a;
            }
            QListWidget::item:selected {
                background-color: #0d6efd;
                color: #ffffff;
            }
            QListWidget::item:hover {
                background-color: #3a3a3a;
            }
        """)
        
        for exe_path in exes:
            try:
                size = os.path.getsize(exe_path)
                size_str = format_size(size)
            except Exception:
                size_str = "Unknown"
                
            item_text = f"{os.path.basename(exe_path)}\n({size_str}) — {exe_path}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, exe_path)
            self.list_widget.addItem(item)
            
        layout.addWidget(self.list_widget)
        
        buttons = QHBoxLayout()
        launch_btn = QPushButton("▶ Launch Selected")
        launch_btn.setStyleSheet("background: #2e7d32; color: white; font-weight: bold; padding: 10px; font-size: 11pt;")
        launch_btn.clicked.connect(self.accept_selection)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("background: #444; color: #eee; padding: 10px;")
        cancel_btn.clicked.connect(self.reject)
        
        buttons.addStretch()
        buttons.addWidget(cancel_btn)
        buttons.addWidget(launch_btn)
        layout.addLayout(buttons)

    def accept_selection(self):
        selected_item = self.list_widget.currentItem()
        if selected_item:
            self.selected_exe = selected_item.data(Qt.UserRole)
            self.accept()
        else:
            QMessageBox.warning(self, "No Selection", "Please select an executable from the list.")

class WikiSuggestionsDialog(QDialog):
    def __init__(self, suggestions, game_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Save Location Suggestions — {game_name}")
        self.setMinimumSize(600, 450)
        self.selected_path = None
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Found {len(suggestions)} possible save locations from PCGamingWiki:"))
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        list_layout = QVBoxLayout(container)
        list_layout.setAlignment(Qt.AlignTop)
        
        for item in suggestions:
            row = QWidget()
            row.setStyleSheet("background: #252525; border-radius: 5px; margin: 2px;")
            rl = QHBoxLayout(row)
            
            # Badge
            badge = QLabel(item["path_type"])
            color = "#2e7d32" if item["exists"] else "#555"
            badge.setStyleSheet(f"background: {color}; color: white; padding: 2px 6px; border-radius: 3px; font-weight: bold;")
            rl.addWidget(badge)
            
            info = QVBoxLayout()
            info.addWidget(QLabel(f"<b>{item['expanded_path']}</b>"))
            rl.addLayout(info, 1)
            
            browse_btn = QPushButton("📁 Browse Here")
            browse_btn.clicked.connect(lambda checked, p=item['expanded_path']: self.browse_and_confirm(p))
            rl.addWidget(browse_btn)
            
            list_layout.addWidget(row)
            
        scroll.setWidget(container)
        layout.addWidget(scroll)
        
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def browse_and_confirm(self, start_path):
        # Find nearest existing parent
        p = Path(start_path)
        while not p.exists() and p.parent != p:
            p = p.parent
            
        directory = QFileDialog.getExistingDirectory(self, "Select Save Folder", str(p))
        if directory:
            res = QMessageBox.question(self, "Confirm Save Directory", 
                f"You selected:\n{directory}\n\nIs this the correct save folder?")
            if res == QMessageBox.Yes:
                self.selected_path = directory
                self.accept()

class SaveSyncSetupDialog(QDialog):
    def __init__(self, game_name, config, main_window, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Up Save Sync")
        self.game_name = game_name
        self.config = config
        self.main_window = main_window
        self.selected_path = None
        
        self.setFixedSize(450, 250)
        layout = QVBoxLayout(self)
        
        msg = QLabel(f"Where does <b>{game_name}</b> save its files?<br><br>Setting this up enables automatic cloud backup.")
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignCenter)
        layout.addWidget(msg)
        
        layout.addStretch()
        
        btn_wiki = QPushButton("🌐 Get PCGamingWiki Suggestions")
        btn_wiki.setStyleSheet("padding: 10px; background: #1565c0; color: white; font-weight: bold;")
        btn_wiki.setVisible(self.config.get("pcgamingwiki_enabled", True))
        btn_wiki.clicked.connect(self.get_suggestions)
        layout.addWidget(btn_wiki)
        
        btn_manual = QPushButton("📁 Browse Manually")
        btn_manual.setStyleSheet("padding: 8px;")
        btn_manual.clicked.connect(self.browse_manually)
        layout.addWidget(btn_manual)
        
        btn_skip = QPushButton("▶ Skip for Now")
        btn_skip.clicked.connect(self.reject)
        layout.addWidget(btn_skip)

    def get_suggestions(self):
        # Show loading
        loading = QMessageBox(self)
        loading.setWindowTitle("Fetching Suggestions")
        loading.setText("Querying PCGamingWiki...")
        loading.setStandardButtons(QMessageBox.NoButton)
        loading.show()
        QApplication.processEvents()
        
        # We'll use a local event loop to wait for the thread
        loop = QEventLoop()
        results = []
        def on_finished(res):
            nonlocal results
            results = res
            loop.quit()
            
        thread = WikiFetcherThread(self.game_name, self.config.get("windows_games_dir", ""))
        thread.finished.connect(on_finished)
        thread.start()
        loop.exec()
        loading.close()
        
        if not results:
            QMessageBox.information(self, "No Suggestions", "No suggestions found for this game. Please browse manually.")
            self.browse_manually()
            return
            
        dialog = WikiSuggestionsDialog(results, self.game_name, self)
        if dialog.exec() == QDialog.Accepted:
            self.selected_path = dialog.selected_path
            self.accept()

    def browse_manually(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Save Folder")
        if directory:
            self.selected_path = directory
            self.accept()

class WindowsGameSettingsDialog(QDialog):
    def __init__(self, game, config, main_window, parent=None):
        super().__init__(parent)
        self.game, self.config, self.main_window = game, config, main_window
        self.setWindowTitle(f"Game Settings — {game.get('name')}")
        self.resize(550, 500)
        
        self.save_data = windows_saves.get_windows_save(game['id']) or {"name": game.get('name')}
        self.default_exe = self.save_data.get("default_exe")
        self.save_dir = self.save_data.get("save_dir")
        
        layout = QVBoxLayout(self)
        
        # Section 1: Default Executable
        layout.addWidget(QLabel("<h3>Default Executable</h3>"))
        layout.addWidget(QLabel("Choose which .exe to launch by default instead of being asked every time."))
        
        self.exe_status = QLabel()
        self.exe_status.setStyleSheet("color: #aaa; margin: 10px 0;")
        layout.addWidget(self.exe_status)
        
        exe_btns = QHBoxLayout()
        auto_btn = QPushButton("🔍 Auto-detect")
        auto_btn.clicked.connect(self.auto_detect_exe)
        exe_btns.addWidget(auto_btn)
        
        browse_btn = QPushButton("📁 Browse")
        browse_btn.clicked.connect(self.browse_exe)
        exe_btns.addWidget(browse_btn)
        layout.addLayout(exe_btns)
        
        layout.addSpacing(20)
        
        # Section 2: Save Directory
        layout.addWidget(QLabel("<h3>Save Directory</h3>"))
        layout.addWidget(QLabel("Where does this game store its saves? Wingosy will sync this folder to the cloud."))
        
        self.save_status = QLabel()
        self.save_status.setStyleSheet("color: #aaa; margin: 10px 0;")
        layout.addWidget(self.save_status)
        
        save_btns = QHBoxLayout()
        wiki_btn = QPushButton("🌐 PCGamingWiki Suggestions")
        wiki_btn.setVisible(self.config.get("pcgamingwiki_enabled", True))
        wiki_btn.clicked.connect(self.get_wiki_suggestions)
        save_btns.addWidget(wiki_btn)
        
        manual_btn = QPushButton("📁 Browse Manually")
        manual_btn.clicked.connect(self.browse_save_dir)
        save_btns.addWidget(manual_btn)
        layout.addLayout(save_btns)
        
        self.sync_status = QLabel()
        self.sync_status.setStyleSheet("font-weight: bold; margin-top: 5px;")
        layout.addWidget(self.sync_status)
        
        layout.addStretch()
        
        # Dialog buttons
        bottom_btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        bottom_btns.accepted.connect(self.save_and_close)
        bottom_btns.rejected.connect(self.reject)
        layout.addWidget(bottom_btns)
        
        self.update_ui()

    def update_ui(self):
        if self.default_exe:
            filename = os.path.basename(self.default_exe)
            self.exe_status.setText(f"<b>{filename}</b><br><small>{self.default_exe}</small>")
        else:
            self.exe_status.setText("No default set — will ask on each launch")
            
        if self.save_dir:
            self.save_status.setText(self.save_dir)
            if os.path.exists(self.save_dir):
                self.sync_status.setText("<span style='color: #4caf50;'>✅ Cloud sync active</span>")
            else:
                self.sync_status.setText("<span style='color: #ff5252;'>⚠️ Folder does not exist</span>")
        else:
            self.save_status.setText("Not configured — no cloud sync active")
            self.sync_status.setText("")

    def auto_detect_exe(self):
        rom_name = self.game.get('fs_name')
        if not rom_name: return
        folder_name = Path(rom_name).stem
        win_dir = self.config.get("windows_games_dir")
        if not win_dir: return
        
        folder = Path(win_dir) / folder_name
        if not folder.exists(): return
        
        exes = []
        for p in folder.rglob("*.exe"):
            name = p.name.lower()
            if not any(ex in name for ex in EXCLUDED_EXES):
                exes.append(str(p))
        
        if not exes:
            QMessageBox.information(self, "No EXEs", "No executables found in the game folder.")
            return
            
        picker = ExePickerDialog(exes, self.game.get("name"), self)
        if picker.exec() == QDialog.Accepted:
            self.default_exe = picker.selected_exe
            self.update_ui()

    def browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Game Executable", "", "Executables (*.exe)")
        if path:
            self.default_exe = path
            self.update_ui()

    def get_wiki_suggestions(self):
        loading = QMessageBox(self)
        loading.setWindowTitle("Fetching Suggestions")
        loading.setText("Querying PCGamingWiki...")
        loading.setStandardButtons(QMessageBox.NoButton)
        loading.show()
        QApplication.processEvents()
        
        loop = QEventLoop()
        results = []
        def on_finished(res):
            nonlocal results
            results = res
            loop.quit()
            
        thread = WikiFetcherThread(self.game.get("name"), self.config.get("windows_games_dir", ""))
        thread.finished.connect(on_finished)
        thread.start()
        loop.exec()
        loading.close()
        
        if not results:
            QMessageBox.information(self, "No Suggestions", "No suggestions found for this game.")
            return
            
        dialog = WikiSuggestionsDialog(results, self.game.get("name"), self)
        if dialog.exec() == QDialog.Accepted:
            self.save_dir = dialog.selected_path
            self.update_ui()

    def browse_save_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Save Folder")
        if directory:
            self.save_dir = directory
            self.update_ui()

    def save_and_close(self):
        windows_saves.set_windows_save(self.game['id'], self.game['name'], self.save_dir, self.default_exe)
        self.accept()

class SettingsDialog(QDialog):
    def __init__(self, config_manager, main_window, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.config = config_manager
        self.main_window = main_window
        self.resize(400, 600)
        self.settings_layout = QVBoxLayout(self)

        host_layout = QHBoxLayout()
        host_layout.addWidget(QLabel("Server Host:"))
        self.host_input = QLineEdit()
        self.host_input.setText(self.config.get("host", ""))
        self.host_input.setPlaceholderText("http://192.168.x.x:8285")
        host_layout.addWidget(self.host_input)

        self.test_conn_btn = QPushButton("Test Connection")
        self.test_conn_btn.clicked.connect(self._test_host_connection)
        host_layout.addWidget(self.test_conn_btn)

        self.reconnect_btn = QPushButton("✅ Apply & Re-connect")
        self.reconnect_btn.setVisible(False)
        self.reconnect_btn.setStyleSheet(
            "background: #2e7d32; color: white; padding: 4px 10px;")
        self.reconnect_btn.clicked.connect(self._apply_and_restart)
        host_layout.addWidget(self.reconnect_btn)

        self.settings_layout.addLayout(host_layout)
        
        self.settings_layout.addWidget(QLabel(f"<b>User:</b> {self.config.get('username')}"))
        self.settings_layout.addWidget(QLabel(f"<b>Version:</b> {self.main_window.version}"))
        
        self.auto_pull_btn = QPushButton("Auto Pull Saves: ON" if self.config.get("auto_pull_saves", True) else "Auto Pull Saves: OFF")
        self.auto_pull_btn.setCheckable(True)
        self.auto_pull_btn.setChecked(self.config.get("auto_pull_saves", True))
        self.auto_pull_btn.toggled.connect(self.toggle_auto_pull)
        self.settings_layout.addWidget(self.auto_pull_btn)
        
        # Cards per row setting
        cards_row_layout = QHBoxLayout()
        cards_row_layout.addWidget(QLabel("Cards per row:"))
        self.cards_per_row_spin = QSpinBox()
        self.cards_per_row_spin.setMinimum(1)
        self.cards_per_row_spin.setMaximum(12)
        self.cards_per_row_spin.setValue(self.config.get("cards_per_row", 6))
        self.cards_per_row_spin.valueChanged.connect(self.set_cards_per_row)
        cards_row_layout.addWidget(self.cards_per_row_spin)
        cards_row_layout.addStretch()
        self.settings_layout.addLayout(cards_row_layout)
        
        # RetroArch save mode
        self.settings_layout.addWidget(QLabel("<b>RetroArch Save Mode:</b>"))
        self.ra_save_mode_combo = QComboBox()
        self.ra_save_mode_combo.addItems(["SRM only", "States only", "Both"])
        mode_map = {"srm": "SRM only", "state": "States only", "both": "Both"}
        current_mode = self.config.get("retroarch_save_mode", "srm")
        self.ra_save_mode_combo.setCurrentText(mode_map.get(current_mode, "SRM only"))
        self.ra_save_mode_combo.currentTextChanged.connect(self.set_ra_save_mode)
        self.settings_layout.addWidget(self.ra_save_mode_combo)

        # Windows Games Folder
        self.settings_layout.addWidget(QLabel("<b>Windows Games Folder:</b>"))
        win_folder_layout = QHBoxLayout()
        self.win_folder_input = QLineEdit(self.config.get("windows_games_dir", ""))
        win_folder_layout.addWidget(self.win_folder_input)
        browse_win_btn = QPushButton("Browse")
        browse_win_btn.clicked.connect(self.browse_windows_folder)
        win_folder_layout.addWidget(browse_win_btn)
        self.settings_layout.addLayout(win_folder_layout)
        
        # Wiki Toggle
        self.wiki_check = QCheckBox("PCGamingWiki Save Suggestions")
        self.wiki_check.setChecked(self.config.get("pcgamingwiki_enabled", True))
        self.wiki_check.stateChanged.connect(lambda s: self.config.set("pcgamingwiki_enabled", s == Qt.Checked.value))
        self.settings_layout.addWidget(self.wiki_check)

        # Log level setting
        log_level_layout = QHBoxLayout()
        log_level_layout.addWidget(QLabel("<b>Log Level:</b>"))
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        current_level = self.config.get("log_level", "INFO").upper()
        self.log_level_combo.setCurrentText(current_level)
        self.log_level_combo.currentTextChanged.connect(self.set_log_level)
        log_level_layout.addWidget(self.log_level_combo)
        log_level_layout.addStretch()
        self.settings_layout.addLayout(log_level_layout)
        
        self.settings_layout.addSpacing(10)
        self.update_btn = QPushButton("Check for Updates")
        self.update_btn.clicked.connect(self.check_updates)
        self.settings_layout.addWidget(self.update_btn)
        
        self.upgrade_btn = QPushButton("Upgrade Available!")
        self.upgrade_btn.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold;")
        self.upgrade_btn.setVisible(False)
        self.settings_layout.addWidget(self.upgrade_btn)

        self.update_pbar = QProgressBar()
        self.update_pbar.setVisible(False)
        self.settings_layout.addWidget(self.update_pbar)
        
        self.settings_layout.addStretch()
        
        self.about_btn = QPushButton("ℹ️ About Wingosy")
        self.about_btn.clicked.connect(self.show_about)
        self.settings_layout.addWidget(self.about_btn)
        
        self.logout_btn = QPushButton("Log Out")
        self.logout_btn.setStyleSheet("background-color: #c62828; color: white; padding: 8px;")
        self.logout_btn.clicked.connect(self.do_logout)
        self.settings_layout.addWidget(self.logout_btn)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.reject)
        self.settings_layout.addWidget(buttons)

        self.latest_version_url = ""

    def browse_windows_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Windows Games Folder")
        if directory:
            self.win_folder_input.setText(directory)
            self.config.set("windows_games_dir", directory)

    def _test_host_connection(self):
        host = self.host_input.text().strip()
        if not host:
            QMessageBox.warning(self, "No Host", "Please enter a host URL.")
            return
        self.test_conn_btn.setText("Testing...")
        self.test_conn_btn.setEnabled(False)
        
        # Use the unified test_connection method from the client with retry feedback
        success, message = self.main_window.client.test_connection(
            host_override=host,
            retry_callback=lambda: self.test_conn_btn.setText("Retrying (slow server)...")
        )
        
        self.test_conn_btn.setText("Test Connection")
        self.test_conn_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "Success",
                f"{message} Click 'Apply & Reconnect' to use this host.")
            self.reconnect_btn.setVisible(True)
        else:
            QMessageBox.warning(self, "Failed", message)
            self.reconnect_btn.setVisible(False)

    def _apply_and_restart(self):
        import logging
        import time
        new_host = self.host_input.text().strip()
        logging.info("[Restart] _apply_and_restart called")
        logging.info(f"[Restart] new host={new_host}")
        
        # Save config first
        self.config.set("host", new_host)
        
        # Small delay to ensure config is flushed to disk
        time.sleep(0.3)
        
        QMessageBox.information(self, "Restarting",
            "Host saved. The app will now restart.")
        
        logging.info("[Restart] config saved, calling _do_restart")
        self._do_restart()

    def _do_restart(self):
        import logging
        import subprocess
        import sys
        import os
        
        logging.info("[Restart] _do_restart called")
        logging.info(f"[Restart] frozen="
                     f"{getattr(sys, 'frozen', False)}")
        logging.info(f"[Restart] sys.executable={sys.executable}")
        logging.info(f"[Restart] sys.argv={sys.argv}")
        
        exe = sys.executable  # Always the correct exe, 
                               # frozen or not
        
        try:
            logging.info(f"[Restart] about to Popen: {exe}")
            
            if sys.platform == "win32":
                # Windows: detached process so it survives
                # parent exit
                DETACHED_PROCESS = 0x00000008
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                subprocess.Popen(
                    [exe],
                    close_fds=True,
                    creationflags=(
                        DETACHED_PROCESS | 
                        CREATE_NEW_PROCESS_GROUP),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    [exe],
                    close_fds=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            
            logging.info("[Restart] Popen complete")
        except Exception as e:
            logging.exception(f"[Restart] Popen failed: {e}")
            return
        
        logging.info("[Restart] calling sys.exit(0)")
        sys.exit(0)

    def show_about(self):
        QMessageBox.about(self, "About Wingosy",
            f"<b>Wingosy Launcher</b> v{self.main_window.version}<br><br>"
            "A lightweight Windows game launcher for RomM.<br>"
            "Licensed under GNU GPL v3.0.<br><br>"
            "<a href='https://github.com/abduznik/Wingosy-Launcher'>GitHub Repository</a>"
        )

    def toggle_auto_pull(self, checked):
        self.config.set("auto_pull_saves", checked)
        self.auto_pull_btn.setText("Auto Pull Saves: ON" if checked else "Auto Pull Saves: OFF")

    def set_cards_per_row(self, value):
        self.config.set("cards_per_row", value)
        lib = self.main_window.library_tab
        lib._resize_all_cards()

    def set_log_level(self, text):
        self.config.set("log_level", text)
        level = getattr(logging, text.upper(), logging.INFO)
        logging.getLogger().setLevel(level)
        logging.info(f"Log level changed to {text}")

    def set_ra_save_mode(self, text):
        mode_map = {"SRM only": "srm", "States only": "state", "Both": "both"}
        self.config.set("retroarch_save_mode", mode_map.get(text, "srm"))

    def check_updates(self):
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Checking...")
        self.updater = UpdaterThread(self.main_window.version)
        self.updater.finished.connect(self.on_update_result)
        self.updater.start()

    def on_update_result(self, available, version, url):
        self.update_btn.setEnabled(True)
        self.update_btn.setText("Check for Updates")
        if available:
            self.latest_version_url = url
            self.upgrade_btn.setText(f"Upgrade to v{version}")
            self.upgrade_btn.setVisible(True)
            try: self.upgrade_btn.clicked.disconnect()
            except Exception: pass
            
            if getattr(sys, 'frozen', False):
                self.upgrade_btn.clicked.connect(self.start_self_update)
            else:
                self.upgrade_btn.clicked.connect(lambda: webbrowser.open(url))
        else:
            QMessageBox.information(self, "No Updates", "You are running the latest version.")

    def start_self_update(self):
        self.upgrade_btn.setEnabled(False)
        self.upgrade_btn.setText("Downloading update...")
        self.update_pbar.setVisible(True)
        self.update_pbar.setValue(0)
        
        current_exe = Path(sys.executable).resolve()
        self.updater_thread = SelfUpdateThread(self.latest_version_url, current_exe)
        self.updater_thread.progress.connect(self.update_pbar.setValue)
        self.updater_thread.finished.connect(self.on_self_update_finished)
        self.updater_thread.start()

    def on_self_update_finished(self, success, message):
        if success:
            QMessageBox.information(self, "Update Complete", "Update downloaded! Click OK to restart Wingosy.")
            current_exe = Path(sys.executable).resolve()
            pid = os.getpid()
            bat_path = current_exe.parent / "_wingosy_restart.bat"
            bat_content = (
                f'@echo off\n'
                f':wait\n'
                f'tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL\n'
                f'if not errorlevel 1 (\n'
                f'    timeout /t 1 /nobreak >NUL\n'
                f'    goto wait\n'
                f')\n'
                f'start "" "{current_exe}"\n'
                f'del "%~f0"\n'
            )
            bat_path.write_text(bat_content)
            subprocess.Popen(
                ['cmd.exe', '/c', str(bat_path)],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            QApplication.instance().quit()
        else:
            QMessageBox.critical(self, "Update Failed", f"Could not replace the current file. Please download manually.\nError: {message}")
            self.upgrade_btn.setEnabled(True)
            self.upgrade_btn.setText("Retry Update")
            webbrowser.open(self.latest_version_url)

    def do_logout(self):
        reply = QMessageBox.question(self, "Log Out", "Are you sure you want to log out? You will need to enter your credentials again.", QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
            
        self.main_window.client.logout()
        self.config.set("password", None)
        QMessageBox.information(self, "Logged Out", "You have been logged out. Restart to log in.")
        QApplication.instance().quit()

class GameDetailDialog(QDialog):
    def __init__(self, game, client, config, main_window, parent=None):
        super().__init__(parent)
        self.game, self.client, self.config, self.main_window = game, client, config, main_window
        self.setWindowTitle(game.get("name"))
        self.setFixedSize(800, 550)
        self.dl_thread = None
        self.extract_thread = None
        self._conflict_shown = False
        self._is_windows = game.get("platform_slug") in WINDOWS_PLATFORM_SLUGS
        self._local_rom_path = self._get_local_rom_path()
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Title (Top)
        title_label = QLabel(game.get('name'))
        title_label.setStyleSheet("font-size: 20pt; font-weight: bold; color: #1e88e5;")
        title_label.setWordWrap(True)
        main_layout.addWidget(title_label)
        
        # Content layout (Cover | Metadata)
        content_layout = QHBoxLayout()
        content_layout.setSpacing(25)
        
        # Left: Cover Image (300px wide)
        self.img_label = QLabel()
        self.img_label.setFixedWidth(300)
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setStyleSheet("background: #1a1a1a; border-radius: 6px;")
        content_layout.addWidget(self.img_label)
        
        # Right Column: Metadata + Description + Action Buttons
        right_column = QVBoxLayout()
        right_column.setSpacing(0) # Remove default spacing
        
        platform_label = QLabel(f"<b>Platform:</b> {game.get('platform_display_name')}")
        platform_label.setStyleSheet("font-size: 12pt; margin-bottom: 2px;")
        right_column.addWidget(platform_label)
        
        # Size
        total_bytes = 0
        for f in game.get('files', []):
            total_bytes += f.get('file_size_bytes', 0)
        size_str = format_size(total_bytes)
        size_label = QLabel(f"<b>Size:</b> {size_str}")
        size_label.setStyleSheet("font-size: 12pt; margin-bottom: 8px;")
        right_column.addWidget(size_label)
        
        # Description scroll area
        self.desc_scroll = QScrollArea()
        self.desc_scroll.setWidgetResizable(True)
        self.desc_scroll.setStyleSheet("background: transparent; border: none;")
        self.desc_label = QLabel("Loading description...")
        self.desc_label.setWordWrap(True)
        self.desc_label.setAlignment(Qt.AlignTop)
        self.desc_label.setStyleSheet("color: #ccc; font-size: 11pt; line-height: 1.4;")
        self.desc_scroll.setWidget(self.desc_label)
        right_column.addWidget(self.desc_scroll, 1) # Give it stretch factor 1
        
        # Progress area (for downloads)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        right_column.addWidget(self.progress_bar)
        self.speed_label = QLabel()
        self.speed_label.setAlignment(Qt.AlignCenter)
        right_column.addWidget(self.speed_label)
        
        # Action Buttons Container (Minimized spacing)
        self.actions_layout = QVBoxLayout()
        self.actions_layout.setContentsMargins(0, 5, 0, 0) # Tight to description
        self.actions_layout.setSpacing(4) # Very small margin between buttons
        
        self.play_btn = QPushButton("▶ PLAY")
        self.play_btn.setStyleSheet("background: #2e7d32; color: white; font-weight: bold; padding: 10px; font-size: 13pt;")
        self.play_btn.clicked.connect(self.play_game)
        
        self.game_settings_btn = QPushButton("⚙ Game Settings")
        self.game_settings_btn.setStyleSheet("background: #455a64; color: white; padding: 8px; font-size: 11pt;")
        self.game_settings_btn.clicked.connect(self.open_game_settings)
        
        self.uninstall_btn = QPushButton("🗑 Uninstall")
        self.uninstall_btn.setStyleSheet("background: #8e0000; color: white; padding: 6px; font-size: 11pt;")
        self.uninstall_btn.clicked.connect(self.uninstall_game)
        
        self.dl_btn = QPushButton("⬇ DOWNLOAD")
        self.dl_btn.setStyleSheet("background: #1565c0; color: white; font-weight: bold; padding: 10px; font-size: 13pt;")
        self.dl_btn.clicked.connect(self._on_download_clicked)
        
        self.cancel_btn = QPushButton("Cancel Download")
        self.cancel_btn.setStyleSheet("background: #c62828; color: white;")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_dl)
        
        self.actions_layout.addWidget(self.play_btn)
        self.actions_layout.addWidget(self.game_settings_btn)
        self.actions_layout.addWidget(self.uninstall_btn)
        self.actions_layout.addWidget(self.dl_btn)
        self.actions_layout.addWidget(self.cancel_btn)
        
        right_column.addLayout(self.actions_layout)
        
        content_layout.addLayout(right_column, 1)
        main_layout.addLayout(content_layout)
        
        # Close button (Bottom, spans full width)
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("background: #333; color: #ccc; padding: 8px; font-size: 12pt;")
        close_btn.clicked.connect(self.reject)
        main_layout.addWidget(close_btn)
        
        # Fetch data
        self._update_button_states()
        self._start_image_fetch()
        self._start_desc_fetch()

    def _get_local_rom_path(self):
        platform = self.game.get('platform_slug')
        
        if self._is_windows:
            win_dir = self.config.get("windows_games_dir")
            if not win_dir: return None
            rom_name = self.game.get('fs_name')
            if not rom_name: return None
            folder_name = Path(rom_name).stem
            return Path(win_dir) / folder_name

        base_rom = self.config.get("base_rom_path")
        rom_name = self.game.get('fs_name')
        if not rom_name: return None
        return Path(base_rom) / platform / rom_name

    def _update_button_states(self):
        exists = False
        if self._is_windows:
            folder = self._local_rom_path
            if folder and folder.exists() and folder.is_dir():
                exists = any(folder.rglob("*.exe"))
        else:
            exists = self._local_rom_path and self._local_rom_path.exists()
            if not exists:
                base_rom = self.config.get("base_rom_path")
                rom_name = self.game.get('fs_name')
                if rom_name:
                    root_path = Path(base_rom) / rom_name
                    if root_path.exists():
                        self._local_rom_path = root_path
                        exists = True
        
        self.play_btn.setVisible(exists)
        self.game_settings_btn.setVisible(exists and self._is_windows)
        self.uninstall_btn.setVisible(exists)
        self.dl_btn.setVisible(not exists)

    def open_game_settings(self):
        dialog = WindowsGameSettingsDialog(self.game, self.config, self.main_window, self)
        if dialog.exec() == QDialog.Accepted:
            self.main_window.log(f"✅ Settings updated for {self.game.get('name')}")
            self._update_button_states()

    def _start_image_fetch(self):
        url = self.client.get_cover_url(self.game)
        if url:
            self.img_fetch_thread = ImageFetcher(self.game['id'], url)
            self.img_fetch_thread.finished.connect(self._on_image_loaded)
            self.img_fetch_thread.finished.connect(lambda t=self.img_fetch_thread: self.main_window.active_threads.remove(t) if t in self.main_window.active_threads else None)
            self.main_window.active_threads.append(self.img_fetch_thread)
            self.img_fetch_thread.start()

    def _on_image_loaded(self, gid, pixmap):
        self.img_label.setPixmap(pixmap.scaled(300, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _start_desc_fetch(self):
        self.desc_thread = GameDescriptionFetcher(self.client, self.game['id'])
        self.desc_thread.finished.connect(self.desc_label.setText)
        self.desc_thread.finished.connect(lambda t=self.desc_thread: self.main_window.active_threads.remove(t) if t in self.main_window.active_threads else None)
        self.main_window.active_threads.append(self.desc_thread)
        self.desc_thread.start()

    def uninstall_game(self):
        confirm_msg = f"Are you sure you want to delete {self.game.get('name')} from your device?\n\nCloud saves are not affected."
        if self._is_windows:
            confirm_msg = f"This will permanently delete all files in:\n{self._local_rom_path}\n\nThis cannot be undone. Cloud saves are not affected. Are you sure?"
            
        reply = QMessageBox.question(self, "Uninstall", confirm_msg, QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                path = self._local_rom_path
                if path.exists():
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                    self.main_window.log(f"🗑 {self.game.get('name')} uninstalled")
                    QMessageBox.information(self, "Success", "Game uninstalled.")
                    self._update_button_states()
                    self.main_window.library_tab.apply_filters()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete: {e}")

    def _on_download_clicked(self):
        if self._is_windows:
            win_dir = self.config.get("windows_games_dir")
            if not win_dir:
                QMessageBox.warning(self, "Windows Games Folder Not Set", 
                    "Please set your Windows Games folder in Settings before downloading Windows games.")
                directory = QFileDialog.getExistingDirectory(self, "Select Windows Games Folder")
                if directory:
                    self.config.set("windows_games_dir", directory)
                    win_dir = directory
                else:
                    return

        files = self.game.get('files', [])
        if files:
            self.download_rom(files[0])

    def _do_blocking_pull(self, save_info, is_retroarch):
        watcher = self.main_window.watcher
        rom_id = self.game['id']
        title = self.game['name']
        self._conflict_shown = False
        
        if self._is_windows:
            save_dir = windows_saves.get_save_dir(rom_id)
            if save_dir:
                latest_save = watcher.client.get_latest_save(rom_id)
                if latest_save:
                    result = self._apply_save_blocking(
                        rom_id, title, latest_save,
                        save_dir, file_type="save",
                        is_folder=True)
                    return result is not False
            return True

        if is_retroarch and isinstance(save_info, dict):
            srm_path = save_info.get('srm')
            state_path = save_info.get('state')
            psp_folder = save_info.get('psp_folder')
            
            if psp_folder:
                latest_save = watcher.client.get_latest_save(rom_id)
                if latest_save:
                    result = self._apply_save_blocking(
                        rom_id, title, latest_save,
                        str(psp_folder), file_type="save",
                        is_folder=True)
                    if result is False: return False
                
                state_path = save_info.get('state')
                if state_path:
                    latest_state = watcher.client.get_latest_state(rom_id)
                    if latest_state:
                        result = self._apply_save_blocking(
                            rom_id, title, latest_state,
                            state_path, file_type="state")
                        if result is False: return False
            else:
                if srm_path:
                    latest_save = watcher.client.get_latest_save(rom_id)
                    if latest_save:
                        result = self._apply_save_blocking(
                            rom_id, title, latest_save, 
                            srm_path, file_type="save")
                        if result is False: return False

                if state_path:
                    latest_state = watcher.client.get_latest_state(rom_id)
                    if latest_state:
                        result = self._apply_save_blocking(
                            rom_id, title, latest_state,
                            state_path, file_type="state")
                        if result is False: return False
        else:
            local_path = save_info if isinstance(save_info, str) else None
            if local_path:
                latest_save = watcher.client.get_latest_save(rom_id)
                if latest_save:
                    result = self._apply_save_blocking(
                        rom_id, title, latest_save,
                        local_path, file_type="save")
                    if result is False: return False
        return True

    def _apply_save_blocking(self, rom_id, title, cloud_obj, 
                              local_path, file_type="save", is_folder=False):
        import os, tempfile, zipfile, re
        from pathlib import Path
        watcher = self.main_window.watcher
        server_updated_at = cloud_obj.get('updated_at', '')
        local_exists = os.path.isdir(local_path) if is_folder else os.path.exists(local_path)
        
        cache_entry = watcher.sync_cache.get(str(rom_id), {})
        if isinstance(cache_entry, dict):
            cached_ts = cache_entry.get(f'{file_type}_updated_at','')
        else:
            cached_ts = cache_entry if file_type=='save' else ''
        
        if cached_ts == server_updated_at and local_exists:
            return True
        
        tmp = tempfile.mktemp(suffix=f".{file_type}")
        if file_type == "state":
            ok = watcher.client.download_state(cloud_obj, tmp)
        else:
            ok = watcher.client.download_save(cloud_obj, tmp)
        
        if not ok: return True
        
        rid_str = str(rom_id)
        if (local_exists and (rid_str in watcher.sync_cache) and not self._conflict_shown):
            self._conflict_shown = True
            msg = QMessageBox(self)
            msg.setWindowTitle(f"Save Conflict — {title}")
            msg.setText(f"Your local {file_type} differs from the cloud.\n\nCloud: {server_updated_at[:19]}\nWhich do you want to use?")
            keep_local = msg.addButton("Keep Local", QMessageBox.RejectRole)
            use_cloud = msg.addButton("Use Cloud", QMessageBox.AcceptRole)
            msg.exec()
            if msg.clickedButton() == keep_local:
                if os.path.exists(tmp): os.remove(tmp)
                return True
        
        dest = Path(local_path)
        if is_folder: dest.mkdir(parents=True, exist_ok=True)
        else: dest.parent.mkdir(parents=True, exist_ok=True)
        
        if dest.exists():
            bak = Path(str(dest) + ".bak")
            try:
                if is_folder: shutil.copytree(str(dest), str(bak), dirs_exist_ok=True)
                else: shutil.copy2(str(dest), str(bak))
            except Exception: pass
        
        try:
            if is_folder or (zipfile.is_zipfile(tmp) and not local_path.endswith(('.srm', '.state'))):
                with zipfile.ZipFile(tmp, 'r') as z:
                    z.extractall(local_path)
            else:
                shutil.copy2(tmp, str(dest))
                if (file_type == "state" and dest.suffix == '.state' and not dest.name.endswith('.state.auto')):
                    auto_path = dest.with_name(dest.name + '.auto')
                    if auto_path.exists():
                        if auto_path.is_dir(): shutil.rmtree(auto_path)
                        else: auto_path.unlink()
                    dest.rename(auto_path)
            
            if not isinstance(watcher.sync_cache.get(str(rom_id)), dict):
                watcher.sync_cache[str(rom_id)] = {}
            watcher.sync_cache[str(rom_id)][f'{file_type}_updated_at'] = server_updated_at
            watcher.save_cache()
        except Exception as e: print(f"[Launch] Error applying save: {e}")
        finally:
            if os.path.exists(tmp): os.remove(tmp)
        return True

    def play_game(self):
        platform = self.game.get('platform_slug')
        
        if self._is_windows:
            folder = self._local_rom_path
            if not folder or not folder.exists():
                QMessageBox.warning(self, "Game Folder Not Found", "The extracted game folder was not found.")
                self._update_button_states()
                return
            
            # Check for default exe in windows_saves.json
            saved = windows_saves.get_windows_save(self.game['id'])
            default_exe = saved.get("default_exe") if saved else None
            
            exe_to_launch = None
            if default_exe and os.path.exists(default_exe):
                exe_to_launch = default_exe
            else:
                # Scan recursively including subdirs
                exes = []
                for p in folder.rglob("*.exe"):
                    p_str_lower = str(p).lower()
                    if not any(ex.lower() in p_str_lower for ex in EXCLUDED_EXES):
                        exes.append(str(p))
                
                if not exes:
                    QMessageBox.warning(self, "No Executables Found", "Could not find any game executables in the folder.")
                    return
                
                if len(exes) == 1:
                    exe_to_launch = exes[0]
                else:
                    picker = ExePickerDialog(exes, self.game.get("name"), self)
                    if picker.exec() == QDialog.Accepted:
                        exe_to_launch = picker.selected_exe
                    else:
                        return
            
            if exe_to_launch:
                if self.config.get("auto_pull_saves", True):
                    if not self._do_blocking_pull(None, False): return
                try:
                    self.main_window.log(f"🚀 Launching Windows Game: {os.path.basename(exe_to_launch)}")
                    proc = subprocess.Popen([exe_to_launch], cwd=os.path.dirname(exe_to_launch))
                    save_dir = windows_saves.get_save_dir(self.game['id'])
                    if self.main_window.watcher:
                        QTimer.singleShot(0, lambda: self.main_window.watcher.track_session(
                            proc, "Windows (Native)", self.game, exe_to_launch, exe_to_launch, 
                            skip_pull=True, windows_save_dir=save_dir
                        ))
                    self.accept()
                except Exception as e:
                    QMessageBox.critical(self, "Launch Error", f"Failed to launch game: {e}")
            return

        base_rom = self.config.get("base_rom_path")
        rom_name = self.game.get('fs_name')
        local_rom = self._local_rom_path
        if not local_rom or not local_rom.exists():
            QMessageBox.warning(self, "ROM Not Found", f"Could not find {rom_name} in {base_rom}.\nPlease download it first.")
            return

        emu_data = None
        emu_display_name = None
        all_emus = emulators.load_emulators()
        assigned_id = self.config.get("platform_assignments", {}).get(platform)
        if assigned_id:
            emu_data = next((e for e in all_emus if e["id"] == assigned_id), None)
            if emu_data and emu_data.get("executable_path") and os.path.exists(emu_data["executable_path"]):
                emu_display_name = emu_data["name"]
            else: emu_data = None

        if not emu_data:
            emu_data = emulators.get_emulator_for_platform(platform)
            if emu_data and emu_data.get("executable_path") and os.path.exists(emu_data["executable_path"]):
                emu_display_name = emu_data["name"]
            else: emu_data = None

        if not emu_data:
            emu_data = next((e for e in all_emus if e["id"] == "retroarch"), None)
            if emu_data and emu_data.get("executable_path") and os.path.exists(emu_data["executable_path"]):
                emu_display_name = emu_data["name"]
                if platform in RETROARCH_PLATFORMS:
                    self.main_window.log(f"🎮 No dedicated emulator for {platform}, falling back to RetroArch")
            else: emu_data = None
        
        if not emu_data:
            QMessageBox.warning(self, "Emulator Not Set", f"No emulator path set for {platform}.")
            return

        self.main_window.log(f"🎮 Preparing {self.game.get('name')}...")
        self.main_window.ensure_watcher_running()
        
        try:
            args = []
            is_retroarch = emu_data["id"] == "retroarch"
            emu_path = emu_data["executable_path"]
            if is_retroarch:
                check_retroarch_autosave(emu_path, platform, self, self.config)
                core_name = RETROARCH_CORES.get(platform)
                if platform == "psp" or core_name == "ppsspp_libretro.dll": check_ppsspp_assets(emu_path, self)
                if core_name:
                    emu_dir_path = Path(emu_path).parent
                    core_path = emu_dir_path / "cores" / core_name
                    if core_path.exists():
                        args = [emu_path, "-L", str(core_path), str(local_rom)]
                    else:
                        reply = QMessageBox.question(self, "Core Not Found", f"Download {core_name} automatically?", QMessageBox.Yes | QMessageBox.No)
                        if reply == QMessageBox.Yes: self.start_core_download(core_name, emu_dir_path, platform)
                        return
                else: args = [emu_path, str(local_rom)]
            else:
                raw_args = emu_data.get("launch_args", ["{rom_path}"])
                args = [emu_path]
                for arg in raw_args:
                    processed = arg.replace("{rom_path}", str(local_rom))
                    if processed != emu_path: args.append(processed)

            if self.config.get("auto_pull_saves", True):
                watcher = self.main_window.watcher
                save_info = watcher.get_retroarch_save_path(self.game, {"path": emu_path}) if is_retroarch else watcher.resolve_save_path(emu_display_name, self.game['name'], f"\"{emu_path}\" \"{local_rom}\"", emu_path, platform)[0]
                if not self._do_blocking_pull(save_info, is_retroarch): return

            clean_env = os.environ.copy()
            for key in ["QT_QPA_PLATFORM_PLUGIN_PATH", "QT_PLUGIN_PATH", "QT_QPA_FONTDIR", "QT_QPA_PLATFORM", "QT_STYLE_OVERRIDE"]: clean_env.pop(key, None)
            proc = subprocess.Popen(args, env=clean_env, cwd=str(Path(emu_path).parent))
            self.main_window.log(f"🚀 Launched {emu_display_name} (PID: {proc.pid})")
            if self.main_window.watcher:
                QTimer.singleShot(0, lambda: self.main_window.watcher.track_session(proc, emu_display_name, self.game, str(local_rom), emu_path, skip_pull=True))
            self.accept()
        except Exception as e:
            self.main_window.log(f"❌ Launch Error: {e}")
            QMessageBox.critical(self, "Launch Error", str(e))

    def download_rom(self, file_data):
        if self._is_windows:
            target_dir = Path(self.config.get("windows_games_dir"))
            target_path = target_dir / file_data['file_name']
        else:
            suggested = Path(self.config.get("base_rom_path")) / self.game.get('platform_slug', 'unknown')
            os.makedirs(suggested, exist_ok=True)
            target_path, _ = QFileDialog.getSaveFileName(self, "Save ROM", str(suggested / file_data['file_name']))
            if not target_path: return
            target_path = Path(target_path)

        self.dl_btn.setVisible(False)
        self.cancel_btn.setVisible(True)
        self.progress_bar.setVisible(True)
        self.speed_label.setText("Downloading...")
        thread = RomDownloader(self.client, self.game['id'], file_data['file_name'], str(target_path))
        self.main_window.active_threads.append(thread)
        self.main_window.download_queue.add_download(self.game.get('name'), thread)
        thread.progress.connect(lambda p, s: (self.progress_bar.setValue(p), self.speed_label.setText(f"Speed: {format_speed(s)}")))
        thread.finished.connect(self.on_download_complete)
        thread.finished.connect(lambda: self.main_window.download_queue.remove_download(thread))
        thread.finished.connect(lambda t=thread: self.main_window.active_threads.remove(t) if t in self.main_window.active_threads else None)
        self.dl_thread = thread
        thread.start()

    def cancel_dl(self):
        if self.dl_thread:
            self.dl_thread.requestInterruption()
            self.on_download_complete(False, "Cancelled")

    def on_download_complete(self, ok, path):
        if not ok:
            self.cancel_btn.setVisible(False)
            self.progress_bar.setVisible(False)
            self.speed_label.setText("")
            self._update_button_states()
            if path != "Cancelled": QMessageBox.critical(self, "Error", f"Download failed: {path}")
            return

        if self._is_windows:
            target_dir = self.config.get("windows_games_dir")
            if not target_dir:
                QMessageBox.warning(self, "Windows Games Folder Not Set", "Please set your Windows Games folder in Settings.")
                self.cancel_btn.setVisible(False)
                self.progress_bar.setVisible(False)
                self.speed_label.setText("")
                return
            rom_name = self.game.get('fs_name')
            if rom_name:
                folder_name = Path(rom_name).stem
                final_target = Path(target_dir) / folder_name
                self._local_rom_path = final_target
                self.extract_thread = ExtractionThread(path, str(final_target))
                self.main_window.active_threads.append(self.extract_thread)
                self.extract_thread.progress.connect(self.speed_label.setText)
                self.extract_thread.finished.connect(self.on_extraction_complete)
                self.extract_thread.start()
        else:
            self._local_rom_path = Path(path)
            self.cancel_btn.setVisible(False)
            self.progress_bar.setVisible(False)
            self.speed_label.setText("")
            self._update_button_states()
            QMessageBox.information(self, "Success", f"Downloaded to {path}")
            self.main_window.fetch_library_and_populate()

    def on_extraction_complete(self, ok, msg):
        self.cancel_btn.setVisible(False)
        self.progress_bar.setVisible(False)
        self.speed_label.setText("Ready to play!" if ok else "")
        self._update_button_states()
        if ok:
            QMessageBox.information(self, "Success", "Game extracted and ready to play!")
            self.main_window.fetch_library_and_populate()
        else: QMessageBox.warning(self, "Extraction Finished", msg)

    def start_core_download(self, core_name, emu_dir, platform):
        progress_dlg = QDialog(self)
        progress_dlg.setWindowTitle(f"Downloading {core_name}...")
        progress_dlg.setFixedSize(350, 100)
        dlg_layout = QVBoxLayout(progress_dlg)
        status_label = QLabel(f"Downloading core for {platform}...")
        pbar = QProgressBar()
        dlg_layout.addWidget(status_label)
        dlg_layout.addWidget(pbar)
        progress_dlg.setWindowModality(Qt.ApplicationModal)
        thread = CoreDownloadThread(core_name, emu_dir / "cores")
        thread.progress.connect(lambda val, speed: (pbar.setValue(val), status_label.setText(f"Speed: {format_speed(speed)}")))
        def on_finished(success, msg):
            progress_dlg.close()
            if success:
                self.main_window.log(f"✨ Core {core_name} installed.")
                self.play_game()
            else: QMessageBox.critical(self, "Download Failed", f"Could not download core: {msg}")
        thread.finished.connect(on_finished)
        thread.start()
        progress_dlg.exec()
