import sys
import os
import re
import webbrowser
import zipfile
import shutil
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, 
                             QLabel, QLineEdit, QPushButton, QDialogButtonBox, 
                             QMessageBox, QProgressBar, QComboBox, QFileDialog, 
                             QSizePolicy, QApplication)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QPixmap, QDesktopServices

from src.ui.threads import (UpdaterThread, SelfUpdateThread,
                             ConnectionTestThread, RomDownloader, CoreDownloadThread, ImageFetcher)
from src.ui.widgets import format_speed, get_resource_path, RETROARCH_PLATFORMS, RETROARCH_CORES

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

class SettingsDialog(QDialog):
    def __init__(self, config_manager, main_window, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.config = config_manager
        self.main_window = main_window
        self.resize(400, 500)
        self.settings_layout = QVBoxLayout(self)
        self.settings_layout.addWidget(QLabel(f"<b>RomM Host:</b> {self.config.get('host')}"))
        
        self.test_btn = QPushButton("🔌 Test Connection")
        self.test_btn.clicked.connect(self.test_connection)
        self.settings_layout.addWidget(self.test_btn)
        
        self.settings_layout.addWidget(QLabel(f"<b>User:</b> {self.config.get('username')}"))
        self.settings_layout.addWidget(QLabel(f"<b>Version:</b> {self.main_window.version}"))
        
        self.auto_pull_btn = QPushButton("Auto Pull Saves: ON" if self.config.get("auto_pull_saves", True) else "Auto Pull Saves: OFF")
        self.auto_pull_btn.setCheckable(True)
        self.auto_pull_btn.setChecked(self.config.get("auto_pull_saves", True))
        self.auto_pull_btn.toggled.connect(self.toggle_auto_pull)
        self.settings_layout.addWidget(self.auto_pull_btn)
        
        self.settings_layout.addWidget(QLabel("<b>Preferred Switch Emulator:</b>"))
        self.switch_pref = QComboBox()
        self.switch_pref.addItems(["Switch (Eden)", "Switch (Yuzu)"])
        prefs = self.config.get("preferred_emulators", {})
        current = prefs.get("switch", "Switch (Eden)")
        self.switch_pref.setCurrentText(current)
        self.switch_pref.currentTextChanged.connect(self.set_switch_pref)
        self.settings_layout.addWidget(self.switch_pref)
        
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

    def test_connection(self):
        self.test_btn.setEnabled(False)
        self.test_btn.setText("Testing...")
        self.test_thread = ConnectionTestThread(self.main_window.client)
        self.test_thread.finished.connect(self.on_test_result)
        self.test_thread.finished.connect(lambda: self.main_window.active_threads.remove(self.test_thread) if self.test_thread in self.main_window.active_threads else None)
        self.main_window.active_threads.append(self.test_thread)
        self.test_thread.start()

    def on_test_result(self, success, msg):
        self.test_btn.setEnabled(True)
        self.test_btn.setText("🔌 Test Connection")
        if success:
            QMessageBox.information(self, "Connection Test", f"✅ {msg}")
        else:
            QMessageBox.critical(self, "Connection Test", f"❌ {msg}")

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

    def set_switch_pref(self, val):
        prefs = self.config.get("preferred_emulators", {})
        prefs["switch"] = val
        self.config.set("preferred_emulators", prefs)

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
            subprocess.Popen([str(current_exe)])
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
            
        self.config.set("token", None)
        self.config.set("password", None)
        QMessageBox.information(self, "Logged Out", "You have been logged out. Restart to log in.")
        QApplication.instance().quit()

class GameDetailDialog(QDialog):
    def __init__(self, game, client, config, main_window, parent=None):
        super().__init__(parent)
        self.game, self.client, self.config, self.main_window = game, client, config, main_window
        self.setWindowTitle(game.get("name"))
        self.resize(500, 450)
        self.dl_thread = None
        layout = QVBoxLayout(self)
        info_layout = QHBoxLayout()
        self.img_label = QLabel()
        self.img_label.setFixedSize(200, 280)
        info_layout.addWidget(self.img_label)
        url = client.get_cover_url(game)
        if url:
            from src.ui.threads import ImageFetcher
            self.img_fetch_thread = ImageFetcher(game['id'], url)
            self.img_fetch_thread.finished.connect(lambda g, p: self.img_label.setPixmap(p.scaled(200, 280)))
            self.img_fetch_thread.finished.connect(lambda t=self.img_fetch_thread: self.main_window.active_threads.remove(t) if t in self.main_window.active_threads else None)
            self.main_window.active_threads.append(self.img_fetch_thread)
            self.img_fetch_thread.start()
        
        detail_layout = QVBoxLayout()
        detail_layout.addWidget(QLabel(f"<h2>{game.get('name')}</h2>"))
        detail_layout.addWidget(QLabel(f"<b>Platform:</b> {game.get('platform_display_name')}"))
        
        self.play_btn = QPushButton("▶ PLAY")
        self.play_btn.setStyleSheet("background: #1e88e5; color: white; font-weight: bold; padding: 10px; font-size: 14pt;")
        self.play_btn.clicked.connect(self.play_game)
        detail_layout.addWidget(self.play_btn)

        files = game.get('files', [])
        self.dl_btn = QPushButton("Download ROM")
        self.dl_btn.setStyleSheet("background: #1565c0; color: white; padding: 8px;")
        self.dl_btn.setVisible(len(files) > 0)
        self.dl_btn.clicked.connect(lambda: self.download_rom(files[0]))
        detail_layout.addWidget(self.dl_btn)
        
        self.cancel_btn = QPushButton("Cancel Download")
        self.cancel_btn.setStyleSheet("background: #c62828; color: white;")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_dl)
        detail_layout.addWidget(self.cancel_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        detail_layout.addWidget(self.progress_bar)
        self.speed_label = QLabel()
        detail_layout.addWidget(self.speed_label)
        
        info_layout.addLayout(detail_layout)
        layout.addLayout(info_layout)
        button_box = QDialogButtonBox(QDialogButtonBox.Close, self)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def play_game(self):
        platform = self.game.get('platform_slug')
        base_rom = self.config.get("base_rom_path")
        rom_name = self.game.get('fs_name')
        
        local_rom = Path(base_rom) / platform / rom_name
        if not local_rom.exists():
            local_rom = Path(base_rom) / rom_name
            if not local_rom.exists():
                found = False
                for root, dirs, files in os.walk(base_rom):
                    if rom_name in files:
                        local_rom = Path(root) / rom_name
                        found = True
                        break
                if not found:
                    QMessageBox.warning(self, "ROM Not Found", f"Could not find {rom_name} in {base_rom}.\nPlease download it first.")
                    return

        emu_data = None
        emu_display_name = None
        preferred = self.config.get("preferred_emulators", {}).get(platform)
        
        # Pass 1: Exact Match (Preferred or Slug)
        if preferred:
            data = self.config.get("emulators").get(preferred)
            if data and data.get("path") and os.path.exists(data.get("path")):
                emu_data = data
                emu_display_name = preferred
        
        if not emu_data:
            for name, data in self.config.get("emulators").items():
                if data.get("platform_slug") == platform:
                    if data.get("path") and os.path.exists(data.get("path")):
                        emu_data = data
                        emu_display_name = name
                        break
                # Special case for Dolphin (historical naming)
                if platform in ["gc", "wii", "ngc"] and name == "GameCube / Wii":
                    if data.get("path") and os.path.exists(data.get("path")):
                        emu_data = data
                        emu_display_name = name
                        break
        
        # Pass 2: RetroArch Fallback
        if not emu_data:
            for name, data in self.config.get("emulators").items():
                if data.get("platform_slug") == "multi":
                    if data.get("path") and os.path.exists(data.get("path")):
                        emu_data = data
                        emu_display_name = name
                        if platform in RETROARCH_PLATFORMS:
                            self.main_window.log(f"🎮 No dedicated emulator for {platform}, falling back to RetroArch")
                        break
        
        if not emu_data:
            QMessageBox.warning(self, "Emulator Not Set", 
                f"No emulator path set for {platform}.\n\n"
                "If you use RetroArch for this platform, make sure its path is set in the Emulators tab.")
            return

        self.main_window.log(f"🎮 Preparing {self.game.get('name')}...")
        self.main_window.ensure_watcher_running()
        
        try:
            # Build launch arguments
            if emu_display_name and "RetroArch" in emu_display_name:
                core_name = RETROARCH_CORES.get(platform)
                if core_name:
                    # Look for the core relative to the RetroArch exe location
                    emu_dir_path = Path(emu_data['path']).parent
                    core_path = emu_dir_path / "cores" / core_name
                    if core_path.exists():
                        args = [emu_data['path'], "-L", str(core_path), str(local_rom)]
                        self.main_window.log(f"🎮 Using core: {core_name}")
                    else:
                        # Core missing — offer to download
                        reply = QMessageBox.question(self, "Core Not Found",
                            f"The core '{core_name}' is not installed for {platform}.\n\n"
                            "Would you like Wingosy to download it automatically now?\n\n"
                            "(This uses RetroArch's buildbot — same source as Online Updater)",
                            QMessageBox.Yes | QMessageBox.No)
                        
                        if reply == QMessageBox.Yes:
                            self.start_core_download(core_name, emu_dir_path, platform)
                        return
                else:
                    # No known core for this platform — launch without -L and let RetroArch show its menu
                    args = [emu_data['path'], str(local_rom)]
                    self.main_window.log(f"⚠️ No known RetroArch core for {platform}, launching without core")
            else:
                args = [emu_data['path'], str(local_rom)]

            proc = subprocess.Popen(args)
            self.main_window.log(f"🚀 Launched {emu_data['exe']} with {rom_name} (PID: {proc.pid})")
            
            if self.main_window.watcher:
                QTimer.singleShot(0, lambda: self.main_window.watcher.track_session(
                    proc, emu_display_name, self.game, str(local_rom), emu_data['path']
                ))
            
            self.accept()
        except Exception as e:
            self.main_window.log(f"❌ Launch Error: {e}")
            QMessageBox.critical(self, "Launch Error", str(e))

    def download_rom(self, file_data):
        suggested = Path(self.config.get("base_rom_path")) / self.game.get('platform_slug', 'unknown')
        os.makedirs(suggested, exist_ok=True)
        target_path, _ = QFileDialog.getSaveFileName(self, "Save ROM", str(suggested / file_data['file_name']))
        if not target_path:
            return
        self.dl_btn.setVisible(False)
        self.cancel_btn.setVisible(True)
        self.progress_bar.setVisible(True)
        
        thread = RomDownloader(self.client, self.game['id'], file_data['file_name'], target_path)
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
        self.dl_btn.setVisible(True)
        self.cancel_btn.setVisible(False)
        self.progress_bar.setVisible(False)
        self.speed_label.setText("")
        if ok:
            QMessageBox.information(self, "Success", f"Downloaded to {path}")
            self.main_window.fetch_library_and_populate() # Refresh to update indicators
        elif path != "Cancelled":
            QMessageBox.critical(self, "Error", f"Download failed: {path}")

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
                self.main_window.log(f"✨ Core {core_name} installed successfully.")
                self.play_game() # Relaunch!
            else:
                QMessageBox.critical(self, "Download Failed",
                    f"Could not download core: {msg}\n\n"
                    "Please try installing it manually via RetroArch's Online Updater.")
        
        thread.finished.connect(on_finished)
        thread.start()
        progress_dlg.exec()
