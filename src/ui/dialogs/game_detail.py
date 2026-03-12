import os
import shutil
import subprocess
import logging
import zipfile
from pathlib import Path
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox, QProgressBar, QScrollArea, QFileDialog, QApplication)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QPoint
from PySide6.QtGui import QPixmap

from src.ui.threads import (RomDownloader, ImageFetcher, ConflictResolveThread, GameDescriptionFetcher, ExtractionThread)
from src.ui.widgets import format_size, get_resource_path, format_speed
from src.platforms import RETROARCH_CORES
from src import emulators, windows_saves, download_registry
from src.save_strategies import get_strategy
from src.utils import read_retroarch_cfg, write_retroarch_cfg_values, extract_strip_root, resolve_local_rom_path

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
    global _retroarch_autosave_checked
    if _retroarch_autosave_checked:
        return
    _retroarch_autosave_checked = True
    
    if platform_slug in ("psp", "playstation-portable"):
        return
        
    save_mode = config.get("retroarch_save_mode", "srm") if config else "srm"
    if save_mode == "srm":
        return
        
    cfg_path = Path(ra_exe_path).parent / "retroarch.cfg"
    if not cfg_path.exists():
        return
        
    cfg = read_retroarch_cfg(str(cfg_path))
    auto_save = cfg.get("savestate_auto_save", "false")
    auto_load = cfg.get("savestate_auto_load", "false")
    
    if auto_save == "true" and auto_load == "true":
        return
        
    missing = []
    if auto_save != "true": missing.append("savestate_auto_save")
    if auto_load != "true": missing.append("savestate_auto_load")
    
    result = QMessageBox.question(
        parent, 
        "RetroArch Auto-Save States — Wingosy", 
        f"Enable auto save/load states in retroarch.cfg?\n\nMissing: {', '.join(missing)}", 
        QMessageBox.Yes | QMessageBox.No
    )
    
    if result == QMessageBox.Yes:
        write_retroarch_cfg_values(str(cfg_path), {"savestate_auto_save": "true", "savestate_auto_load": "true"})
        QMessageBox.information(parent, "RetroArch Auto-Save States — Wingosy", "✅ Auto save/load states enabled.")

def check_ppsspp_assets(ra_exe_path, parent):
    global _ppsspp_assets_checked
    if _ppsspp_assets_checked:
        return
    _ppsspp_assets_checked = True
    
    system_ppsspp = Path(ra_exe_path).parent / "system" / "PPSSPP"
    if (system_ppsspp / "ppge_atlas.zim").exists():
        return
        
    result = QMessageBox.question(
        parent, 
        "PPSSPP Assets Missing — Wingosy", 
        "Download missing PPSSPP assets now?", 
        QMessageBox.Yes | QMessageBox.No
    )
    
    if result != QMessageBox.Yes:
        return
        
    progress = QMessageBox(parent)
    progress.setWindowTitle("Downloading PPSSPP Assets — Wingosy")
    progress.setText("Downloading...")
    progress.show()
    QApplication.processEvents()
    
    try:
        import urllib.request, tempfile
        url = "https://buildbot.libretro.com/assets/system/PPSSPP.zip"
        system_ppsspp.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name
        
        urllib.request.urlretrieve(url, tmp_path)
        with zipfile.ZipFile(tmp_path, 'r') as z:
            for member in z.namelist():
                rel = member[len("PPSSPP/"):] if member.startswith("PPSSPP/") else member
                if not rel: continue
                target = system_ppsspp / rel
                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as src, open(target, 'wb') as dst:
                        dst.write(src.read())
        
        Path(tmp_path).unlink(missing_ok=True)
        progress.close()
        QMessageBox.information(parent, "PPSSPP Assets Ready — Wingosy", "✅ Done.")
    except Exception as e:
        progress.close()
        QMessageBox.warning(parent, "Download Failed — Wingosy", str(e))

class GameDetailPanel(QWidget):
    def __init__(self, game, client, config, main_window, on_close=None, parent=None):
        super().__init__(parent)
        self._on_close = on_close
        self.game = game
        self.client = client
        self.config = config
        self.main_window = main_window
        
        self.dl_thread = None
        self.extract_thread = None
        self._is_windows = game.get("platform_slug") in WINDOWS_PLATFORM_SLUGS
        self._local_rom_path = self._get_local_rom_path()

        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QPushButton {
                border-radius: 4px;
            }
            QScrollArea {
                background: transparent;
                border: none;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header
        main_layout.addWidget(self._build_header(game.get('name', '')))

        # Content area
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)
        content_layout.setSpacing(10)

        title_label = QLabel(game.get('name'))
        title_label.setStyleSheet("font-size: 20pt; font-weight: bold; color: #1e88e5; background: transparent;")
        title_label.setWordWrap(True)
        content_layout.addWidget(title_label)

        sub_layout = QHBoxLayout()
        sub_layout.setSpacing(25)

        self.img_label = QLabel()
        self.img_label.setFixedWidth(280)
        self.img_label.setStyleSheet("background: #111; border-radius: 6px;")
        sub_layout.addWidget(self.img_label)

        self.right_column = QVBoxLayout()
        self.right_column.setSpacing(0)

        self.right_column.addWidget(QLabel(f"<b>Platform:</b> {game.get('platform_display_name')}", styleSheet="font-size: 12pt; margin-bottom: 2px; background: transparent;"))

        total_bytes = sum(f.get('file_size_bytes', 0) for f in game.get('files', []))
        self.right_column.addWidget(QLabel(f"<b>Size:</b> {format_size(total_bytes)}", styleSheet="font-size: 12pt; margin-bottom: 8px; background: transparent;"))

        self.desc_scroll = QScrollArea()
        self.desc_scroll.setWidgetResizable(True)
        self.desc_scroll.setStyleSheet("background: transparent; border: none;")

        self.desc_label = QLabel("Loading description...")
        self.desc_label.setWordWrap(True)
        self.desc_label.setAlignment(Qt.AlignTop)
        self.desc_label.setStyleSheet("color: #ccc; font-size: 11pt; line-height: 1.4; background: transparent;")
        self.desc_scroll.setWidget(self.desc_label)
        self.right_column.addWidget(self.desc_scroll, 1)

        self.pbar = QProgressBar()
        self.pbar.setVisible(False)
        self.pbar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 3px;
                background: #2d2d2d;
                height: 8px;
            }
            QProgressBar::chunk {
                border-radius: 3px;
                background: #0d6efd;
            }
        """)
        self.right_column.addWidget(self.pbar)

        self.speed_label = QLabel()
        self.speed_label.setAlignment(Qt.AlignCenter)
        self.speed_label.setStyleSheet("background: transparent;")
        self.right_column.addWidget(self.speed_label)

        self.actions_layout = QVBoxLayout()
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(4)

        self.play_btn = QPushButton("▶ PLAY")
        self.play_btn.setStyleSheet("background: #2e7d32; color: white; font-weight: bold; padding: 12px; font-size: 16pt;")
        self.play_btn.clicked.connect(self.play_game)

        self.gs_btn = QPushButton("⚙ Game Settings")
        self.gs_btn.setStyleSheet("background: #455a64; color: white; padding: 8px; font-size: 11pt;")
        self.gs_btn.clicked.connect(self.open_game_settings)

        self.un_btn = QPushButton("🗑 Uninstall")
        self.un_btn.setStyleSheet("background: #8e0000; color: white; padding: 8px; font-size: 13pt;")
        self.un_btn.clicked.connect(self.uninstall_game)

        self.cloud_btn = QPushButton("☁️ Cloud Saves")
        self.cloud_btn.setStyleSheet("background: #0d47a1; color: white; padding: 8px; font-size: 11pt;")
        self.cloud_btn.clicked.connect(self.open_cloud_manager)

        self.dl_btn = QPushButton("⬇ DOWNLOAD")
        self.dl_btn.setStyleSheet("background: #1565c0; color: white; font-weight: bold; padding: 12px; font-size: 16pt;")
        self.dl_btn.clicked.connect(self._on_download_clicked)

        self.can_btn = QPushButton("Cancel Download")
        self.can_btn.setStyleSheet("background: #c62828; color: white; font-size: 12pt;")
        self.can_btn.setVisible(False)
        self.can_btn.clicked.connect(self.cancel_dl)

        self.actions_layout.addWidget(self.play_btn)
        self.actions_layout.addWidget(self.gs_btn)
        self.actions_layout.addWidget(self.un_btn)
        self.actions_layout.addWidget(self.dl_btn)
        self.actions_layout.addWidget(self.can_btn)

        self.right_column.addLayout(self.actions_layout)
        sub_layout.addLayout(self.right_column, 1)
        content_layout.addLayout(sub_layout)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("background: #333; color: #ccc; padding: 10px; font-size: 16pt;")
        close_btn.clicked.connect(self._close)
        content_layout.addWidget(close_btn)

        main_layout.addWidget(content, 1)

        # After building the UI, check registry
        self._reconnect_active_download()
            
        self._start_image_fetch()
        self._start_desc_fetch()

    def _build_header(self, game_name):
        header = QWidget()
        header.setFixedHeight(44)
        header.setStyleSheet("background: #111; border-bottom: 1px solid #222;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 0, 12, 0)
        
        back_btn = QPushButton("← Back to Library")
        back_btn.setFixedWidth(180)
        back_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #888;
                border: none;
                font-size: 14px;
                padding: 6px 10px;
                text-align: left;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        back_btn.clicked.connect(self._close)
        hl.addWidget(back_btn)
        hl.addStretch()
        return header

    def _close(self):
        if self._on_close:
            self._on_close()

    def _reconnect_active_download(self):
        rom_id = str(self.game["id"])
        entry = download_registry.get(rom_id)
        
        if not entry:
            self._update_button_states()
            return
        
        # Active download or extraction found!
        row_type = entry["type"]
        current, total = entry["progress"]
        
        self.play_btn.hide()
        self.dl_btn.hide()
        self.un_btn.hide()
        
        self.pbar.setVisible(True)
        if total > 0:
            self.pbar.setRange(0, 100)
            self.pbar.setValue(int(current / total * 100))
        else:
            self.pbar.setRange(0, 0)
        
        if row_type == "download":
            self.speed_label.setText("Downloading...")
        else:
            self.speed_label.setText("Extracting...")
        
        self.can_btn.show()
        
        self._progress_listener = self._on_registry_progress
        download_registry.add_listener(rom_id, self._progress_listener)

    def _on_registry_progress(self, rom_id, rtype, current, total, speed=0):
        if rtype == "done" or rtype == "cancelled":
            download_registry.remove_listener(rom_id, self._progress_listener)
            self.pbar.setVisible(False)
            self.can_btn.hide()
            self.speed_label.setText("")
            self._update_button_states()
            return
        
        if total > 0:
            self.pbar.setRange(0, 100)
            self.pbar.setValue(int(current / total * 100))
        else:
            self.pbar.setRange(0, 0)
        
        if rtype == "download":
            self.speed_label.setText(f"Downloading... {format_size(current)} / {format_size(total)}")
        elif rtype == "extraction":
            if total > 0:
                self.speed_label.setText(f"Extracting... {current}/{total} files")
            else:
                self.speed_label.setText("Extracting...")

    def download_rom(self, file_obj):
        if not file_obj: return
        
        # Determine target path
        if self._is_windows:
            target_dir = Path(self.config.get("windows_games_dir"))
            target_path = target_dir / file_obj['file_name']
        else:
            target_dir = Path(self.config.get("base_rom_path")) / self.game.get('platform_slug')
            target_path = target_dir / file_obj['file_name']
            
        os.makedirs(target_dir, exist_ok=True)
        
        self.dl_thread = RomDownloader(self.client, self.game['id'], file_obj['file_name'], str(target_path))
        download_registry.register_download(self.game['id'], self.game['name'], self.dl_thread)
        
        self.dl_thread.progress.connect(lambda d, t, s: download_registry.update_progress(self.game['id'], d, t, s))
        self.dl_thread.finished.connect(lambda ok, p: self._on_download_finished(ok, p))
        
        self.main_window.download_queue.add_download(self.game['name'], self.dl_thread, "download", self.game['id'])
        self.dl_thread.start()
        self._reconnect_active_download()

    def _on_download_finished(self, ok, path):
        if not ok:
            download_registry.unregister(self.game['id'])
            return
            
        # If it's an archive and we are on Windows, or just need extraction
        if path.endswith(('.zip', '.7z', '.iso')):
            # Pre-fetch 7z.exe in background so extraction starts immediately
            from src.sevenzip import get_7zip_exe
            from PySide6.QtCore import QThread
            
            class SevenZipFetcher(QThread):
                ready = Signal(str)
                def run(self):
                    exe = get_7zip_exe()
                    self.ready.emit(exe or "")
            
            self.speed_label.setText("Preparing extractor...")
            self._sz_fetcher = SevenZipFetcher()
            self._sz_fetcher.ready.connect(lambda exe: self._start_extraction(path))
            self._sz_fetcher.start()
        else:
            download_registry.unregister(self.game['id'])
            self._update_button_states()

    def _on_extraction_finished(self, path):
        download_registry.unregister(self.game['id'])
        self._update_button_states()
        self.main_window.fetch_library_and_populate()

    def cancel_dl(self):
        rom_id = str(self.game["id"])
        entry = download_registry.get(rom_id)
        if not entry or not entry.get("thread"):
            return

        rom_name = self.game.get('name', 'this game')
        if entry["type"] == "extraction":
            reply = QMessageBox.question(
                self, "Cancel Extraction — Wingosy",
                f"Cancel extracting {rom_name}?\n\nWhat should happen to the files extracted so far?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Cancel
            )
            if reply == QMessageBox.Cancel: return
            
            entry["thread"].cancel()
            if reply == QMessageBox.Discard:
                def on_cancelled(path):
                    import shutil
                    shutil.rmtree(path, ignore_errors=True)
                entry["thread"].cancelled.connect(on_cancelled)
        else:
            reply = QMessageBox.question(
                self, "Cancel Download — Wingosy",
                f"Cancel downloading {rom_name}?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Cancel
            )
            if reply == QMessageBox.Cancel: return
            
            entry["thread"].cancel()
            if reply == QMessageBox.Discard:
                def on_cancelled_dl():
                    p = getattr(entry["thread"], 'file_path', None)
                    if p and os.path.exists(p):
                        try: os.remove(p)
                        except: pass
                entry["thread"].cancelled.connect(on_cancelled_dl)

        download_registry.update_status(rom_id, "cancelled")
        QTimer.singleShot(1000, lambda: download_registry.unregister(rom_id))
        self.can_btn.hide()
        self.pbar.hide()
        self._update_button_states()

    def _get_local_rom_path(self):
        return resolve_local_rom_path(self.game, self.config.data)
        
    def _update_button_states(self):
        self._local_rom_path = self._get_local_rom_path()
        p = self._local_rom_path
        
        if self._is_windows and p and p.is_dir():
            exists = any(p.rglob("*.exe"))
        else:
            exists = p and p.exists() if p else False
                
        self.play_btn.setVisible(bool(exists))
        self.gs_btn.setVisible(bool(exists) and self._is_windows)
        self.un_btn.setVisible(bool(exists))
        self.dl_btn.setVisible(not bool(exists))
        self.dl_btn.setText("⬇ DOWNLOAD")
        self.dl_btn.setStyleSheet("background: #1565c0; color: white; font-weight: bold; padding: 10px; font-size: 13pt;")
        
    def open_game_settings(self):
        from src.ui.dialogs.windows_settings import WindowsGameSettingsDialog
        dlg = WindowsGameSettingsDialog(self.game, self.config, self.main_window, self)
        dlg.show()
        # Keep reference
        self._child_dlg = dlg

    def open_cloud_manager(self):
        from src.ui.dialogs.save_sync import CloudSaveManagerDialog
        dlg = CloudSaveManagerDialog(self.game, self.client, self.config, self.main_window, self)
        dlg.show()
        # Keep reference
        self._child_dlg = dlg
            
    def _start_image_fetch(self):
        url = self.client.get_cover_url(self.game)
        if url:
            self.it = ImageFetcher(self.game['id'], url)
            self.it.finished.connect(lambda g, p: self.img_label.setPixmap(p.scaled(280, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            self.it.finished.connect(lambda t=self.it: self.main_window.active_threads.remove(t) if t in self.main_window.active_threads else None)
            self.main_window.active_threads.append(self.it)
            self.it.start()
            
    def _start_desc_fetch(self):
        self.dt = GameDescriptionFetcher(self.client, self.game['id'])
        self.dt.finished.connect(self.desc_label.setText)
        self.dt.finished.connect(lambda t=self.dt: self.main_window.active_threads.remove(t) if t in self.main_window.active_threads else None)
        self.main_window.active_threads.append(self.dt)
        self.dt.start()
        
    def uninstall_game(self):
        msg = f"Are you sure you want to delete {self.game.get('name')}?"
        if self._is_windows:
            msg = f"Permanently delete ALL files in:\n{self._local_rom_path}?"
            
        if QMessageBox.question(self, "Uninstall — Wingosy", msg, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try:
                p = self._local_rom_path
                if p.exists():
                    if p.is_dir():
                        shutil.rmtree(p)
                    else:
                        os.remove(p)
                    self.main_window.log(f"🗑 {self.game.get('name')} uninstalled")
                    self._update_button_states()
                    self.main_window.library_tab.apply_filters()
            except Exception as e:
                QMessageBox.critical(self, "Error — Wingosy", str(e))
                
    def _on_download_clicked(self):
        windows_dir = self.config.get("windows_games_dir", "")
        if self._is_windows and not windows_dir:
            directory = QFileDialog.getExistingDirectory(self, "Select Windows Games Folder")
            if directory:
                self.config.set("windows_games_dir", directory)
                windows_dir = directory
            else:
                return

        files = self.game.get('files', [])
        if not files:
            return

        file_obj = files[0]
        rom_name = file_obj.get("file_name", "")

        # Windows-specific pre-download checks
        if self._is_windows and windows_dir:
            archive_path = Path(windows_dir) / rom_name
            extracted_dir = Path(windows_dir) / Path(rom_name).stem

            # 1. Check if already installed
            if extracted_dir.exists() and any(extracted_dir.rglob("*.exe")):
                QMessageBox.information(
                    self, "Already Installed — Wingosy",
                    f"{self.game['name']} appears to already be installed at:\n{extracted_dir}\n\nUse the Play button to launch it."
                )
                self._update_button_states()
                return

            # 2. Check if archive exists
            if archive_path.exists():
                reply = QMessageBox.question(
                    self, "Archive Already Downloaded — Wingosy",
                    f"{rom_name} already exists in your Windows Games folder.\n\nWould you like to extract it now instead of downloading again?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                    QMessageBox.Yes
                )
                if reply == QMessageBox.Cancel:
                    return
                if reply == QMessageBox.Yes:
                    self._start_extraction(str(archive_path))
                    return

        self.download_rom(file_obj)

    def _start_extraction(self, path):
        target_dir = Path(path).parent
        if self._is_windows:
            target_dir = target_dir / Path(path).stem

        self.extract_thread = ExtractionThread(path, str(target_dir))
        download_registry.register_extraction(self.game['id'], self.game['name'], self.extract_thread)

        self.extract_thread.progress.connect(lambda d, t: download_registry.update_progress(self.game['id'], d, t))
        self.extract_thread.finished.connect(self._on_extraction_finished)

        self.main_window.download_queue.add_download(self.game['name'], self.extract_thread, "extraction", self.game['id'])
        self.extract_thread.start()
        self._reconnect_active_download()

    def _do_blocking_pull(self, rom, emulator):
        """Pull latest save from RomM before launching. Returns False to abort launch."""
        try:
            if not self.config.get("auto_pull_saves", True):
                return True

            strategy = get_strategy(self.config, emulator)
            save_dir = strategy.get_save_dir(rom)

            latest = self.client.get_latest_save(rom['id'])
            if not latest:
                return True

            is_folder = (strategy.mode_id in ["folder", "windows"])
            local_path = str(save_dir) if save_dir else (
                str(strategy.get_save_files(rom)[0]) if strategy.get_save_files(rom) else None
            )

            if not local_path:
                return True

            # Check if a conflict will be triggered: local exists + hashes differ
            import zipfile
            from src.utils import calculate_zip_content_hash, calculate_file_hash, calculate_folder_hash
            import tempfile

            watcher = self.main_window.watcher
            server_updated_at = latest.get('updated_at', '')
            cached_val = watcher.sync_cache.get(str(rom['id']), {})
            cached_ts = cached_val.get('save_updated_at', '') if isinstance(cached_val, dict) else ""

            # If cache matches server, no conflict possible
            if cached_ts == server_updated_at and os.path.exists(local_path):
                return True

            local_exists = os.path.isdir(local_path) if is_folder else os.path.exists(local_path)
            if not local_exists:
                # No local save — safe to pull normally
                return self._apply_save_blocking(
                    rom['id'], rom['name'], latest, local_path, "save", is_folder
                ) is not False

            # Local exists — download cloud save to temp and compare hashes
            tmp = tempfile.mktemp(suffix=".save")
            if not watcher.client.download_save(latest, tmp):
                return True

            try:
                remote_h = calculate_zip_content_hash(tmp) if zipfile.is_zipfile(tmp) else calculate_file_hash(tmp)
                local_h = calculate_folder_hash(local_path) if is_folder else calculate_file_hash(local_path)

                if remote_h == local_h:
                    # Identical — update cache and proceed
                    watcher.sync_cache[str(rom['id'])] = {"save_updated_at": server_updated_at}
                    watcher.save_cache()
                    return True

                # Hashes differ — show conflict dialog and BLOCK launch until resolved
                from src.ui.dialogs.save_sync import ConflictDialog
                from PySide6.QtCore import QEventLoop

                result = {"choice": None}
                loop = QEventLoop()

                def on_conflict_resolved(choice):
                    result["choice"] = choice
                    loop.quit()

                dlg = ConflictDialog(rom['name'], self)
                dlg.choice_made.connect(on_conflict_resolved)
                dlg.show()
                loop.exec()  # Block here until user picks

                choice = result["choice"]
                if choice == "cloud":
                    return self._apply_save_blocking(
                        rom['id'], rom['name'], latest, local_path, "save", is_folder
                    ) is not False
                elif choice == "local":
                    return True  # Keep local, proceed to launch
                elif choice == "both":
                    # Backup cloud to .cloud_backup then proceed with local
                    cloud_bak = str(local_path) + ".cloud_backup"
                    if os.path.exists(cloud_bak):
                        if os.path.isdir(cloud_bak): shutil.rmtree(cloud_bak, ignore_errors=True)
                        else: os.remove(cloud_bak)
                    shutil.copy2(tmp, cloud_bak) if not os.path.isdir(tmp) else shutil.copytree(tmp, cloud_bak)
                    self.main_window.log(f"📁 Cloud save backed up to: {cloud_bak}")
                    return True
                else:
                    return False  # User closed dialog — abort launch
            finally:
                if os.path.exists(tmp):
                    try: os.remove(tmp) if not os.path.isdir(tmp) else shutil.rmtree(tmp, ignore_errors=True)
                    except: pass

        except Exception as e:
            logging.warning(f"[Sync] Pull failed: {e}")
            return True

    def _apply_save_blocking(self, rom_id, title, obj, local_path, file_type, is_folder=False):
        import tempfile
        watcher = self.main_window.watcher
        server_updated_at = obj.get('updated_at', '')
        local_exists = os.path.isdir(local_path) if is_folder else os.path.exists(local_path)
        
        cached_entry = watcher.sync_cache.get(str(rom_id), {})
        if isinstance(cached_entry, dict):
            cached_ts = cached_entry.get(f'{file_type}_updated_at', '')
        else:
            cached_ts = cached_entry if file_type == 'save' else ''
            
        if cached_ts == server_updated_at and local_exists:
            return True
            
        tmp = tempfile.mktemp(suffix=f".{file_type}")
        success = watcher.client.download_state(obj, tmp) if file_type == "state" else watcher.client.download_save(obj, tmp)
        if not success:
            return True
            
        dest = Path(local_path)
        if is_folder:
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            
        if dest.exists():
            bak = Path(str(dest) + ".bak")
            try:
                if is_folder:
                    shutil.copytree(str(dest), str(bak), dirs_exist_ok=True)
                else:
                    shutil.copy2(str(dest), str(bak))
            except:
                pass
                
        try:
            if is_folder or (zipfile.is_zipfile(tmp) and not local_path.endswith(('.srm', '.state'))):
                extract_strip_root(tmp, local_path)
            else:
                shutil.copy2(tmp, str(dest))
                if file_type == "state" and dest.suffix == '.state' and not dest.name.endswith('.state.auto'):
                    auto_path = dest.with_name(dest.name + '.auto')
                    if auto_path.exists():
                        if auto_path.is_dir(): shutil.rmtree(auto_path)
                        else: auto_path.unlink()
                    dest.rename(auto_path)
                    
            if not isinstance(watcher.sync_cache.get(str(rom_id)), dict):
                watcher.sync_cache[str(rom_id)] = {}
            watcher.sync_cache[str(rom_id)][f'{file_type}_updated_at'] = server_updated_at
            watcher.save_cache()
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return True

    def play_game(self):
        local_rom = self._get_local_rom_path()
        if not local_rom or not local_rom.exists():
            QMessageBox.warning(self, "Error — Wingosy", "Could not find the local ROM file. Please download it first.")
            return
            
        emu_data = None
        platform = self.game.get('platform_slug')
        all_emus = emulators.load_emulators()
        
        assigned_id = self.config.get("platform_assignments", {}).get(platform)
        if assigned_id:
            emu_data = next((e for e in all_emus if e["id"] == assigned_id), None)
            
        if not emu_data:
            emu_data = emulators.get_emulator_for_platform(platform)
            
        if not emu_data:
            emu_data = next((e for e in all_emus if e["id"] == "retroarch"), None)
            
        if not emu_data or (not emu_data.get("is_native") and (not emu_data.get("executable_path") or not os.path.exists(emu_data["executable_path"]))):
            QMessageBox.warning(self, "Error — Wingosy", "No valid emulator configured.")
            return
            
        self.main_window.log(f"🎮 Preparing {self.game.get('name')}...")
        self.main_window.ensure_watcher_running()
        
        # 1. Sync Before Play
        if self.config.get("auto_pull_saves", True):
            if not self._do_blocking_pull(self.game, emu_data):
                return

        # 2. Launch
        try:
            exe_path = emu_data.get("executable_path")
            
            if emu_data.get("is_native"):
                saved = windows_saves.get_windows_save(self.game['id'])
                exe_to_launch = saved.get("default_exe") if saved else None
                if not exe_to_launch:
                    # Fallback to auto-detect logic
                    rom = self.game.get('fs_name')
                    win_dir = self.config.get("windows_games_dir")
                    if rom and win_dir:
                        folder = Path(win_dir) / Path(rom).stem
                        if folder.exists():
                            exes = [str(p) for p in folder.rglob("*.exe") if not any(ex_name.lower() in str(p).lower() for ex_name in EXCLUDED_EXES)]
                            if len(exes) == 1:
                                exe_to_launch = exes[0]
                            elif len(exes) > 1:
                                from src.ui.dialogs.emulator_editor import ExePickerDialog
                                picker = ExePickerDialog(exes, self.game.get("name"), self)
                                picker.exe_selected.connect(self._launch_windows_exe)
                                picker.show()
                                # Keep reference
                                self._child_dlg = picker
                                return # Launching happens after picking
                
                if not exe_to_launch:
                    QMessageBox.warning(self, "Error — Wingosy", "No game executable found.")
                    return

                self._launch_windows_exe(exe_to_launch)
                return

            if emu_data["id"] == "retroarch":
                check_retroarch_autosave(exe_path, platform, self, self.config)
                from src.platforms import RETROARCH_CORES
                core_name = RETROARCH_CORES.get(platform)
                if core_name:
                    core_path = Path(exe_path).parent / "cores" / core_name
                    if core_path.exists():
                        args = [exe_path, "-L", str(core_path), str(local_rom)]
                    else:
                        if QMessageBox.question(self, "Error — Wingosy", f"Core {core_name} missing. Download?") == QMessageBox.Yes:
                            self.start_core_download(core_name, Path(exe_path).parent, platform)
                        return
                else:
                    args = [exe_path, str(local_rom)]
            else:
                raw_args = emu_data.get("launch_args", ["{rom_path}"])
                args = [exe_path]
                for a in raw_args:
                    if a.replace("{rom_path}", str(local_rom)) != exe_path:
                        args.append(a.replace("{rom_path}", str(local_rom)))
            
            clean_env = os.environ.copy()
            for k in ["QT_QPA_PLATFORM_PLUGIN_PATH", "QT_PLUGIN_PATH", "QT_QPA_FONTDIR", "QT_QPA_PLATFORM", "QT_STYLE_OVERRIDE"]:
                clean_env.pop(k, None)
                
            proc = subprocess.Popen(args, env=clean_env, cwd=str(Path(exe_path).parent))
            self.main_window.log(f"🚀 Launched {emu_data['name']} (PID: {proc.pid})")
            if self.main_window.watcher:
                QTimer.singleShot(0, lambda: self.main_window.watcher.track_session(proc, emu_data["name"], self.game, str(local_rom), exe_path, skip_pull=True))
            self._close()
        except Exception as e:
            QMessageBox.critical(self, "Error — Wingosy", str(e))

    def _launch_windows_exe(self, exe_path):
        self.main_window.log(f"🚀 Launching Windows Game: {os.path.basename(exe_path)}")
        proc = subprocess.Popen([exe_path], cwd=os.path.dirname(exe_path))
        self._close()
        if self.main_window.watcher:
            self.main_window.watcher.track_session(proc, "Windows", self.game, exe_path, exe_path, skip_pull=True)

            
    def start_core_download(self, core_name, emu_dir, platform):
        from src.ui.threads import CoreDownloadThread
        dlg = QDialog(self) # Still modal for core DL
        dlg.setWindowTitle(f"Downloading {core_name} — Wingosy")
        dlg.setFixedSize(350, 100)
        l = QVBoxLayout(dlg)
        status = QLabel(f"Downloading for {platform}...")
        pb = QProgressBar()
        l.addWidget(status)
        l.addWidget(pb)
        dlg.setWindowModality(Qt.ApplicationModal)
        
        t = CoreDownloadThread(core_name, emu_dir / "cores")
        t.progress.connect(lambda v, s: (pb.setValue(v), status.setText(f"Speed: {format_speed(s)}")))
        t.finished.connect(lambda success, msg: (dlg.close(), self.play_game() if success else QMessageBox.critical(self, "Error — Wingosy", msg)))
        t.start()
        dlg.exec()

GameDetailDialog = GameDetailPanel
