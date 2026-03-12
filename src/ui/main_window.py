import os
import sys
import shutil
import zipfile
import logging
from pathlib import Path

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QTabWidget, QTextEdit, 
                             QSystemTrayIcon, QMenu, QApplication, QFileDialog, 
                             QMessageBox, QDialog, QLineEdit, QDialogButtonBox, 
                             QScrollArea)
from PySide6.QtGui import QIcon, QPixmap, QKeySequence, QShortcut
from PySide6.QtCore import Qt, QSettings, Slot, Signal, QThread, QTimer, QEvent, QPoint

from src.ui.threads import (ImageFetcher, BiosDownloader, DolphinDownloader, 
                            DirectDownloader, GithubDownloader, ConflictResolveThread,
                            LocalDiscoveryWorker)
from src.ui.widgets import get_resource_path, DownloadQueueWidget, format_speed
from src.ui.dialogs import SetupDialog, WelcomeDialog, ConflictDialog
from src.ui.dialogs.emulator_editor import AssetPickerDialog
from src.emulator_sources import EMULATOR_SOURCES
from src.ui.tabs.library import LibraryTab
from src.ui.tabs.emulators import EmulatorsTab
from src.ui.tabs.settings import SettingsTab
from src.utils import zip_path, resolve_local_rom_path
from src.platforms import RETROARCH_PLATFORMS, platform_matches
from src import emulators

class LibraryFetchWorker(QThread):
    finished = Signal(object)    # emits the final list or "REAUTH_REQUIRED"
    error = Signal()             # emitted on network failure
    retrying = Signal()          # emitted on Stage 1 timeout
    batch_ready = Signal(list, int) # emits a batch of games and total count

    def __init__(self, client, cached_non_empty=False):
        super().__init__()
        self.client = client
        self.cached_non_empty = cached_non_empty

    def run(self):
        def _on_page(batch, total):
            # Just emit the batch, discovery happens in background later
            self.batch_ready.emit(batch, total)

        try:
            result = self.client.fetch_library(
                retry_callback=lambda: self.retrying.emit(),
                page_callback=_on_page
            )
        except Exception:
            result = None
        
        if result is None:
            self.error.emit()
            return

        # Final result emission (used for final cache and cleanup)
        self.finished.emit(result)

from src.ui.title_bar import WingosyTitleBar

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
        
        # Custom window frame setup
        self.setWindowFlags(Qt.Window)

        # After window is shown, call Windows API to remove title bar but keep resize border
        QTimer.singleShot(0, self._apply_windows_frame)

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

        # 1. Load cache immediately — show games NOW
        self._load_library_from_cache()
        # 2. Then fetch fresh data in background
        QTimer.singleShot(500, self.fetch_library_and_populate)

        if self.config.data.get("keyring_failed"):
            QMessageBox.warning(
                self,
                "Credential Storage Warning",
                "Your system's secure credential manager is unavailable.\n\n"
                "Wingosy has stored your login token using local encryption instead.\n\n"
                "This is less secure than keyring. Consider enabling your OS keyring."
            )
            self.config.data.pop("keyring_failed", None)

        if self.config.get("first_run", True):
            WelcomeDialog(self).exec()
            self.config.set("first_run", False)

    def setup_ui(self):
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        central_widget.setStyleSheet("#centralWidget { background: #1a1a1a; border-radius: 10px; border: 1px solid #333; }")
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Custom Title Bar
        self.title_bar = WingosyTitleBar(self)
        self.title_bar.tab_changed.connect(self._on_tab_changed)
        main_layout.addWidget(self.title_bar)
        
        # Update connection status
        host = self.config.get("host", "")
        self.title_bar.update_connection_status("connected" if self.client.token else "disconnected", host)

        self.tabs = QTabWidget()
        self.tabs.tabBar().hide() # Hide default tab bar
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background: #1a1a1a; }
        """)

        self.library_tab = LibraryTab(self)
        self.tabs.addTab(self.library_tab, "Library")

        self.emulators_tab = EmulatorsTab(self)
        self.tabs.addTab(self.emulators_tab, "Emulators")

        # Logs & Downloads Tab
        self.info_tabs = QTabWidget()
        self.info_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background: #1a1a1a;
            }
            QTabWidget > QTabBar {
                background: #1a1a1a;
                border-bottom: 1px solid #2d2d2d;
            }
            QTabBar::tab {
                background: transparent;
                color: #aaaaaa;
                font-size: 11px;
                padding: 8px 20px;
                border: none;
                border-bottom: 2px solid transparent;
                min-width: 80px;
            }
            QTabBar::tab:selected {
                color: #ffffff;
                border-bottom: 2px solid #0d6efd;
                background: transparent;
            }
            QTabBar::tab:hover {
                color: #dddddd;
                background: rgba(255,255,255,0.04);
            }
            QTabBar::scroller {
                width: 0px;
            }
        """)
        self.download_queue = DownloadQueueWidget()
        self.download_queue.refresh_from_registry()
        self.info_tabs.addTab(self.download_queue, "📥 Downloads")        

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("background: #121212; color: #bbdefb; font-family: Consolas; border: none;")
        self.info_tabs.addTab(self.log_area, "📋 Logs")

        self.tabs.addTab(self.info_tabs, "Logs")
        
        self.settings_tab = SettingsTab(self)
        self.tabs.addTab(self.settings_tab, "Settings")
        
        main_layout.addWidget(self.tabs)
        
        # Shortcuts
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.library_tab.search_input.setFocus)
        QShortcut(QKeySequence("F5"), self, activated=self.fetch_library_and_populate)

    def _on_tab_changed(self, index):
        self.tabs.setCurrentIndex(index)
        self.title_bar.set_active_tab(index)

    def eventFilter(self, obj, event):
        return super().eventFilter(obj, event)

    def _load_library_from_cache(self):
        """Load library_cache.json synchronously on startup for instant display."""
        import json
        cache_path = Path.home() / ".wingosy" / "library_cache.json"
        if not cache_path.exists():
            return
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Validate — must be a list of dicts
            if not isinstance(data, list):
                logging.warning("[Library] Cache invalid format — skipping")
                return

            # Filter out any non-dict entries
            games = [g for g in data if isinstance(g, dict)]

            if not games:
                logging.warning("[Library] Cache empty or all entries invalid")
                return

            self.all_games = games
            self._update_platform_filter(games)
            self.library_tab.populate_games(
                games,
                status=f"📚 Loaded from cache ({len(games)} games)"
            )
            logging.info(f"[Library] Cache loaded: {len(games)} games")
            
            # Start background discovery
            self._start_local_discovery(games)
        except Exception as e:
            logging.warning(f"[Library] Cache load failed: {e}")

    def _start_local_discovery(self, games):
        if hasattr(self, '_discovery_worker') and self._discovery_worker.isRunning():
            self._discovery_worker.stop()
            self._discovery_worker.wait()
        
        self._discovery_worker = LocalDiscoveryWorker(games, self.config.data)
        self._discovery_worker.rom_discovered.connect(self._on_rom_discovered)
        self._discovery_worker.start()

    @Slot(int, str)
    def _on_rom_discovered(self, game_id, local_path):
        # Update flag in main list
        for g in self.all_games:
            if g.get('id') == game_id:
                g['_local_exists'] = True
                break
        
        # Update UI if library tab is showing this game
        self.library_tab.update_game_local_status(game_id, True)

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

    def fetch_library_and_populate(self, force_refresh=False):
        """
        force_refresh=False (default): show cache instantly, 
                                        refresh in background silently.
        force_refresh=True: wipe cache display, fetch fresh from server.
        """
        self.library_tab.refresh_btn.setEnabled(False)
        self.library_tab.retry_btn.setVisible(False)
        self._library_fetch_done = False
        
        if not force_refresh:
            # Step A — Load from cache immediately
            cached, _ = self.client.load_library_cache()
            if cached:
                cached = [g for g in cached if isinstance(g, dict)]
                self.all_games = cached
                # Ensure platform filter is updated for cached games (saves/restores current)
                self._update_platform_filter(cached)
                # Respect current filters instead of showing all
                self.library_tab.apply_filters()
                self.log(f"📦 Loaded {len(cached)} games from cache.")
            else:
                self.log("🔄 Loading library...")
        else:
            self.log("🔄 Force refresh — fetching from server...")
            self.all_games = []
            self.library_tab.populate_grid([]) # Clear grid for fresh fetch

        # Step B — Show status
        self.library_tab.set_status("Connecting to RomM server...")

        # Step C — Start worker
        cached_non_empty = len(self.all_games) > 0
        self._fetch_thread = LibraryFetchWorker(self.client, cached_non_empty=cached_non_empty)
        self._fetch_thread.finished.connect(self._on_library_fetched)
        self._fetch_thread.error.connect(lambda: self.library_tab.set_status("Could not connect to RomM server. Check your settings.", color="#b71c1c"))
        self._fetch_thread.retrying.connect(lambda: self.library_tab.set_status("Server is slow, retrying with longer timeout... (this may take a few minutes)", color="#e65100"))
        self._fetch_thread.batch_ready.connect(self._on_library_batch)
        self._fetch_thread.start()

    def _on_library_batch(self, batch, total):
        """Called as each page arrives from parallel fetcher."""
        if self._library_fetch_done: return
        
        # Avoid duplication if we are building on top of cache 
        # (server data replaces cache batch-by-batch)
        # For simplicity in this progressive view, if we're not force-refreshing,
        # we might just wait for final fetch. But user wants progressive.
        
        # If this is the FIRST batch of a fresh fetch or first launch:
        is_first_batch = (len(self.all_games) == 0 or len(self.all_games) == len(batch))
        
        if is_first_batch:
            already_found = {g['id'] for g in self.all_games if g.get('_local_exists')}
            self.all_games = list(batch)
            for g in self.all_games:
                if g['id'] in already_found:
                    g['_local_exists'] = True
            self.library_tab.populate_grid(self.all_games)
        else:
            # Append subsequent batches
            self.all_games.extend(batch)
            self.library_tab.append_batch(batch)
        
        # Update status
        self.library_tab.set_status(f"Loading library... ({len(self.all_games)} / {total} games)")

    def _on_library_fetched(self, res):
        self._library_fetch_done = True
        self.library_tab.set_status(None) # Hide
        self.library_tab.refresh_btn.setEnabled(True)
        
        if res == "REAUTH_REQUIRED":
            QMessageBox.warning(self, "Session Expired", 
                "Your session has expired. Please log in again.")
            self._on_tab_changed(3) # Settings
            return
        
        if res is None:
            self.log("❌ Failed to fetch library from server.")
            self.library_tab.set_status("Connection failed.", color="#b71c1c")
            return
        
        if not isinstance(res, list):
            self.log("❌ Unexpected response from server. Check your RomM version.")
            return
        
        self.log(f"✅ Library fully loaded: {len(res)} games")
        # Ensure final state is correct (in case batches arrived out of order or were incomplete)
        already_found = {g['id'] for g in self.all_games if g.get('_local_exists')}
        self.all_games = res
        for g in self.all_games:
            if g['id'] in already_found:
                g['_local_exists'] = True

        self._update_platform_filter(res)
        # Final render to ensure everything is in place
        self.library_tab.apply_filters()
        self._start_local_discovery(self.all_games)

    def _update_platform_filter(self, games):
        platforms = sorted(set(
            g.get('platform_display_name') for g in games
            if g.get('platform_display_name')
        ))
        self.library_tab.platform_filter.blockSignals(True)
        previously_selected = self.library_tab.platform_filter.currentText()
        self.library_tab.platform_filter.clear()
        self.library_tab.platform_filter.addItem("All Platforms")
        self.library_tab.platform_filter.addItems(platforms)
        
        # Add No Emulator filter if needed
        all_known = set()
        for emu in emulators.load_emulators():
            all_known.update(emu.get("platform_slugs", []))
            
        has_unknown = any(g.get("platform_slug") not in all_known for g in games)
        if has_unknown:
            self.library_tab.platform_filter.addItem("⚠️ No Emulator")
            
        idx = self.library_tab.platform_filter.findText(previously_selected)
        if idx >= 0:
            self.library_tab.platform_filter.setCurrentIndex(idx)
        self.library_tab.platform_filter.blockSignals(False)

    def _populate_from_games(self, games, is_progressive=False):
        """Populate the UI with a list of games. Called from cache or fresh fetch."""
        # Optimization: If the games list is identical to what we have, 
        # only update if we were previously empty
        self.all_games = games
        
        if not games:
            self._show_empty_library_message(
                "No games found. Check your RomM library or platform filter.")
            return

        # Only rebuild the platform list if not in progressive mode (avoid jitter)
        if not is_progressive:
            self._update_platform_filter(games)
        
        # Force a visual rebuild to update indicators (local exists, etc)
        # But if progressive, only rebuild if it's the first batch or platform changed
        if not is_progressive:
            if hasattr(self.library_tab, '_current_platform'):
                delattr(self.library_tab, '_current_platform')
        
        # Respect current filters instead of showing all
        self.library_tab.apply_filters()

    def _show_empty_library_message(self, message):
        self.library_tab.show_empty_message(message)

    def open_fw(self, emu_name):
        # Local import to avoid circular dependency with dialogs.py
        from src.ui.dialogs import GameDetailDialog 
        all_emus = emulators.load_emulators()
        emu_data = next((e for e in all_emus if e["name"] == emu_name), None)
        if not emu_data: return
        
        slugs = emu_data.get("platform_slugs", [])
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{emu_name} BIOS / Firmware")
        dialog.resize(600, 500)
        layout = QVBoxLayout(dialog)
        
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search Library:"))
        # Use first slug as default search, or 'bios'
        default_term = slugs[0] if slugs and slugs[0] != "multi" else "bios"
        self.fw_search_input = QLineEdit(default_term)
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

    def dl_fw_list(self, emu_name, fw_list, dialog):
        count = 0
        for fw in fw_list:
            if self.start_fw_download(emu_name, fw): count += 1
        self.log(f"✨ BIOS Sync: {count} downloads started.")
        dialog.accept()

    def dl_fw(self, emu_name, fw, dialog):
        if self.start_fw_download(emu_name, fw): dialog.accept()

    def start_fw_download(self, emu_name, fw):
        try:
            all_emus = emulators.load_emulators()
            emu_data = next((e for e in all_emus if e["name"] == emu_name), None)
            if not emu_data: return False

            emu_path = emu_data.get("executable_path")
            emu_folder = emu_data.get("id")
            suggested = Path(emu_path).parent / "bios" if emu_path else Path(self.config.get("base_emu_path")) / emu_folder / "bios"
            os.makedirs(suggested, exist_ok=True)
            target_path = suggested / fw['file_name']
            self.log(f"🚀 BIOS: {fw['file_name']}...")
            fw_dl = BiosDownloader(self.client, fw, str(target_path))
            self.download_queue.add_download(f"BIOS: {fw['file_name']}", fw_dl)
            
            fw_dl.progress.connect(lambda d, t, s: self.log(f"DL BIOS: {100*d/t if t > 0 else 0:.1f}% @ {format_speed(s)}"))
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
            all_emus = emulators.load_emulators()
            emu = next((e for e in all_emus if e["name"] == name), None)
            if not emu: return

            source = EMULATOR_SOURCES.get(emu["id"])
            if not source:
                self.log(f"❌ No download source configured for {name}")
                return

            self.log(f"[Debug] dl_emu called for: {name}, id: {emu['id']}, source type: {source['type']}")

            emu_folder = emu.get("folder", emu["id"])
            base_emu_dir = Path(self.config.get("base_emu_path") or Path.home() / ".wingosy" / "emulators")
            target_dir = base_emu_dir / emu_folder
            os.makedirs(target_dir, exist_ok=True)

            def start_download(url, asset_name=None):
                t = DirectDownloader(url, str(target_dir))
                display_name = f"{name} ({asset_name})" if asset_name else name
                self.download_queue.add_download(f"Emulator: {display_name}", t)
                t.progress.connect(lambda d, t_bytes, s: self.log(f"DL {name}: {100*d/t_bytes if t_bytes > 0 else 0:.1f}% @ {format_speed(s)}"))
                
                def on_finished(ok, path, e_data=emu, e_name=name, e_dir=target_dir, thread=t, s_cfg=source):
                    if ok:
                        if path.lower().endswith(('.zip', '.7z')):
                            self.log(f"📦 Extracting {e_name}...")
                            from src.ui.threads import ExtractionThread
                            et = ExtractionThread(path, e_dir)
                            
                            def on_extracted(success, msg=None, e_data=e_data, e_name=e_name, e_dir=e_dir, p=path, s_cfg=s_cfg):
                                if success:
                                    try: os.remove(p)
                                    except: pass
                                    finalize_emu(e_data, e_name, e_dir, s_cfg)
                                else:
                                    self.log(f"❌ Extraction failed for {e_name}: {msg}")

                            et.finished.connect(lambda: on_extracted(True))
                            et.error.connect(lambda msg: on_extracted(False, msg))
                            self.active_threads.append(et)
                            et.start()
                        else:
                            finalize_emu(e_data, e_name, e_dir, s_cfg)
                    else:
                        self.log(f"❌ Failed to download {e_name}: {path}")
                    
                    self.download_queue.remove_download(thread)
                    if thread in self.active_threads: self.active_threads.remove(thread)

                def finalize_emu(e_data, e_name, e_dir, s_cfg):
                    # 1. Try exe_hint first
                    hint = s_cfg.get("exe_hint")
                    exe_path = None
                    if hint:
                        for p in Path(e_dir).rglob(hint):
                            exe_path = str(p)
                            break
                    
                    # 2. Fall back to largest .exe
                    if not exe_path:
                        max_size = -1
                        for p in Path(e_dir).rglob("*.exe"):
                            size = p.stat().st_size
                            if size > max_size:
                                    max_size = size
                                    exe_path = str(p)
                    
                    if exe_path:
                        e_data["executable_path"] = exe_path
                        emulators.save_emulators(all_emus)
                        self.log(f"✅ {e_name} downloaded and configured.")
                        self.emulators_tab.populate_emus()
                    else:
                        self.log(f"⚠ {e_name} downloaded, but no .exe found in {e_dir}")

                t.finished.connect(on_finished)
                self.active_threads.append(t)
                t.start()

            if source["type"] == "github":
                # Fetch assets from GitHub
                import requests
                repo = source["repo"]
                self.log(f"🔍 Fetching latest releases for {name}...")
                api_url = f"https://api.github.com/repos/{repo}/releases/latest"
                headers = {'User-Agent': 'WingosyLauncher'}
                verify = os.environ.get('REQUESTS_CA_BUNDLE', True)
                
                try:
                    resp = requests.get(api_url, timeout=15, headers=headers, verify=verify)
                    self.log(f"[Debug] GitHub API response: {resp.status_code} for {repo}")
                except Exception as ex:
                    self.log(f"❌ GitHub API request failed: {ex}")
                    return

                if resp.status_code != 200:
                    self.log(f"❌ Failed to fetch GitHub releases for {name}")
                    return
                
                assets = resp.json().get("assets", [])
                filters = source.get("asset_filters", {})
                req_k = filters.get("required", [])
                exc_k = filters.get("excluded", [])
                
                valid_assets = []
                for a in assets:
                    aname = a["name"].lower()
                    if not any(aname.endswith(ext) for ext in [".zip", ".7z"]): continue
                    if any(x in aname for x in exc_k): continue
                    if all(k in aname for k in req_k):
                        valid_assets.append(a)
                
                if not valid_assets:
                    self.log(f"❌ No suitable Windows assets found for {name}")
                    return
                
                if len(valid_assets) == 1:
                    start_download(valid_assets[0]["browser_download_url"], valid_assets[0]["name"])
                else:
                    self.picker = AssetPickerDialog(name, valid_assets, self)
                    self.picker.asset_selected.connect(lambda n, u: start_download(u, n))
                    self.picker.show()

            elif source["type"] == "direct":
                start_download(source["url"])

            elif source["type"] == "dolphin_api":
                # specialized downloader
                t = DolphinDownloader(str(target_dir))
                self.download_queue.add_download(f"Emulator: {name}", t)
                t.progress.connect(lambda d, t_bytes, s: self.log(f"DL {name}: {100*d/t_bytes if t_bytes > 0 else 0:.1f}% @ {format_speed(s)}"))
                
                def on_finished_dolphin(ok, path, e_data=emu, e_name=name, e_dir=target_dir, thread=t, s_cfg=source):
                    if ok:
                        if path.lower().endswith(('.zip', '.7z')):
                            self.log(f"📦 Extracting {e_name}...")
                            from src.ui.threads import ExtractionThread
                            et = ExtractionThread(path, e_dir)
                            
                            def on_extracted_dolphin(success, msg=None, e_data=e_data, e_name=e_name, e_dir=e_dir, p=path, s_cfg=s_cfg):
                                if success:
                                    try: os.remove(p)
                                    except: pass
                                    finalize_emu(e_data, e_name, e_dir, s_cfg)
                                else:
                                    self.log(f"❌ Extraction failed for {e_name}: {msg}")

                            et.finished.connect(lambda: on_extracted_dolphin(True))
                            et.error.connect(lambda msg: on_extracted_dolphin(False, msg))
                            self.active_threads.append(et)
                            et.start()
                        else:
                            finalize_emu(e_data, e_name, e_dir, s_cfg)
                    else:
                        self.log(f"❌ Failed to download {e_name}: {path}")
                    self.download_queue.remove_download(thread)
                    if thread in self.active_threads: self.active_threads.remove(thread)

                t.finished.connect(on_finished_dolphin)
                self.active_threads.append(t)
                t.start()

        except Exception as e:
            self.log(f"❌ Error starting emulator download: {e}")



    def st_ep(self, name):
        # This is now handled in EmulatorsTab.edit_emulator_path
        pass

    @Slot(str, str)
    def on_path(self, name, path):
        all_emus = emulators.load_emulators()
        updated = False
        for emu in all_emus:
            if name.lower() in emu['name'].lower():
                emu['executable_path'] = path
                updated = True
                break
        if updated:
            emulators.save_emulators(all_emus)
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
        try:
            dialog = ConflictDialog(title, self)
            if dialog.exec() == QDialog.Accepted:
                mode = dialog.result_mode
                # Only skip next pull if user explicitly chose to keep their local file
                if mode == "local":
                    print(f"[PULL DEBUG] User chose Keep Local. Setting skip_next_pull for {rom_id}")
                    self.watcher.skip_next_pull_rom_id = str(rom_id)
                else:
                    self.watcher.skip_next_pull_rom_id = None

                # Always clear it after 30 seconds max to prevent it sticking forever
                QTimer.singleShot(30000, lambda: setattr(
                    self.watcher, 'skip_next_pull_rom_id', None))

                if mode == "cloud":
                    t = ConflictResolveThread(self.watcher, rom_id, title, local_path, os.path.isdir(local_path))
                    t.finished.connect(lambda ok: self.log("✅ Cloud save applied." if ok else "❌ Cloud save apply failed."))
                    t.finished.connect(lambda t=t: self.active_threads.remove(t) if t in self.active_threads else None)
                    self.active_threads.append(t)
                    t.start()
                elif mode == "both":
                    cloud_bak = str(local_path) + ".cloud_backup"
                    if os.path.exists(cloud_bak):
                        if os.path.isdir(cloud_bak): shutil.rmtree(cloud_bak, ignore_errors=True)
                        else: os.remove(cloud_bak)
                    shutil.copy2(temp_dl, cloud_bak) if not os.path.isdir(temp_dl) else shutil.copytree(temp_dl, cloud_bak)
                    self.log(f"📁 Cloud save backed up to: {cloud_bak}")
            
            if os.path.exists(temp_dl):
                try: os.remove(temp_dl) if not os.path.isdir(temp_dl) else shutil.rmtree(temp_dl, ignore_errors=True)
                except: pass
        finally:
            if self.watcher:
                self.watcher._active_conflicts.discard(str(rom_id))

    @Slot(str, str)
    def show_notification(self, title, msg):
        self.tray_icon.showMessage(title, msg, QSystemTrayIcon.Information, 3000)

    def open_settings(self):
        self._on_tab_changed(3)

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
        # Stop watcher thread gracefully
        if hasattr(self, 'watcher') and self.watcher:
            self.watcher.running = False
            self.watcher.quit()
            self.watcher.wait(3000)  # wait up to 3 seconds
        
        # Stop library fetch worker if running
        if hasattr(self, '_fetch_thread') and self._fetch_thread.isRunning():
            self._fetch_thread.quit()
            self._fetch_thread.wait(2000)
        
        settings = QSettings("Wingosy", "WingosyLauncher")
        settings.setValue("geometry", self.saveGeometry())
        if self.tray_icon.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()

    def _apply_windows_frame(self):
        import sys
        if sys.platform != "win32":
            return
        try:
            import ctypes
            import ctypes.wintypes as wintypes
            
            hwnd = int(self.winId())
            
            # MARGINS struct — extend frame into client area on all sides by 1px
            # This removes title bar but keeps the resize border and snap behavior
            class MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth",    ctypes.c_int),
                    ("cxRightWidth",   ctypes.c_int),
                    ("cyTopHeight",    ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]
            
            margins = MARGINS(1, 1, 1, 1)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
                hwnd, ctypes.byref(margins))
            
            # Remove WS_CAPTION but keep WS_THICKFRAME for resize
            GWL_STYLE = -16
            WS_CAPTION     = 0x00C00000
            WS_THICKFRAME  = 0x00040000
            WS_SYSMENU     = 0x00080000
            WS_MAXIMIZEBOX = 0x00010000
            WS_MINIMIZEBOX = 0x00020000
            
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            # Remove caption, keep thick frame
            style = style & ~WS_CAPTION
            style = style | WS_THICKFRAME
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style)
            
            # Force Windows to redraw the frame
            SWP_FLAGS = (0x0020 |  # SWP_FRAMECHANGED
                         0x0002 |  # SWP_NOMOVE
                         0x0001 |  # SWP_NOSIZE
                         0x0004)   # SWP_NOZORDER
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_FLAGS)
                
        except Exception as e:
            logging.warning(f"[Frame] Windows frame setup failed: {e}")

    def _get_drag_rect(self):
        """Returns the screen rect of the draggable center area of the title bar."""
        try:
            tb = self.title_bar
            # Drag zone is between status_text and lib_btn
            left_widget = tb.status_text
            right_widget = tb.nav_buttons[0] if tb.nav_buttons else tb.settings_btn
            
            left_x = left_widget.mapToGlobal(left_widget.rect().bottomRight()).x()
            right_x = right_widget.mapToGlobal(right_widget.rect().bottomLeft()).x()
            
            top_y = tb.mapToGlobal(tb.rect().topLeft()).y()
            bot_y = tb.mapToGlobal(tb.rect().bottomLeft()).y()
            
            return left_x, right_x, top_y, bot_y
        except Exception:
            return None

    def nativeEvent(self, eventType, message):
        import sys
        if sys.platform != "win32":
            return super().nativeEvent(eventType, message)

        import ctypes
        import ctypes.wintypes as wintypes

        if eventType != b"windows_generic_MSG":
            return super().nativeEvent(eventType, message)

        msg = ctypes.wintypes.MSG.from_address(int(message))

        WM_NCCALCSIZE    = 0x0083
        WM_NCHITTEST     = 0x0084
        WM_GETMINMAXINFO = 0x0024

        if msg.message == WM_GETMINMAXINFO:
            # Constrain the maximized window to the work area so it never covers the taskbar
            try:
                hwnd = int(self.winId())
                MONITOR_DEFAULTTONEAREST = 2
                monitor = ctypes.windll.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)

                class _RECT(ctypes.Structure):
                    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                 ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

                class _MONITORINFO(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                                 ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]

                mi = _MONITORINFO()
                mi.cbSize = ctypes.sizeof(mi)
                ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(mi))

                class _POINT(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

                class _MINMAXINFO(ctypes.Structure):
                    _fields_ = [("ptReserved", _POINT), ("ptMaxSize", _POINT),
                                 ("ptMaxPosition", _POINT), ("ptMinTrackSize", _POINT),
                                 ("ptMaxTrackSize", _POINT)]

                mmi = _MINMAXINFO.from_address(msg.lParam)
                w = mi.rcWork.right - mi.rcWork.left
                h = mi.rcWork.bottom - mi.rcWork.top
                mmi.ptMaxSize.x = w
                mmi.ptMaxSize.y = h
                mmi.ptMaxPosition.x = mi.rcWork.left
                mmi.ptMaxPosition.y = mi.rcWork.top
                mmi.ptMaxTrackSize.x = w
                mmi.ptMaxTrackSize.y = h
                return True, 0
            except Exception:
                pass

        if msg.message == WM_NCCALCSIZE:
            if msg.wParam == 1:
                return True, 0
            return False, 0
        
        if msg.message == WM_NCHITTEST:
            # Screen coordinates from lParam
            x = ctypes.c_int16(msg.lParam & 0xFFFF).value
            y = ctypes.c_int16((msg.lParam >> 16) & 0xFFFF).value
            
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(int(self.winId()), ctypes.byref(rect))
            
            # Use device pixels for border — fall back to Qt's ratio if Win API unavailable
            try:
                dpi = ctypes.windll.user32.GetDpiForWindow(int(self.winId()))
                scale = dpi / 96.0
            except Exception:
                scale = self.devicePixelRatioF()
            
            b = max(4, int(8 * scale))
            
            # Clamp to window bounds first
            if (x < rect.left or x > rect.right or y < rect.top or y > rect.bottom):
                return False, 0
            
            dist_left   = x - rect.left
            dist_right  = rect.right  - x
            dist_top    = y - rect.top
            dist_bottom = rect.bottom - y
            
            if not self.isMaximized():
                on_left   = dist_left   <= b
                on_right  = dist_right  <= b
                on_top    = dist_top    <= b
                on_bottom = dist_bottom <= b
                
                HTTOPLEFT     = 13
                HTTOPRIGHT    = 14
                HTBOTTOMLEFT  = 16
                HTBOTTOMRIGHT = 17
                HTTOP         = 12
                HTBOTTOM      = 15
                HTLEFT        = 10
                HTRIGHT       = 11
                
                if on_top and on_left: return True, HTTOPLEFT
                if on_top and on_right: return True, HTTOPRIGHT
                if on_bottom and on_left: return True, HTBOTTOMLEFT
                if on_bottom and on_right: return True, HTBOTTOMRIGHT
                if on_top: return True, HTTOP
                if on_bottom: return True, HTBOTTOM
                if on_left: return True, HTLEFT
                if on_right: return True, HTRIGHT
            
            # Title bar area hit testing
            title_height = int(40 * scale)
            if dist_top <= title_height:
                drag_rect = self._get_drag_rect()
                if drag_rect:
                    left_x, right_x, top_y, bot_y = drag_rect
                    if left_x <= x <= right_x and top_y <= y <= bot_y:
                        return True, 2 # HTCAPTION
                else:
                    # Fallback
                    if (x - rect.left) < (rect.right - rect.left) * 0.4:
                        return True, 2 # HTCAPTION
                
                return True, 1 # HTCLIENT
            
            return True, 1 # HTCLIENT
        
        return super().nativeEvent(eventType, message)
