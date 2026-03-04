import sys
import os
import requests
import zipfile
import shutil
import subprocess
import time
import json
import webbrowser
import re
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QMainWindow, QTextEdit, QVBoxLayout, 
                             QWidget, QLabel, QLineEdit, QPushButton, QFormLayout, 
                             QDialog, QDialogButtonBox, QMessageBox, QSystemTrayIcon, QMenu,
                             QTabWidget, QGridLayout, QScrollArea, QHBoxLayout, QFileDialog, QProgressBar, QComboBox)
from PySide6.QtGui import QIcon, QAction, QPixmap, QColor, QImage
from PySide6.QtCore import Slot, Qt, QThread, Signal, QSize

# Try to import py7zr for extraction
try:
    import py7zr
    HAS_PY7ZR = True
except ImportError:
    HAS_PY7ZR = False

def get_resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def format_speed(bytes_per_sec):
    if bytes_per_sec > 1024*1024:
        return f"{bytes_per_sec/(1024*1024):.1f} MB/s"
    return f"{bytes_per_sec/1024:.1f} KB/s"

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
        # Basic URL validation
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

class UpdaterThread(QThread):
    finished = Signal(bool, str, str) # update_available, latest_version, download_url
    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version
    def run(self):
        try:
            api_url = "https://api.github.com/repos/abduznik/Wingosy-Launcher/releases/latest"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(api_url, headers=headers, timeout=10).json()
            latest_version = resp.get("tag_name", "").replace("v", "")
            if latest_version and latest_version != self.current_version:
                download_url = ""
                for asset in resp.get("assets", []):
                    if asset["name"].lower().endswith(".exe"):
                        download_url = asset["browser_download_url"]
                        break
                self.finished.emit(True, latest_version, download_url)
            else:
                self.finished.emit(False, latest_version, "")
        except Exception:
            self.finished.emit(False, "", "")

class SettingsDialog(QDialog):
    def __init__(self, config_manager, main_window, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.config = config_manager
        self.main_window = main_window
        self.resize(400, 450)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>RomM Host:</b> {self.config.get('host')}"))
        layout.addWidget(QLabel(f"<b>User:</b> {self.config.get('username')}"))
        layout.addWidget(QLabel(f"<b>Version:</b> {self.main_window.version}"))
        
        self.auto_pull_btn = QPushButton("Auto Pull Saves: ON" if self.config.get("auto_pull_saves", True) else "Auto Pull Saves: OFF")
        self.auto_pull_btn.setCheckable(True)
        self.auto_pull_btn.setChecked(self.config.get("auto_pull_saves", True))
        self.auto_pull_btn.toggled.connect(self.toggle_auto_pull)
        layout.addWidget(self.auto_pull_btn)
        
        layout.addWidget(QLabel("<b>Preferred Switch Emulator:</b>"))
        self.switch_pref = QComboBox()
        self.switch_pref.addItems(["Switch (Eden)", "Switch (Yuzu)"])
        prefs = self.config.get("preferred_emulators", {})
        current = prefs.get("switch", "Switch (Eden)")
        self.switch_pref.setCurrentText(current)
        self.switch_pref.currentTextChanged.connect(self.set_switch_pref)
        layout.addWidget(self.switch_pref)
        
        layout.addSpacing(10)
        self.update_btn = QPushButton("Check for Updates")
        self.update_btn.clicked.connect(self.check_updates)
        layout.addWidget(self.update_btn)
        
        self.upgrade_btn = QPushButton("Upgrade Available!")
        self.upgrade_btn.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold;")
        self.upgrade_btn.setVisible(False)
        layout.addWidget(self.upgrade_btn)
        
        layout.addStretch()
        
        self.logout_btn = QPushButton("Log Out")
        self.logout_btn.setStyleSheet("background-color: #c62828; color: white; padding: 8px;")
        self.logout_btn.clicked.connect(self.do_logout)
        layout.addWidget(self.logout_btn)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
            self.upgrade_btn.setText(f"Upgrade to v{version}")
            self.upgrade_btn.setVisible(True)
            try: self.upgrade_btn.clicked.disconnect()
            except Exception: pass
            self.upgrade_btn.clicked.connect(lambda: webbrowser.open(url))
        else:
            QMessageBox.information(self, "No Updates", "You are running the latest version.")

    def do_logout(self):
        self.config.set("token", None)
        self.config.set("password", None)
        QMessageBox.information(self, "Logged Out", "You have been logged out. Restart to log in.")
        QApplication.instance().quit()

class ImageFetcher(QThread):
    finished = Signal(int, QPixmap)
    def __init__(self, game_id, url):
        super().__init__()
        self.game_id = game_id
        self.url = url
    def run(self):
        try:
            r = requests.get(self.url, timeout=15)
            if r.status_code == 200:
                img = QImage()
                if img.loadFromData(r.content):
                    self.finished.emit(self.game_id, QPixmap.fromImage(img))
        except Exception:
            pass

class BaseDownloader(QThread):
    progress = Signal(int, float)
    finished = Signal(bool, str)
    
    def __init__(self):
        super().__init__()

    def perform_download(self, url, target_dir):
        try:
            name = url.split('/')[-1].split('?')[0]
            target_path = os.path.join(target_dir, name)
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            r = requests.get(url, stream=True, timeout=30, headers=headers)
            r.raise_for_status()
            
            total = int(r.headers.get('content-length', 0))
            downloaded = 0
            start = time.time()
            with open(target_path, 'wb') as f:
                for chunk in r.iter_content(1024*1024):
                    if self.isInterruptionRequested():
                        f.close()
                        try: os.remove(target_path)
                        except Exception: pass
                        return False, "Cancelled"
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        elapsed = time.time() - start
                        speed = downloaded / elapsed if elapsed > 0 else 0
                        self.progress.emit(int((downloaded / total) * 100) if total > 0 else 0, speed)
            
            return self.extract_archive(target_path, target_dir)
        except Exception as e:
            return False, str(e)

    def extract_archive(self, file_path, dest_dir):
        try:
            if file_path.endswith('.zip'):
                with zipfile.ZipFile(file_path, 'r') as z:
                    z.extractall(dest_dir)
                try: os.remove(file_path)
                except Exception: pass
                return True, dest_dir
            elif file_path.endswith('.7z'):
                extracted = False
                if HAS_PY7ZR:
                    try:
                        with py7zr.SevenZipFile(file_path, mode='r') as z:
                            z.extractall(path=dest_dir)
                        extracted = True
                    except Exception: pass
                
                if not extracted:
                    try:
                        subprocess.run(['tar', '-xf', file_path, '-C', dest_dir], check=True)
                        extracted = True
                    except Exception: pass
                
                if extracted:
                    try: os.remove(file_path)
                    except Exception: pass
                    return True, dest_dir
                else:
                    return True, file_path + " (Download complete, but extraction failed. Please extract manually.)"
            return True, file_path
        except Exception as e:
            return True, file_path + f" (Extraction failed: {e})"

class DirectDownloader(BaseDownloader):
    def __init__(self, url, target_dir):
        super().__init__()
        self.url = url
        self.target_dir = target_dir
    def run(self):
        ok, msg = self.perform_download(self.url, self.target_dir)
        self.finished.emit(ok, msg)

class DolphinDownloader(BaseDownloader):
    def __init__(self, target_dir):
        super().__init__()
        self.target_dir = target_dir
    def run(self):
        try:
            api_url = "https://dolphin-emu.org/download/list/master/1/?format=json"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(api_url, timeout=15, headers=headers)
            if resp.status_code != 200:
                download_url = "https://dl.dolphin-emu.org/releases/2512/dolphin-2512-x64.7z"
            else:
                data = resp.json()
                download_url = data['builds'][0]['artifacts']['win-x64']['url']
            
            ok, msg = self.perform_download(download_url, self.target_dir)
            self.finished.emit(ok, msg)
        except Exception:
            download_url = "https://dl.dolphin-emu.org/releases/2512/dolphin-2512-x64.7z"
            ok, msg = self.perform_download(download_url, self.target_dir)
            self.finished.emit(ok, msg)

class GithubDownloader(BaseDownloader):
    def __init__(self, repo, target_dir):
        super().__init__()
        self.repo = repo
        self.target_dir = target_dir
    def run(self):
        try:
            api_url = f"https://api.github.com/repos/{self.repo}/releases/latest"
            headers = {'User-Agent': 'WingosyLauncher'}
            resp_obj = requests.get(api_url, timeout=15, headers=headers)
            if resp_obj.status_code != 200:
                self.finished.emit(False, f"Repo {self.repo} not found.")
                return
                
            resp = resp_obj.json()
            asset = None
            keywords = ['win', 'x64', 'windows', 'amd64', 'qt', 'msvc', 'desktop']
            extensions = ['.zip', '.7z']
            
            for a in resp.get('assets', []):
                name = a['name'].lower()
                if any(k in name for k in keywords) and any(name.endswith(ext) for ext in extensions):
                    if not name.endswith('-symbols.7z') and 'installer' not in name:
                        asset = a
                        break
            
            if not asset:
                for a in resp.get('assets', []):
                    if any(k in a['name'].lower() for k in keywords) and a['name'].endswith(('.zip', '.7z')):
                        asset = a
                        break

            if not asset:
                for a in resp.get('assets', []):
                    if any(k in a['name'].lower() for k in keywords) and a['name'].endswith('.exe'):
                        asset = a
                        break
            
            if not asset:
                self.finished.emit(False, "No suitable release file found.")
                return
            
            ok, msg = self.perform_download(asset['browser_download_url'], self.target_dir)
            self.finished.emit(ok, msg)
        except Exception as e:
            self.finished.emit(False, str(e))

class RomDownloader(QThread):
    progress = Signal(int, float)
    finished = Signal(bool, str)
    def __init__(self, client, rom_id, file_name, target_path):
        super().__init__()
        self.client = client
        self.rom_id = rom_id
        self.file_name = file_name
        self.target_path = target_path
    def run(self):
        def cb(d, t, s):
            self.progress.emit(int((d / t) * 100) if t > 0 else 0, s)
        success = self.client.download_rom(self.rom_id, self.file_name, self.target_path, cb, thread=self)
        self.finished.emit(success, self.target_path)

class BiosDownloader(QThread):
    progress = Signal(int, float)
    finished = Signal(bool, str)
    def __init__(self, client, fw_item, target_path):
        super().__init__()
        self.client = client
        self.fw = fw_item
        self.target_path = target_path
    def run(self):
        def cb(d, t, s):
            self.progress.emit(int((d / t) * 100) if t > 0 else 0, s)
        
        success = False
        if self.fw.get('is_rom'):
            success = self.client.download_rom(self.fw['id'], self.fw['file_name'], self.target_path, cb, thread=self)
        else:
            success = self.client.download_firmware(self.fw, self.target_path, cb, thread=self)
        
        if success and self.target_path.endswith(('.zip', '.7z')):
            try:
                dest = os.path.dirname(self.target_path)
                if self.target_path.endswith('.zip'):
                    with zipfile.ZipFile(self.target_path, 'r') as z:
                        z.extractall(dest)
                    try: os.remove(self.target_path)
                    except Exception: pass
                elif self.target_path.endswith('.7z') and HAS_PY7ZR:
                    with py7zr.SevenZipFile(self.target_path, mode='r') as z:
                        z.extractall(path=dest)
                    try: os.remove(self.target_path)
                    except Exception: pass
            except Exception:
                pass
        self.finished.emit(success, self.target_path)

class GameCard(QWidget):
    clicked = Signal(object)
    def __init__(self, game, client):
        super().__init__()
        self.game, self.client = game, client
        self.setFixedSize(160, 240)
        self.setStyleSheet("""
            QWidget { background: #1e1e1e; border-radius: 8px; }
            QWidget:hover { background: #2c2c2c; border: 2px solid #1565c0; }
        """)
        layout = QVBoxLayout(self)
        self.img_label = QLabel()
        self.img_label.setFixedSize(150, 200)
        self.img_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.img_label)
        self.title_label = QLabel(game.get('name', 'Unknown'))
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("color: white; font-weight: bold; border: none;")
        layout.addWidget(self.title_label)
        url = client.get_cover_url(game)
        if url:
            self.fetcher = ImageFetcher(game['id'], url)
            self.fetcher.finished.connect(self.set_image)
            self.fetcher.start()

    def set_image(self, game_id, pixmap):
        self.img_label.setPixmap(pixmap.scaled(150, 200, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))

    def mouseReleaseEvent(self, event): 
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.game)

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
            self.img_fetch_thread = ImageFetcher(game['id'], url)
            self.img_fetch_thread.finished.connect(lambda g, p: self.img_label.setPixmap(p.scaled(200, 280)))
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
        if preferred:
            data = self.config.get("emulators").get(preferred)
            if data and data.get("path") and os.path.exists(data.get("path")):
                emu_data = data
                emu_display_name = preferred
        
        if not emu_data:
            for name, data in self.config.get("emulators").items():
                if data.get("platform_slug") == platform or (platform in ["gc", "wii", "ngc"] and name == "GameCube / Wii"):
                    if data.get("path") and os.path.exists(data.get("path")):
                        emu_data = data
                        emu_display_name = name
                        break
        
        if not emu_data:
            QMessageBox.warning(self, "Emulator Not Set", f"No emulator path set for {platform}.")
            return

        self.main_window.log(f"🎮 Preparing {self.game.get('name')}...")
        self.main_window.ensure_watcher_running()
        
        try:
            args = [emu_data['path'], str(local_rom)]
            proc = subprocess.Popen(args)
            self.main_window.log(f"🚀 Launched {emu_data['exe']} with {rom_name} (PID: {proc.pid})")
            
            # Pass Popen object to watcher for specific process tracking
            if self.main_window.watcher:
                self.main_window.watcher.track_session(proc, emu_display_name, self.game, str(local_rom), emu_data['path'])
            
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
        self.dl_thread = RomDownloader(self.client, self.game['id'], file_data['file_name'], target_path)
        self.dl_thread.progress.connect(lambda p, s: (self.progress_bar.setValue(p), self.speed_label.setText(f"Speed: {format_speed(s)}")))
        self.dl_thread.finished.connect(self.on_download_complete)
        self.dl_thread.start()

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
        elif path != "Cancelled":
            QMessageBox.critical(self, "Error", f"Download failed: {path}")

class LibraryTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.client = main_window.client
        self.config = main_window.config
        
        layout = QVBoxLayout(self)
        
        # Filter controls
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter games...")
        self.search_input.textChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.search_input)
        
        filter_layout.addWidget(QLabel("Platform:"))
        self.platform_filter = QComboBox()
        self.platform_filter.addItem("All Platforms")
        self.platform_filter.currentTextChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.platform_filter)
        layout.addLayout(filter_layout)

        # Grid area
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.grid_widget)
        layout.addWidget(scroll_area)

    def apply_filters(self):
        text = self.search_input.text().lower()
        platform = self.platform_filter.currentText()
        filtered = [g for g in self.main_window.all_games if (text in g.get('name', '').lower() or text in g.get('fs_name', '').lower()) and (platform == "All Platforms" or g.get('platform_display_name') == platform)]
        self.populate_grid(filtered)

    def populate_grid(self, games):
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)
        
        row, col = 0, 0
        for game in games:
            card = GameCard(game, self.client)
            card.clicked.connect(lambda g=game: GameDetailDialog(g, self.client, self.config, self.main_window, self.main_window).exec())
            self.grid_layout.addWidget(card, row, col)
            col += 1
            if col >= 6:
                col = 0
                row += 1

class EmulatorsTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.config = main_window.config
        
        layout = QVBoxLayout(self)
        
        # Paths setup
        paths_widget = QWidget()
        form_layout = QFormLayout(paths_widget)
        
        rom_path_layout = QHBoxLayout()
        self.rom_path_input = QLineEdit(self.config.get("base_rom_path"))
        rom_path_layout.addWidget(self.rom_path_input)
        browse_rom_btn = QPushButton("Browse")
        browse_rom_btn.clicked.connect(lambda: self.browse_directory("base_rom_path", self.rom_path_input))
        rom_path_layout.addWidget(browse_rom_btn)
        form_layout.addRow("ROM Path:", rom_path_layout)
        
        emu_path_layout = QHBoxLayout()
        self.emu_path_input = QLineEdit(self.config.get("base_emu_path"))
        emu_path_layout.addWidget(self.emu_path_input)
        browse_emu_btn = QPushButton("Browse")
        browse_emu_btn.clicked.connect(lambda: self.browse_directory("base_emu_path", self.emu_path_input))
        emu_path_layout.addWidget(browse_emu_btn)
        form_layout.addRow("Emu Path:", emu_path_layout)
        
        save_paths_btn = QPushButton("Save Paths")
        save_paths_btn.clicked.connect(self.save_paths)
        form_layout.addRow(save_paths_btn)
        layout.addWidget(paths_widget)
        
        # Emulator list
        self.emu_list_layout = QVBoxLayout()
        self.emu_list_layout.setAlignment(Qt.AlignTop)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        emulator_container = QWidget()
        emulator_container.setLayout(self.emu_list_layout)
        scroll_area.setWidget(emulator_container)
        layout.addWidget(scroll_area)
        
        self.populate_emus()

    def browse_directory(self, key, line_edit):
        directory = QFileDialog.getExistingDirectory(self, "Select Folder")
        if directory:
            line_edit.setText(directory)
            self.config.set(key, directory)

    def save_paths(self):
        self.config.set("base_rom_path", self.rom_path_input.text())
        self.config.set("base_emu_path", self.emu_path_input.text())
        self.main_window.log("✅ Paths saved.")

    def populate_emus(self):
        for i in reversed(range(self.emu_list_layout.count())):
            item = self.emu_list_layout.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)
        
        emus = self.config.get("emulators", {})
        for name, data in emus.items():
            row = QWidget()
            row.setStyleSheet("background: #252525; border-radius: 5px; margin: 2px;")
            row_layout = QHBoxLayout(row)
            
            name_label = QLabel(f"<b>{name}</b>")
            name_label.setFixedWidth(180)
            row_layout.addWidget(name_label)
            
            path_label = QLabel(data.get("path") or "Not Set")
            path_label.setStyleSheet("color: #888;")
            row_layout.addWidget(path_label, 1)
            
            btn_latest = QPushButton("⬇️ Latest")
            btn_latest.clicked.connect(lambda checked, n=name: self.main_window.dl_emu(n))
            row_layout.addWidget(btn_latest)
            
            btn_fw = QPushButton("📂 Firmware")
            btn_fw.clicked.connect(lambda checked, n=name: self.main_window.open_fw(n))
            row_layout.addWidget(btn_fw)
            
            btn_path = QPushButton("Path")
            btn_path.clicked.connect(lambda checked, n=name: self.main_window.st_ep(n))
            row_layout.addWidget(btn_path)
            
            btn_export = QPushButton("📤 Export")
            btn_export.clicked.connect(lambda checked, n=name: self.main_window.sy_ec(n, "export"))
            row_layout.addWidget(btn_export)
            
            btn_import = QPushButton("📥 Import")
            btn_import.clicked.connect(lambda checked, n=name: self.main_window.sy_ec(n, "import"))
            row_layout.addWidget(btn_import)
            
            self.emu_list_layout.addWidget(row)

class WingosyMainWindow(QMainWindow):
    def __init__(self, config_manager, client, watcher_class, version):
        super().__init__()
        self.config, self.client, self.watcher_class, self.version = config_manager, client, watcher_class, version
        self.watcher = None
        self.active_threads = []
        self.all_games = []
        self.setWindowTitle("Wingosy Launcher")
        self.resize(1100, 800)
        
        icon_path = get_resource_path("icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.setup_ui()
        self.setup_tray()
        self.ensure_watcher_running()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("<h1 style='color: #1e88e5;'>Wingosy Launcher</h1>"))
        header_layout.addStretch()
        
        # The watcher now starts automatically and handles process-specific tracking.
        # No manual "Start Tracking" button needed.
        self.settings_btn = QPushButton("⚙️ Settings")
        self.settings_btn.clicked.connect(self.open_settings)
        header_layout.addWidget(self.settings_btn)
        main_layout.addLayout(header_layout)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabBar::tab { background: #2d2d2d; color: white; padding: 10px; }
            QTabBar::tab:selected { background: #1e1e1e; border-bottom: 2px solid #1e88e5; }
        """)
        
        self.library_tab = LibraryTab(self)
        self.tabs.addTab(self.library_tab, "🎮 Library")
        
        self.emulators_tab = EmulatorsTab(self)
        self.tabs.addTab(self.emulators_tab, "🛠️ Emulators")
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("background: #121212; color: #bbdefb; font-family: Consolas;")
        self.tabs.addTab(self.log_area, "📝 Logs")
        main_layout.addWidget(self.tabs)
        
        self.fetch_library_and_populate()

    def fetch_library_and_populate(self):
        try:
            self.all_games = self.client.fetch_library()
            platforms = sorted(list(set(g.get('platform_display_name') for g in self.all_games if g.get('platform_display_name'))))
            
            self.library_tab.platform_filter.blockSignals(True)
            self.library_tab.platform_filter.clear()
            self.library_tab.platform_filter.addItem("All Platforms")
            self.library_tab.platform_filter.addItems(platforms)
            self.library_tab.platform_filter.blockSignals(False)
            
            self.library_tab.populate_grid(self.all_games)
        except Exception as e:
            self.log(f"❌ Error fetching library: {e}")

    def open_fw(self, emu_name):
        emu_data = self.config.get("emulators").get(emu_name)
        slug = emu_data.get("platform_slug")
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{emu_name} BIOS / Firmware")
        dialog.resize(600, 500)
        layout = QVBoxLayout(dialog)
        
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search Library:"))
        self.fw_search_input = QLineEdit(slug if slug != "multi" else "bios")
        search_layout.addWidget(self.fw_search_input)
        search_btn = QPushButton("Search")
        search_layout.addWidget(search_btn)
        layout.addLayout(search_layout)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        container = QWidget()
        list_layout = QVBoxLayout(container)
        list_layout.setAlignment(Qt.AlignTop)
        scroll_area.setWidget(container)
        layout.addWidget(scroll_area)

        def perform_search():
            for i in reversed(range(list_layout.count())):
                item = list_layout.itemAt(i)
                if item and item.widget():
                    item.widget().setParent(None)
            
            term = self.fw_search_input.text().lower()
            firmwares = self.client.get_firmware()
            matches = [f for f in firmwares if term in f.get('file_name', '').lower() or term in f.get('platform_name', '').lower() or term in f.get('platform_slug', '')]
            
            for game in self.client.user_games:
                if term in game.get('name', '').lower() or term in game.get('fs_name', '').lower():
                    files = game.get('files', [])
                    if files:
                        matches.append({'id': game['id'], 'file_name': files[0].get('file_name'), 'platform_name': game.get('platform_display_name', 'Library'), 'is_rom': True})
            
            if not matches:
                list_layout.addWidget(QLabel("No results found."))
                return
                
            platforms_map = {}
            for fw in matches:
                p = fw.get('platform_name', 'Other')
                if p not in platforms_map: platforms_map[p] = []
                platforms_map[p].append(fw)
                
            for plat_name, files in platforms_map.items():
                if len(files) > 1:
                    group = QWidget()
                    gl = QVBoxLayout(group)
                    group.setStyleSheet("background: #333; border-radius: 5px; margin: 5px;")
                    gl.addWidget(QLabel(f"<b>{plat_name} ({len(files)} files)</b>"))
                    dl_set_btn = QPushButton("Download Full Set")
                    dl_set_btn.clicked.connect(lambda checked, f_list=files: self.dl_fw_list(emu_name, f_list, dialog))
                    gl.addWidget(dl_set_btn)
                    list_layout.addWidget(group)
                else:
                    fw = files[0]
                    row = QWidget()
                    row_layout = QHBoxLayout(row)
                    row_layout.addWidget(QLabel(f"{fw['file_name']} ({fw['platform_name']})"))
                    dl_btn = QPushButton("Download")
                    dl_btn.clicked.connect(lambda checked, f=fw: self.dl_fw(emu_name, f, dialog))
                    row_layout.addWidget(dl_btn)
                    list_layout.addWidget(row)

        search_btn.clicked.connect(perform_search)
        perform_search()
        
        button_box = QDialogButtonBox(QDialogButtonBox.Close, dialog)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        dialog.exec()

    def dl_fw_list(self, emu, fw_list, dialog):
        count = 0
        for fw in fw_list:
            if self.start_fw_download(emu, fw): count += 1
        self.log(f"✨ BIOS Sync: {count} downloads started.")
        dialog.accept()

    def dl_fw(self, emu, fw, dialog):
        if self.start_fw_download(emu, fw): dialog.accept()

    def start_fw_download(self, emu, fw):
        try:
            emu_path = self.config.get("emulators")[emu].get("path")
            emu_folder = self.config.get("emulators")[emu].get("folder", emu)
            suggested = Path(emu_path).parent / "bios" if emu_path else Path(self.config.get("base_emu_path")) / emu_folder / "bios"
            os.makedirs(suggested, exist_ok=True)
            target_path = suggested / fw['file_name']
            self.log(f"🚀 BIOS: {fw['file_name']}...")
            fw_dl = BiosDownloader(self.client, fw, str(target_path))
            fw_dl.progress.connect(lambda p, s: self.log(f"DL BIOS: {p}% @ {format_speed(s)}"))
            fw_dl.finished.connect(lambda ok, p: self.log(f"✨ BIOS saved to {p}") if ok else self.log(f"❌ BIOS failed: {p}"))
            fw_dl.finished.connect(lambda: self.active_threads.remove(fw_dl) if fw_dl in self.active_threads else None)
            self.active_threads.append(fw_dl)
            fw_dl.start()
            return True
        except Exception as e:
            self.log(f"❌ Error starting BIOS download: {e}")
            return False

    def dl_emu(self, name):
        try:
            emu_data = self.config.get("emulators")[name]
            url, repo = emu_data.get("url"), emu_data.get("github")
            target_dir = Path(self.config.get("base_emu_path")) / emu_data.get("folder")
            os.makedirs(target_dir, exist_ok=True)
            self.log(f"🚀 Downloading {name}...")
            if emu_data.get("dolphin_latest", False): dl_thread = DolphinDownloader(str(target_dir))
            elif url: dl_thread = DirectDownloader(url, str(target_dir))
            elif repo: dl_thread = GithubDownloader(repo, str(target_dir))
            else: return
            dl_thread.progress.connect(lambda p, s: self.log(f"DL {name}: {p}% @ {format_speed(s)}"))
            dl_thread.finished.connect(lambda ok, p: self.post_dl_emu(name, ok, p, dl_thread))
            self.active_threads.append(dl_thread)
            dl_thread.start()
        except Exception as e:
            self.log(f"❌ Error starting emulator download: {e}")

    def post_dl_emu(self, name, ok, path, thread):
        if ok:
            self.log(f"✨ {name} ready at {path}")
            emu_data = self.config.get("emulators")[name]
            exe_name = emu_data['exe']
            for root, dirs, files in os.walk(path):
                if exe_name in files:
                    full_path = os.path.join(root, exe_name)
                    emu_data['path'] = full_path
                    self.config.set("emulators", self.config.get("emulators"))
                    self.emulators_tab.populate_emus()
                    self.log(f"📍 Path: {full_path}")
                    trigger = emu_data.get("portable_trigger")
                    if trigger:
                        trigger_path = Path(root) / trigger
                        if not trigger_path.exists():
                            if '.' in trigger: trigger_path.write_text("")
                            else: trigger_path.mkdir(exist_ok=True)
                            self.log(f"📁 Portable mode enabled ({trigger})")
                    break
        else: self.log(f"❌ {path}")
        if thread in self.active_threads: self.active_threads.remove(thread)

    def st_ep(self, name):
        path, _ = QFileDialog.getOpenFileName(self, f"Select {name}.exe", filter="Executables (*.exe)")
        if path:
            emus = self.config.get("emulators")
            emus[name]["path"] = path
            self.config.set("emulators", emus)
            self.emulators_tab.populate_emus()

    @Slot(str, str)
    def on_path(self, name, path):
        emus = self.config.get("emulators")
        updated = False
        for disp_name, data in emus.items():
            if data['exe'].lower() == name.lower() or name.lower() in disp_name.lower():
                data['path'] = path
                updated = True
                break
        if updated:
            self.config.set("emulators", emus)
            self.emulators_tab.populate_emus()

    def sy_ec(self, name, mode):
        try:
            emu_data = self.config.get("emulators")[name]
            path = emu_data.get("config_path")
            if not path: return
            self.log(f"🔄 {mode}ing {name} config...")
            if mode == "export" and os.path.exists(path):
                from src.utils import zip_path
                temp_zip = f"conf_{name}.zip"
                zip_path(path, temp_zip)
                if self.client.upload_save(17, f"{name}-config", temp_zip)[0]: self.log(f"✨ {name} config exported.")
                if os.path.exists(temp_zip): os.remove(temp_zip)
            elif mode == "import":
                latest = self.client.get_latest_save(17)
                if latest:
                    temp_dl = "dl_conf.zip"
                    if self.client.download_save(latest, temp_dl):
                        if os.path.exists(path): shutil.move(path, f"{path}.bak")
                        with zipfile.ZipFile(temp_dl, 'r') as z: z.extractall(Path(path).parent)
                        self.log(f"✨ {name} config restored!")
                        os.remove(temp_dl)
        except Exception as e:
            self.log(f"❌ Config sync error: {e}")

    def log(self, message):
        self.log_area.append(message)

    def open_settings(self):
        SettingsDialog(self.config, self, self).exec()

    def ensure_watcher_running(self):
        if not self.watcher:
            self.watcher = self.watcher_class(self.client, self.config)
            self.watcher.log_signal.connect(self.log)
            self.watcher.path_detected_signal.connect(self.on_path)
            self.watcher.start()

    def setup_tray(self):
        icon_path = get_resource_path("icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon(QPixmap(32, 32))
        self.tray_icon = QSystemTrayIcon(icon, self)
        menu = QMenu()
        menu.addAction("Show", self.showNormal)
        menu.addAction("Exit", QApplication.instance().quit)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

    def closeEvent(self, event):
        if self.tray_icon.isVisible():
            self.hide()
            event.ignore()

if __name__ == "__main__":
    pass
