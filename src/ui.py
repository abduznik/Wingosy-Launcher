import sys
import os
import requests
import zipfile
import shutil
import subprocess
import time
import json
import webbrowser
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
        self.pass_input = QLineEdit(self.config.get("password"))
        self.pass_input.setEchoMode(QLineEdit.Password)
        layout.addRow("RomM Host:", self.host_input)
        layout.addRow("Username:", self.user_input)
        layout.addRow("Password:", self.pass_input)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_data(self):
        return {
            "host": self.host_input.text(),
            "username": self.user_input.text(),
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
        except:
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
            except: pass
            self.upgrade_btn.clicked.connect(lambda: webbrowser.open(url))
        else:
            QMessageBox.information(self, "No Updates", "You are running the latest version.")

    def do_logout(self):
        self.config.set("token", None)
        self.config.set("password", "")
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
        except:
            pass

class BaseDownloader(QThread):
    progress = Signal(int, float)
    finished = Signal(bool, str)
    
    def __init__(self):
        super().__init__()
        self.is_cancelled = [False]

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
                    if self.is_cancelled[0]:
                        f.close()
                        os.remove(target_path)
                        return False, "Cancelled"
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        elapsed = time.time() - start
                        speed = downloaded / elapsed if elapsed > 0 else 0
                        self.progress.emit(int((downloaded / total) * 100) if total > 0 else 0, speed)
            
            # Extraction logic
            return self.extract_archive(target_path, target_dir)
        except Exception as e:
            return False, str(e)

    def extract_archive(self, file_path, dest_dir):
        try:
            if file_path.endswith('.zip'):
                with zipfile.ZipFile(file_path, 'r') as z:
                    z.extractall(dest_dir)
                os.remove(file_path)
                return True, dest_dir
            elif file_path.endswith('.7z'):
                extracted = False
                if HAS_PY7ZR:
                    try:
                        with py7zr.SevenZipFile(file_path, mode='r') as z:
                            z.extractall(path=dest_dir)
                        extracted = True
                    except: pass
                
                if not extracted:
                    # Try system tar
                    try:
                        subprocess.run(['tar', '-xf', file_path, '-C', dest_dir], check=True)
                        extracted = True
                    except: pass
                
                if extracted:
                    os.remove(file_path)
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
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            resp = requests.get(api_url, timeout=15, headers=headers)
            if resp.status_code != 200:
                download_url = "https://dl.dolphin-emu.org/releases/2512/dolphin-2512-x64.7z"
            else:
                data = resp.json()
                download_url = data['builds'][0]['artifacts']['win-x64']['url']
            
            ok, msg = self.perform_download(download_url, self.target_dir)
            self.finished.emit(ok, msg)
        except Exception as e:
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
        self.is_cancelled = [False]
    def run(self):
        def cb(d, t, s):
            self.progress.emit(int((d / t) * 100), s)
        success = self.client.download_rom(self.rom_id, self.file_name, self.target_path, cb, self.is_cancelled)
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
            success = self.client.download_rom(self.fw['id'], self.fw['file_name'], self.target_path, cb)
        else:
            success = self.client.download_firmware(self.fw, self.target_path, cb)
        
        if success and self.target_path.endswith(('.zip', '.7z')):
            try:
                dest = os.path.dirname(self.target_path)
                if self.target_path.endswith('.zip'):
                    with zipfile.ZipFile(self.target_path, 'r') as z:
                        z.extractall(dest)
                    os.remove(self.target_path)
                elif self.target_path.endswith('.7z') and HAS_PY7ZR:
                    with py7zr.SevenZipFile(self.target_path, mode='r') as z:
                        z.extractall(path=dest)
                    os.remove(self.target_path)
            except:
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
        l = QVBoxLayout(self)
        self.img = QLabel()
        self.img.setFixedSize(150, 200)
        self.img.setAlignment(Qt.AlignCenter)
        l.addWidget(self.img)
        self.t = QLabel(game.get('name', 'Unknown'))
        self.t.setAlignment(Qt.AlignCenter)
        self.t.setStyleSheet("color: white; font-weight: bold; border: none;")
        l.addWidget(self.t)
        url = client.get_cover_url(game)
        if url:
            self.fetcher = ImageFetcher(game['id'], url)
            self.fetcher.finished.connect(self.set_i)
            self.fetcher.start()
    def set_i(self, gid, pix):
        self.img.setPixmap(pix.scaled(150, 200, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
    def mouseReleaseEvent(self, e): 
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.game)

class GameDetailDialog(QDialog):
    def __init__(self, game, client, config, main_window, parent=None):
        super().__init__(parent)
        self.game, self.client, self.config, self.main_window = game, client, config, main_window
        self.setWindowTitle(game.get("name"))
        self.resize(500, 450)
        self.dl_thread = None
        l = QVBoxLayout(self)
        il = QHBoxLayout()
        self.img = QLabel()
        self.img.setFixedSize(200, 280)
        il.addWidget(self.img)
        url = client.get_cover_url(game)
        if url:
            self.img_fetch_thread = ImageFetcher(game['id'], url)
            self.img_fetch_thread.finished.connect(lambda g, p: self.img.setPixmap(p.scaled(200, 280)))
            self.img_fetch_thread.start()
        dt = QVBoxLayout()
        dt.addWidget(QLabel(f"<h2>{game.get('name')}</h2>"))
        dt.addWidget(QLabel(f"<b>Platform:</b> {game.get('platform_display_name')}"))
        
        # PLAY BUTTON
        self.play_btn = QPushButton("▶ PLAY")
        self.play_btn.setStyleSheet("background: #1e88e5; color: white; font-weight: bold; padding: 10px; font-size: 14pt;")
        self.play_btn.clicked.connect(self.play_game)
        dt.addWidget(self.play_btn)

        files = game.get('files', [])
        self.dl_btn = QPushButton("Download ROM")
        self.dl_btn.setStyleSheet("background: #1565c0; color: white; padding: 8px;")
        self.dl_btn.setVisible(len(files) > 0)
        self.dl_btn.clicked.connect(lambda: self.download_rom(files[0]))
        dt.addWidget(self.dl_btn)
        
        self.cancel_btn = QPushButton("Cancel Download")
        self.cancel_btn.setStyleSheet("background: #c62828; color: white;")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_dl)
        dt.addWidget(self.cancel_btn)

        self.p = QProgressBar()
        self.p.setVisible(False)
        dt.addWidget(self.p)
        self.sl = QLabel()
        dt.addWidget(self.sl)
        
        il.addLayout(dt)
        l.addLayout(il)
        bb = QDialogButtonBox(QDialogButtonBox.Close, self)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)

    def play_game(self):
        platform = self.game.get('platform_slug')
        base_rom = self.config.get("base_rom_path")
        rom_name = self.game.get('fs_name')
        
        # Robust ROM search
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
        
        # Check for preferred emulator
        preferred = self.config.get("preferred_emulators", {}).get(platform)
        if preferred:
            data = self.config.get("emulators").get(preferred)
            if data and data.get("path") and os.path.exists(data.get("path")):
                emu_data = data
                emu_display_name = preferred
        
        # Fallback to first available emulator for platform
        if not emu_data:
            for name, data in self.config.get("emulators").items():
                if data.get("platform_slug") == platform or (platform in ["gc", "wii"] and name == "GameCube / Wii"):
                    if data.get("path") and os.path.exists(data.get("path")):
                        emu_data = data
                        emu_display_name = name
                        break
        
        if not emu_data:
            QMessageBox.warning(self, "Emulator Not Set", f"No emulator path set for {platform}.")
            return

        self.main_window.log(f"🎮 Preparing {self.game.get('name')}...")
        if not self.main_window.watcher:
            self.main_window.toggle_tr()
        
        # Resolve path using the standardized display name
        save_path = self.main_window.watcher.resolve_save_path(emu_display_name, self.game.get('name'), str(local_rom), emu_data.get('path'))
        if save_path:
            self.main_window.watcher.skip_next_pull_rom_id = str(self.game['id'])
            is_folder = os.path.isdir(save_path) if os.path.exists(save_path) else False
            # Force pull from server regardless of cache in Play mode
            self.main_window.watcher.pull_server_save(self.game['id'], self.game.get('name'), save_path, is_folder, force=True)
        
        try:
            args = [emu_data['path'], str(local_rom)]
            subprocess.Popen(args)
            self.main_window.log(f"🚀 Launched {emu_data['exe']} with {rom_name}")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Launch Error", str(e))

    def download_rom(self, fd):
        suggested = Path(self.config.get("base_rom_path")) / self.game.get('platform_slug', 'unknown')
        os.makedirs(suggested, exist_ok=True)
        tp, _ = QFileDialog.getSaveFileName(self, "Save ROM", str(suggested / fd['file_name']))
        if not tp:
            return
        self.dl_btn.setVisible(False)
        self.cancel_btn.setVisible(True)
        self.p.setVisible(True)
        self.dl_thread = RomDownloader(self.client, self.game['id'], fd['file_name'], tp)
        self.dl_thread.progress.connect(lambda p, s: (self.p.setValue(p), self.sl.setText(f"Speed: {format_speed(s)}")))
        self.dl_thread.finished.connect(self.on_download_complete)
        self.dl_thread.start()

    def cancel_dl(self):
        if self.dl_thread:
            self.dl_thread.is_cancelled[0] = True
            self.on_download_complete(False, "Cancelled")

    def on_download_complete(self, ok, p):
        self.dl_btn.setVisible(True)
        self.cancel_btn.setVisible(False)
        self.p.setVisible(False)
        self.sl.setText("")
        if ok:
            QMessageBox.information(self, "Success", f"Downloaded to {p}")
        elif p != "Cancelled":
            QMessageBox.critical(self, "Error", "Download failed.")

class WingosyMainWindow(QMainWindow):
    def __init__(self, config_manager, client, watcher_class, version):
        super().__init__()
        self.config, self.client, self.watcher_class, self.version = config_manager, client, watcher_class, version
        self.watcher = None
        self.active_threads = []
        self.all_games = []
        self.setWindowTitle("Wingosy Launcher")
        self.resize(1100, 800)
        
        # Set Application Icon
        icon_path = get_resource_path("icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.setup_ui()
        self.setup_tray()
        # Enable tracking by default on startup
        self.toggle_tr()

    def setup_ui(self):
        c = QWidget()
        self.setCentralWidget(c)
        l = QVBoxLayout(c)
        h = QHBoxLayout()
        h.addWidget(QLabel("<h1 style='color: #1e88e5;'>Wingosy Launcher</h1>"))
        h.addStretch()
        self.tr_btn = QPushButton("START TRACKING")
        self.tr_btn.setFixedSize(150, 35)
        self.tr_btn.setStyleSheet("background: #1565c0; color: white; font-weight: bold;")
        self.tr_btn.clicked.connect(self.toggle_tr)
        h.addWidget(self.tr_btn)
        self.st_btn = QPushButton("⚙️ Settings")
        self.st_btn.clicked.connect(self.open_st)
        h.addWidget(self.st_btn)
        l.addLayout(h)
        
        # Library Filtering UI
        filter_l = QHBoxLayout()
        filter_l.addWidget(QLabel("Search:"))
        self.search_in = QLineEdit()
        self.search_in.setPlaceholderText("Filter games...")
        self.search_in.textChanged.connect(self.apply_filters)
        filter_l.addWidget(self.search_in)
        
        filter_l.addWidget(QLabel("Platform:"))
        self.plat_filter = QComboBox()
        self.plat_filter.addItem("All Platforms")
        self.plat_filter.currentTextChanged.connect(self.apply_filters)
        filter_l.addWidget(self.plat_filter)
        l.addLayout(filter_l)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabBar::tab { background: #2d2d2d; color: white; padding: 10px; }
            QTabBar::tab:selected { background: #1e1e1e; border-bottom: 2px solid #1e88e5; }
        """)
        
        self.gw = QWidget()
        self.gl = QGridLayout(self.gw)
        self.gl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.gw)
        self.tabs.addTab(sc, "🎮 Library")
        
        self.et = QWidget()
        el = QVBoxLayout(self.et)
        pb = QWidget()
        f = QFormLayout(pb)
        rl = QHBoxLayout()
        self.rp = QLineEdit(self.config.get("base_rom_path"))
        rl.addWidget(self.rp)
        br = QPushButton("Browse")
        br.clicked.connect(lambda: self.br_d("base_rom_path", self.rp))
        rl.addWidget(br)
        f.addRow("ROM Path:", rl)
        xl = QHBoxLayout()
        self.ep = QLineEdit(self.config.get("base_emu_path"))
        xl.addWidget(self.ep)
        be = QPushButton("Browse")
        be.clicked.connect(lambda: self.br_d("base_emu_path", self.ep))
        xl.addWidget(be)
        f.addRow("Emu Path:", xl)
        sp = QPushButton("Save Paths")
        sp.clicked.connect(self.sv_p)
        f.addRow(sp)
        el.addWidget(pb)
        self.emu_list_layout = QVBoxLayout()
        self.emu_list_layout.setAlignment(Qt.AlignTop)
        es = QScrollArea()
        es.setWidgetResizable(True)
        ec = QWidget()
        ec.setLayout(self.emu_list_layout)
        es.setWidget(ec)
        el.addWidget(es)
        self.tabs.addTab(self.et, "🛠️ Emulators")
        self.la = QTextEdit()
        self.la.setReadOnly(True)
        self.la.setStyleSheet("background: #121212; color: #bbdefb; font-family: Consolas;")
        self.tabs.addTab(self.la, "📝 Logs")
        l.addWidget(self.tabs)
        self.pop_lib()
        self.pop_emu()

    def apply_filters(self):
        txt = self.search_in.text().lower()
        plat = self.plat_filter.currentText()
        
        filtered = []
        for g in self.all_games:
            name_match = txt in g.get('name', '').lower() or txt in g.get('fs_name', '').lower()
            plat_match = plat == "All Platforms" or g.get('platform_display_name') == plat
            if name_match and plat_match:
                filtered.append(g)
        self.populate_grid(filtered)

    def br_d(self, k, le):
        d = QFileDialog.getExistingDirectory(self, "Select Folder")
        if d:
            le.setText(d)
            self.config.set(k, d)

    def sv_p(self):
        self.config.set("base_rom_path", self.rp.text())
        self.config.set("base_emu_path", self.ep.text())
        self.log("✅ Paths saved.")
    
    def pop_lib(self):
        self.all_games = self.client.fetch_library()
        plats = sorted(list(set(g.get('platform_display_name') for g in self.all_games if g.get('platform_display_name'))))
        self.plat_filter.blockSignals(True)
        self.plat_filter.clear()
        self.plat_filter.addItem("All Platforms")
        self.plat_filter.addItems(plats)
        self.plat_filter.blockSignals(False)
        self.populate_grid(self.all_games)

    def populate_grid(self, games):
        for i in reversed(range(self.gl.count())):
            item = self.gl.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)
        r, c = 0, 0
        for g in games:
            cd = GameCard(g, self.client)
            cd.clicked.connect(lambda game=g: GameDetailDialog(game, self.client, self.config, self, self).exec())
            self.gl.addWidget(cd, r, c)
            c += 1
            if c >= 6:
                c = 0
                r = r + 1

    def pop_emu(self):
        for i in reversed(range(self.emu_list_layout.count())):
            item = self.emu_list_layout.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)
        emus = self.config.get("emulators", {})
        for n, d in emus.items():
            row = QWidget()
            row.setStyleSheet("background: #252525; border-radius: 5px; margin: 2px;")
            rl = QHBoxLayout(row)
            name_label = QLabel(f"<b>{n}</b>")
            name_label.setFixedWidth(180)
            rl.addWidget(name_label)
            p_lbl = QLabel(d.get("path") or "Not Set")
            p_lbl.setStyleSheet("color: #888;")
            rl.addWidget(p_lbl, 1)
            
            btn_dl = QPushButton("⬇️ Latest")
            btn_dl.clicked.connect(lambda checked, name=n: self.dl_emu(name))
            rl.addWidget(btn_dl)
            
            btn_fw = QPushButton("📂 Firmware")
            btn_fw.clicked.connect(lambda checked, name=n: self.open_fw(name))
            rl.addWidget(btn_fw)
            
            btn_p = QPushButton("Path")
            btn_p.clicked.connect(lambda checked, name=n: self.st_ep(name))
            rl.addWidget(btn_p)
            
            btn_ex = QPushButton("📤 Export")
            btn_ex.clicked.connect(lambda checked, name=n: self.sy_ec(name, "export"))
            rl.addWidget(btn_ex)
            
            btn_im = QPushButton("📥 Import")
            btn_im.clicked.connect(lambda checked, name=n: self.sy_ec(name, "import"))
            rl.addWidget(btn_im)
            
            self.emu_list_layout.addWidget(row)

    def open_fw(self, emu_name):
        emu_data = self.config.get("emulators").get(emu_name)
        slug = emu_data.get("platform_slug")
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{emu_name} BIOS / Firmware")
        dlg.resize(600, 500)
        main_l = QVBoxLayout(dlg)
        search_l = QHBoxLayout()
        search_l.addWidget(QLabel("Search Library:"))
        self.fw_search_in = QLineEdit(slug if slug != "multi" else "bios")
        search_l.addWidget(self.fw_search_in)
        search_btn = QPushButton("Search")
        search_l.addWidget(search_btn)
        main_l.addLayout(search_l)
        self.fw_scroll = QScrollArea()
        self.fw_scroll.setWidgetResizable(True)
        self.fw_list_container = QWidget()
        self.fw_list_layout = QVBoxLayout(self.fw_list_container)
        self.fw_list_layout.setAlignment(Qt.AlignTop)
        self.fw_scroll.setWidget(self.fw_list_container)
        main_l.addWidget(self.fw_scroll)

        def perform_search():
            for i in reversed(range(self.fw_list_layout.count())):
                item = self.fw_list_layout.itemAt(i)
                if item and item.widget():
                    item.widget().setParent(None)
            term = self.fw_search_in.text().lower()
            fws = self.client.get_firmware()
            matches = [f for f in fws if term in f.get('file_name', '').lower() or term in f.get('platform_name', '').lower() or term in f.get('platform_slug', '')]
            for g in self.client.user_games:
                if term in g.get('name', '').lower() or term in g.get('fs_name', '').lower():
                    files = g.get('files', [])
                    if files:
                        matches.append({'id': g['id'], 'file_name': files[0].get('file_name'), 'platform_name': g.get('platform_display_name', 'Library'), 'is_rom': True})
            if not matches:
                self.fw_list_layout.addWidget(QLabel("No results found."))
                return
            platforms = {}
            for f in matches:
                p = f.get('platform_name', 'Other')
                if p not in platforms:
                    platforms[p] = []
                platforms[p].append(f)
            for p_name, files in platforms.items():
                if len(files) > 1:
                    group = QWidget()
                    gl = QVBoxLayout(group)
                    group.setStyleSheet("background: #333; border-radius: 5px; margin: 5px;")
                    gl.addWidget(QLabel(f"<b>{p_name} ({len(files)} files)</b>"))
                    db = QPushButton("Download Full Set")
                    db.clicked.connect(lambda checked, f_list=files: self.dl_fw_list(emu_name, f_list, dlg))
                    gl.addWidget(db)
                    self.fw_list_layout.addWidget(group)
                else:
                    f = files[0]
                    fr = QWidget()
                    fr_l = QHBoxLayout(fr)
                    fr_l.addWidget(QLabel(f"{f['file_name']} ({f['platform_name']})"))
                    db = QPushButton("Download")
                    db.clicked.connect(lambda checked, fw=f: self.dl_fw(emu_name, fw, dlg))
                    fr_l.addWidget(db)
                    self.fw_list_layout.addWidget(fr)

        search_btn.clicked.connect(perform_search)
        perform_search()
        bb = QDialogButtonBox(QDialogButtonBox.Close, dlg)
        bb.rejected.connect(dlg.reject)
        main_l.addWidget(bb)
        dlg.exec()

    def dl_fw_list(self, emu, fw_list, dlg):
        count = 0
        for fw in fw_list:
            if self.start_fw_download(emu, fw):
                count += 1
        self.log(f"✨ BIOS Sync: {count} downloads started.")
        dlg.accept()

    def dl_fw(self, emu, fw, dlg):
        if self.start_fw_download(emu, fw):
            dlg.accept()

    def start_fw_download(self, emu, fw):
        emu_path = self.config.get("emulators")[emu].get("path")
        emu_folder = self.config.get("emulators")[emu].get("folder", emu)
        suggested = Path(emu_path).parent / "bios" if emu_path else Path(self.config.get("base_emu_path")) / emu_folder / "bios"
        os.makedirs(suggested, exist_ok=True)
        tp = suggested / fw['file_name']
        self.log(f"🚀 BIOS: {fw['file_name']}...")
        fw_dl = BiosDownloader(self.client, fw, str(tp))
        fw_dl.progress.connect(lambda p, s: self.log(f"DL BIOS: {p}% @ {format_speed(s)}"))
        fw_dl.finished.connect(lambda ok, p: self.log(f"✨ BIOS saved to {p}") if ok else self.log(f"❌ BIOS failed: {p}"))
        fw_dl.finished.connect(lambda: self.active_threads.remove(fw_dl) if fw_dl in self.active_threads else None)
        self.active_threads.append(fw_dl)
        fw_dl.start()
        return True

    def dl_emu(self, n):
        emu_data = self.config.get("emulators")[n]
        url = emu_data.get("url")
        repo = emu_data.get("github")
        is_dolphin = emu_data.get("dolphin_latest", False)
        
        target_dir = Path(self.config.get("base_emu_path")) / emu_data.get("folder")
        os.makedirs(target_dir, exist_ok=True)
        self.log(f"🚀 Downloading {n}...")
        
        if is_dolphin:
            dl_thread = DolphinDownloader(str(target_dir))
        elif url:
            dl_thread = DirectDownloader(url, str(target_dir))
        elif repo:
            dl_thread = GithubDownloader(repo, str(target_dir))
        else:
            return
            
        dl_thread.progress.connect(lambda p, s: self.log(f"DL {n}: {p}% @ {format_speed(s)}"))
        dl_thread.finished.connect(lambda ok, p: self.post_dl_emu(n, ok, p, dl_thread))
        self.active_threads.append(dl_thread)
        dl_thread.start()

    def post_dl_emu(self, n, ok, p, thread):
        if ok:
            self.log(f"✨ {n} ready at {p}")
            emu_data = self.config.get("emulators")[n]
            exe_name = emu_data['exe']
            for root, dirs, files in os.walk(p):
                if exe_name in files:
                    full_path = os.path.join(root, exe_name)
                    emu_data['path'] = full_path
                    self.config.set("emulators", self.config.get("emulators"))
                    self.pop_emu()
                    self.log(f"📍 Path: {full_path}")
                    trigger = emu_data.get("portable_trigger")
                    if trigger:
                        trigger_path = Path(root) / trigger
                        if not trigger_path.exists():
                            if '.' in trigger:
                                trigger_path.write_text("")
                            else:
                                trigger_path.mkdir(exist_ok=True)
                            self.log(f"📁 Portable mode enabled ({trigger})")
                    break
        else:
            self.log(f"❌ {p}")
        if thread in self.active_threads:
            self.active_threads.remove(thread)

    def st_ep(self, n):
        p, _ = QFileDialog.getOpenFileName(self, f"Select {n}.exe", filter="Executables (*.exe)")
        if p:
            ems = self.config.get("emulators")
            ems[n]["path"] = p
            self.config.set("emulators", ems)
            self.pop_emu()

    @Slot(str, str)
    def on_path(self, n, p):
        emus = self.config.get("emulators")
        updated = False
        for disp_name, data in emus.items():
            if data['exe'].lower() == n.lower() or n.lower() in disp_name.lower():
                data['path'] = p
                updated = True
                break
        if updated:
            self.config.set("emulators", emus)
            self.pop_emu()

    def sy_ec(self, n, m):
        d = self.config.get("emulators")[n]
        p = d.get("config_path")
        if not p:
            return
        self.log(f"🔄 {m}ing {n} config...")
        if m == "export" and os.path.exists(p):
            from src.utils import zip_path
            t = f"conf_{n}.zip"
            zip_path(p, t)
            if self.client.upload_save(17, f"{n}-config", t)[0]:
                self.log(f"✨ {n} config exported.")
            if os.path.exists(t):
                os.remove(t)
        elif m == "import":
            l = self.client.get_latest_save(17)
            if l:
                t = "dl_conf.zip"
                if self.client.download_save(l, t):
                    if os.path.exists(p):
                        shutil.move(p, f"{p}.bak")
                    with zipfile.ZipFile(t, 'r') as z:
                        z.extractall(Path(p).parent)
                    self.log(f"✨ {n} config restored!")
                    os.remove(t)

    def log(self, m):
        self.la.append(m)

    def open_st(self):
        SettingsDialog(self.config, self, self).exec()

    def toggle_tr(self):
        if not self.watcher:
            self.watcher = self.watcher_class(self.client, self.config)
            self.watcher.log_signal.connect(self.log)
            self.watcher.path_detected_signal.connect(self.on_path)
            self.watcher.start()
            self.tr_btn.setText("STOP TRACKING")
            self.tr_btn.setStyleSheet("background: #c62828; color: white;")
        else:
            self.watcher.running = False
            self.watcher.wait()
            self.watcher = None
            self.tr_btn.setText("START TRACKING")
            self.tr_btn.setStyleSheet("background: #1565c0; color: white;")

    def setup_tray(self):
        # Create a tray icon using the app icon if possible
        icon_path = get_resource_path("icon.png")
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
        else:
            px = QPixmap(32, 32)
            px.fill(QColor("#1565c0"))
            icon = QIcon(px)
            
        self.ti = QSystemTrayIcon(icon, self)
        menu = QMenu()
        menu.addAction("Show", self.showNormal)
        menu.addAction("Exit", QApplication.instance().quit)
        self.ti.setContextMenu(menu)
        self.ti.show()

    def closeEvent(self, e):
        if self.ti.isVisible():
            self.hide()
            e.ignore()

if __name__ == "__main__":
    pass
