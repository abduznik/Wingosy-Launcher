import os
import sys
import shutil
import zipfile
from pathlib import Path

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QTabWidget, QTextEdit, 
                             QSystemTrayIcon, QMenu, QApplication, QFileDialog, 
                             QMessageBox, QDialog, QLineEdit, QDialogButtonBox, 
                             QScrollArea)
from PySide6.QtGui import QIcon, QPixmap, QKeySequence, QShortcut
from PySide6.QtCore import Qt, QSettings, Slot, Signal

from src.ui.threads import (ImageFetcher, BiosDownloader, DolphinDownloader, 
                            DirectDownloader, GithubDownloader, ConflictResolveThread)
from src.ui.widgets import get_resource_path, DownloadQueueWidget, format_speed
from src.ui.dialogs import SetupDialog, SettingsDialog, WelcomeDialog, ConflictDialog
from src.ui.tabs.library import LibraryTab
from src.ui.tabs.emulators import EmulatorsTab
from src.utils import zip_path

class WingosyMainWindow(QMainWindow):
    def __init__(self, config_manager, client, watcher_class, version):
        super().__init__()
        self.config, self.client, self.watcher_class, self.version = config_manager, client, watcher_class, version
        self.watcher = None
        self.active_threads = []
        self.image_fetch_queue = []
        self.active_image_fetchers = []
        self.fetch_generation = 0
        self.all_games = []
        self.setWindowTitle("Wingosy Launcher")
        self.resize(1100, 800)
        
        settings = QSettings("Wingosy", "WingosyLauncher")
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        icon_path = get_resource_path("icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.setup_ui()
        self.setup_tray()
        self.ensure_watcher_running()
        
        if self.config.get("first_run", True):
            WelcomeDialog(self).exec()
            self.config.set("first_run", False)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("<h1 style='color: #1e88e5;'>Wingosy Launcher</h1>"))
        header_layout.addStretch()
        
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
        
        # Logs & Downloads Tab
        self.info_tabs = QTabWidget()
        self.download_queue = DownloadQueueWidget()
        self.info_tabs.addTab(self.download_queue, "📥 Downloads")
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("background: #121212; color: #bbdefb; font-family: Consolas;")
        self.info_tabs.addTab(self.log_area, "📝 Logs")
        
        self.tabs.addTab(self.info_tabs, "📊 info")
        main_layout.addWidget(self.tabs)
        
        # Shortcuts
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.library_tab.search_input.setFocus)
        QShortcut(QKeySequence("F5"), self, activated=self.fetch_library_and_populate)
        
        self.fetch_library_and_populate()

    def _on_image_fetched(self, fetcher, generation=None):
        if generation is not None and generation != self.fetch_generation:
            if fetcher in self.active_image_fetchers:
                self.active_image_fetchers.remove(fetcher)
            return
        if fetcher in self.active_image_fetchers:
            self.active_image_fetchers.remove(fetcher)
        if self.image_fetch_queue:
            next_card = self.image_fetch_queue.pop(0)
            new_fetcher = next_card.start_image_fetch(self, self.fetch_generation)
            if new_fetcher:
                self.active_image_fetchers.append(new_fetcher)

    def fetch_library_and_populate(self):
        try:
            res = self.client.fetch_library()
            if res == "REAUTH_REQUIRED":
                QMessageBox.warning(self, "Session Expired", "Your session has expired. Please log in again.")
                self.open_settings()
                return
            
            if res != "REAUTH_REQUIRED" and not isinstance(res, list):
                self.log("❌ Unexpected response from server. Check your RomM version.")
                self._show_empty_library_message("Could not load library. Check logs.")
                return
                
            self.all_games = res
            if isinstance(res, list) and len(res) == 0:
                self._show_empty_library_message("No games found. Check your RomM library or platform filter.")
                return

            platforms = sorted(list(set(g.get('platform_display_name') for g in self.all_games if g.get('platform_display_name'))))
            
            self.library_tab.platform_filter.blockSignals(True)
            self.library_tab.platform_filter.clear()
            self.library_tab.platform_filter.addItem("All Platforms")
            self.library_tab.platform_filter.addItems(platforms)
            self.library_tab.platform_filter.blockSignals(False)
            
            self.library_tab.populate_grid(self.all_games)
        except Exception as e:
            self.log(f"❌ Error fetching library: {e}")

    def _show_empty_library_message(self, message):
        self.library_tab.show_empty_message(message)

    def open_fw(self, emu_name):
        # Local import to avoid circular dependency with dialogs.py
        from src.ui.dialogs import GameDetailDialog 
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
            self.download_queue.add_download(f"BIOS: {fw['file_name']}", fw_dl)
            
            fw_dl.progress.connect(lambda p, s: self.log(f"DL BIOS: {p}% @ {format_speed(s)}"))
            fw_dl.finished.connect(lambda ok, p: self.log(f"✨ BIOS saved to {p}") if ok else self.log(f"❌ BIOS failed: {p}"))
            fw_dl.finished.connect(lambda: self.download_queue.remove_download(fw_dl))
            fw_dl.finished.connect(lambda t=fw_dl: self.active_threads.remove(t) if t in self.active_threads else None)
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
            
            self.download_queue.add_download(name, dl_thread)
            dl_thread.progress.connect(lambda p, s: self.log(f"DL {name}: {p}% @ {format_speed(s)}"))
            dl_thread.finished.connect(lambda ok, p: self.post_dl_emu(name, ok, p, dl_thread))
            dl_thread.finished.connect(lambda: self.download_queue.remove_download(dl_thread))
            dl_thread.finished.connect(lambda t=dl_thread: self.active_threads.remove(t) if t in self.active_threads else None)
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
            
            if mode == "export":
                if not os.path.exists(path):
                    QMessageBox.warning(self, "Export Failed", f"Config path does not exist: {path}")
                    return
                
                target_zip, _ = QFileDialog.getSaveFileName(self, f"Export {name} Config", f"{name}_config.zip", "ZIP Files (*.zip)")
                if target_zip:
                    self.log(f"🔄 Exporting {name} config to {target_zip}...")
                    from src.utils import zip_path
                    zip_path(path, target_zip)
                    self.log(f"✨ {name} config exported.")
            
            elif mode == "import":
                source_zip, _ = QFileDialog.getOpenFileName(self, f"Import {name} Config", "", "ZIP Files (*.zip)")
                if source_zip:
                    self.log(f"🔄 Importing {name} config from {source_zip}...")
                    if os.path.exists(path):
                        shutil.move(path, f"{path}.bak")
                    
                    with zipfile.ZipFile(source_zip, 'r') as z:
                        z.extractall(Path(path).parent)
                    self.log(f"✨ {name} config restored!")
                    
        except Exception as e:
            self.log(f"❌ Config operation error: {e}")

    def log(self, message):
        self.log_area.append(message)

    @Slot(str, str, str, str)
    def handle_conflict(self, title, local_path, temp_dl, rom_id):
        dialog = ConflictDialog(title, self)
        if dialog.exec() == QDialog.Accepted:
            mode = dialog.result_mode
            if mode == "cloud":
                t = ConflictResolveThread(self.watcher, rom_id, title, local_path, os.path.isdir(local_path))
                t.finished.connect(lambda ok: self.log("✅ Cloud save applied." if ok else "❌ Cloud save apply failed."))
                t.finished.connect(lambda t=t: self.active_threads.remove(t) if t in self.active_threads else None)
                self.active_threads.append(t)
                t.start()
            elif mode == "both":
                cloud_bak = str(local_path) + ".cloud_backup"
                if os.path.exists(cloud_bak):
                    if os.path.isdir(cloud_bak): shutil.rmtree(cloud_bak)
                    else: os.remove(cloud_bak)
                shutil.copy2(temp_dl, cloud_bak) if not os.path.isdir(temp_dl) else shutil.copytree(temp_dl, cloud_bak)
                self.log(f"📁 Cloud save backed up to: {cloud_bak}")
        if os.path.exists(temp_dl):
            try: os.remove(temp_dl) if not os.path.isdir(temp_dl) else shutil.rmtree(temp_dl)
            except: pass

    @Slot(str, str)
    def show_notification(self, title, msg):
        self.tray_icon.showMessage(title, msg, QSystemTrayIcon.Information, 3000)

    def open_settings(self):
        SettingsDialog(self.config, self, self).exec()

    def ensure_watcher_running(self):
        if not self.watcher:
            self.watcher = self.watcher_class(self.client, self.config)
            self.watcher.log_signal.connect(self.log)
            self.watcher.path_detected_signal.connect(self.on_path)
            self.watcher.conflict_signal.connect(self.handle_conflict, Qt.QueuedConnection)
            self.watcher.notify_signal.connect(self.show_notification)
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
        settings = QSettings("Wingosy", "WingosyLauncher")
        settings.setValue("geometry", self.saveGeometry())
        if self.tray_icon.isVisible():
            self.hide()
            event.ignore()
