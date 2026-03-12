import os
from pathlib import Path
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QMessageBox, QScrollArea, QFileDialog, QFrame)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QFontMetrics

class ConflictDialog(QDialog):
    choice_made = Signal(str)

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Save Conflict — {title} — Wingosy")
        self.setFixedSize(450, 200)
        self.result_mode = None

        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowTitleHint)
        
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
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        layout.addWidget(QLabel(f"Conflict found for <b>{title}</b>. Which save would you like to use?"))
        layout.addStretch()
        
        btn_layout = QHBoxLayout()

        for mode, text in [("cloud", "☁️ Use Cloud"), ("local", "💾 Keep Local"), ("both", "📁 Keep Both")]:
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked, m=mode: self.finish(m))
            btn_layout.addWidget(btn)
            
        layout.addLayout(btn_layout)
        
        QTimer.singleShot(0, self._apply_dark_frame)
        QTimer.singleShot(50, self._center_on_parent)

    def _apply_dark_frame(self):
        import sys, ctypes
        if sys.platform == "win32":
            try: ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 20, ctypes.byref(ctypes.c_int(1)), 4)
            except: pass

    def _center_on_parent(self):
        p = self.parent()
        if not p: return
        pg = p.geometry()
        x = pg.x() + (pg.width() - self.width()) // 2
        y = pg.y() + (pg.height() - self.height()) // 2
        self.move(x, y)
        
    def finish(self, mode):
        self.result_mode = mode
        self.choice_made.emit(mode)
        self.accept()

class WikiSuggestionsDialog(QWidget):
    def __init__(self, suggestions, game_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Save Location Suggestions — {game_name} — Wingosy")
        self.setFixedSize(680, 350)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowTitleHint)
        self.selected_path = None
        
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        
        layout.addWidget(QLabel(f"<b>Found {len(suggestions)} possible save locations from PCGamingWiki:</b>"))
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: #1a1a1a; border: 1px solid #333;")
        
        container = QWidget()
        list_layout = QVBoxLayout(container)
        list_layout.setContentsMargins(2, 2, 2, 2)
        list_layout.setSpacing(2)
        list_layout.setAlignment(Qt.AlignTop)
        
        metrics = QFontMetrics(self.font())
        
        for item in suggestions:
            row = QWidget()
            row.setFixedHeight(36)
            row.setStyleSheet("background: #252525; border-radius: 3px;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(4, 0, 4, 0)
            rl.setSpacing(4)
            
            badge = QLabel(item["path_type"])
            color = "#2e7d32" if item["exists"] else "#555"
            badge.setFixedWidth(130)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(f"background: {color}; color: white; border-radius: 2px; font-size: 10px; font-weight: bold; padding: 2px;")
            rl.addWidget(badge)
            
            p_val = item['expanded_path']
            elided = metrics.elidedText(p_val, Qt.ElideMiddle, 380)
            lbl = QLabel(elided)
            lbl.setToolTip(p_val)
            lbl.setStyleSheet("font-size: 10px; color: #ddd; background: transparent;")
            rl.addWidget(lbl, 1)
            
            btn = QPushButton("📁 Browse Here")
            btn.setFixedWidth(100)
            btn.setStyleSheet("font-size: 10px; padding: 4px 8px; background: #444; color: white;")
            btn.clicked.connect(lambda checked, p=p_val: self.browse_and_confirm(p))
            rl.addWidget(btn)
            
            list_layout.addWidget(row)
            
        scroll.setWidget(container)
        layout.addWidget(scroll)
        
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet("padding: 8px; background: #333;")
        cancel.clicked.connect(self.close)
        layout.addWidget(cancel)
        
        QTimer.singleShot(0, self._apply_dark_frame)
        QTimer.singleShot(50, self._center_on_parent)

    def _apply_dark_frame(self):
        import sys, ctypes
        if sys.platform == "win32":
            try: ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 20, ctypes.byref(ctypes.c_int(1)), 4)
            except: pass

    def _center_on_parent(self):
        p = self.parent()
        if not p: return
        pg = p.geometry()
        x = pg.x() + (pg.width() - self.width()) // 2
        y = pg.y() + (pg.height() - self.height()) // 2
        self.move(x, y)

    def browse_and_confirm(self, start_path):
        p = Path(start_path)
        while not p.exists() and p.parent != p:
            p = p.parent
        directory = QFileDialog.getExistingDirectory(self, "Select Save Folder — Wingosy", str(p))
        if directory:
            if QMessageBox.question(self, "Confirm — Wingosy", f"Use this folder?\n{directory}") == QMessageBox.Yes:
                self.selected_path = directory
                self.accepted_path.emit(directory)
                self.close()
    
    accepted_path = Signal(str)

class WikiFetchWorker(QThread):
    results_ready = Signal(list)
    failed = Signal()
    
    def __init__(self, game_title, windows_games_dir):
        super().__init__()
        self.game_title = game_title
        self.windows_games_dir = windows_games_dir
        
    def run(self):
        try:
            from src.pcgamingwiki import fetch_save_locations
            self.results_ready.emit(fetch_save_locations(self.game_title, self.windows_games_dir))
        except Exception:
            self.failed.emit()

class SaveSyncSetupDialog(QWidget):
    def __init__(self, game_name, config, main_window, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Up Save Sync — Wingosy")
        self.game_name = game_name
        self.config = config
        self.main_window = main_window
        self.selected_path = None
        self.setFixedSize(450, 250)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowTitleHint)
        
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
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        msg = QLabel(f"Where does <b>{game_name}</b> save its files?<br><br>Setting this up enables automatic cloud backup.")
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignCenter)
        layout.addWidget(msg)
        layout.addStretch()
        
        self.btn_wiki = QPushButton("🌐 Get PCGamingWiki Suggestions")
        self.btn_wiki.setStyleSheet("padding: 10px; background: #1565c0; color: white; font-weight: bold;")
        self.btn_wiki.setVisible(self.config.get("pcgamingwiki_enabled", True))
        self.btn_wiki.clicked.connect(self.get_suggestions)
        layout.addWidget(self.btn_wiki)
        
        btn_man = QPushButton("📁 Browse Manually")
        btn_man.setStyleSheet("padding: 8px; background: #333;")
        btn_man.clicked.connect(self.browse_manually)
        layout.addWidget(btn_man)
        
        btn_skip = QPushButton("▶ Skip for Now")
        btn_skip.setStyleSheet("padding: 8px; background: #333;")
        btn_skip.clicked.connect(self.close)
        layout.addWidget(btn_skip)
        
        QTimer.singleShot(0, self._apply_dark_frame)
        QTimer.singleShot(50, self._center_on_parent)

    def _apply_dark_frame(self):
        import sys, ctypes
        if sys.platform == "win32":
            try: ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 20, ctypes.byref(ctypes.c_int(1)), 4)
            except: pass

    def _center_on_parent(self):
        p = self.parent()
        if not p: return
        pg = p.geometry()
        x = pg.x() + (pg.width() - self.width()) // 2
        y = pg.y() + (pg.height() - self.height()) // 2
        self.move(x, y)

    def get_suggestions(self):
        self.loading_dlg = QMessageBox(self)
        self.loading_dlg.setWindowTitle("Fetching — Wingosy")
        self.loading_dlg.setText("Querying PCGamingWiki...")
        self.loading_dlg.show()
        
        self.btn_wiki.setEnabled(False)
        self.wiki_worker = WikiFetchWorker(self.game_name, self.config.get("windows_games_dir", ""))
        self.wiki_worker.results_ready.connect(self.on_wiki_results)
        self.wiki_worker.failed.connect(self.on_wiki_failed)
        
        self.wiki_timeout = QTimer()
        self.wiki_timeout.setSingleShot(True)
        self.wiki_timeout.timeout.connect(self.on_wiki_timeout)
        self.wiki_timeout.start(3000)
        self.wiki_worker.start()
        
    def on_wiki_timeout(self):
        if self.wiki_worker and self.wiki_worker.isRunning():
            self.wiki_worker.terminate()
            self.on_wiki_failed()
            
    def on_wiki_results(self, res):
        if self.wiki_timeout: self.wiki_timeout.stop()
        self.loading_dlg.close()
        self.btn_wiki.setEnabled(True)
        
        if not res:
            QMessageBox.information(self, "No Suggestions — Wingosy", "None found. Browse manually.")
            self.browse_manually()
            return
            
        QTimer.singleShot(100, lambda: self._show_suggestions(res))
        
    def _show_suggestions(self, res):
        d = WikiSuggestionsDialog(res, self.game_name, self)
        d.accepted_path.connect(self._on_wiki_path_selected)
        d.show()
        self._suggestions_dlg = d
            
    def _on_wiki_path_selected(self, path):
        self.selected_path = path
        self.accepted.emit()
        self.close()

    accepted = Signal()

    def on_wiki_failed(self):
        if self.wiki_timeout: self.wiki_timeout.stop()
        self.loading_dlg.close()
        self.btn_wiki.setEnabled(True)
        QMessageBox.warning(self, "Error — Wingosy", "Failed to reach wiki.")
        
    def browse_manually(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Save Folder — Wingosy")
        if directory:
            self.selected_path = directory
            self.accepted.emit()
            self.close()

class CloudSaveManagerDialog(QWidget):
    def __init__(self, game, client, config, main_window, parent=None):
        super().__init__(parent)
        self.game = game
        self.client = client
        self.config = config
        self.main_window = main_window
        
        self.setWindowTitle(f"Cloud Save History — {game.get('name')} — Wingosy")
        self.setFixedSize(600, 450)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowTitleHint)
        
        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                color: #ffffff;
            }
            QLabel { color: #ffffff; }
            QPushButton { border-radius: 4px; padding: 6px; }
            QScrollArea { background: transparent; border: none; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        layout.addWidget(QLabel(f"<b>Cloud Save History for {game.get('name')}</b>"))
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background: #111; border: 1px solid #333; border-radius: 4px;")
        
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.list_container)
        layout.addWidget(self.scroll)

        self.refresh_btn = QPushButton("🔄 Refresh History")
        self.refresh_btn.setStyleSheet("background: #333; color: white;")
        self.refresh_btn.clicked.connect(self.load_history)
        layout.addWidget(self.refresh_btn)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("background: #444; color: #ccc;")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        QTimer.singleShot(0, self._apply_dark_frame)
        QTimer.singleShot(50, self._center_on_parent)
        QTimer.singleShot(100, self.load_history)

    def _apply_dark_frame(self):
        import sys, ctypes
        if sys.platform == "win32":
            try: ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 20, ctypes.byref(ctypes.c_int(1)), 4)
            except: pass

    def _center_on_parent(self):
        p = self.parent()
        if not p: return
        pg = p.geometry()
        x = pg.x() + (pg.width() - self.width()) // 2
        y = pg.y() + (pg.height() - self.height()) // 2
        self.move(x, y)

    def load_history(self):
        # Clear list
        while self.list_layout.count():
            child = self.list_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        
        self.list_layout.addWidget(QLabel("Loading history..."))
        
        class HistoryWorker(QThread):
            ready = Signal(list, list)
            def __init__(self, client, rid):
                super().__init__()
                self.client, self.rid = client, rid
            def run(self):
                saves = self.client.list_all_saves(self.rid)
                states = self.client.list_all_states(self.rid)
                self.ready.emit(saves, states)

        self.worker = HistoryWorker(self.client, self.game['id'])
        self.worker.ready.connect(self._on_history_ready)
        self.worker.start()

    def _on_history_ready(self, saves, states):
        while self.list_layout.count():
            child = self.list_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()

        all_items = []
        for s in saves:
            s['_type'] = 'save'
            all_items.append(s)
        for s in states:
            s['_type'] = 'state'
            all_items.append(s)
        
        if not all_items:
            self.list_layout.addWidget(QLabel("No cloud saves found for this game."))
            return

        all_items.sort(key=lambda x: x.get('updated_at', ''), reverse=True)

        for item in all_items:
            row = QFrame()
            row.setStyleSheet("background: #222; border-radius: 4px; margin-bottom: 2px;")
            rl = QHBoxLayout(row)
            
            icon = "💾" if item['_type'] == 'save' else "📸"
            date_str = item.get('updated_at', 'Unknown Date').replace('T', ' ').split('.')[0]
            
            info = QVBoxLayout()
            name_lbl = QLabel(f"<b>{icon} {item.get('name', 'Unnamed')}</b>")
            name_lbl.setStyleSheet("font-size: 11px;")
            date_lbl = QLabel(date_str)
            date_lbl.setStyleSheet("font-size: 10px; color: #888;")
            info.addWidget(name_lbl)
            info.addWidget(date_lbl)
            rl.addLayout(info, 1)

            restore_btn = QPushButton("Restore")
            restore_btn.setFixedWidth(80)
            restore_btn.setStyleSheet("background: #2e7d32; color: white; font-size: 10px;")
            restore_btn.clicked.connect(lambda checked, i=item: self.restore_version(i))
            rl.addWidget(restore_btn)

            del_btn = QPushButton("🗑")
            del_btn.setFixedWidth(30)
            del_btn.setStyleSheet("background: #8e0000; color: white; font-size: 10px;")
            del_btn.clicked.connect(lambda checked, i=item: self.delete_version(i))
            rl.addWidget(del_btn)

            self.list_layout.addWidget(row)

    def restore_version(self, item):
        msg = f"Restore this {item['_type']}?\n\nYour current local save will be backed up to .bak first."
        if QMessageBox.question(self, "Restore Version — Wingosy", msg) != QMessageBox.Yes:
            return

        # Use extraction/restore logic from GameDetailPanel? 
        # Actually watcher.pull_server_save or similar is better.
        
        # We need the emulator to get the strategy
        all_emus = emulators.load_emulators()
        platform = self.game.get('platform_slug')
        assigned_id = self.config.get("platform_assignments", {}).get(platform)
        emu = next((e for e in all_emus if e["id"] == assigned_id), None)
        if not emu: emu = emulators.get_emulator_for_platform(platform)
        if not emu: emu = next((e for e in all_emus if e["id"] == "retroarch"), None)

        if not emu:
            QMessageBox.warning(self, "Error", "Could not determine emulator for restoration.")
            return

        strategy = get_strategy(self.config, emu)
        # Find local path
        save_dir = strategy.get_save_dir(self.game)
        is_folder = (strategy.mode_id in ["folder", "windows"])
        local_path = str(save_dir) if save_dir else None
        if not local_path:
            files = strategy.get_save_files(self.game)
            if files: local_path = str(files[0])
        
        if not local_path:
            # Last resort: RA defaults
            if emu['id'] == 'retroarch':
                from pathlib import Path
                ra_dir = Path(emu['executable_path']).parent
                local_path = str(ra_dir / "saves")
            else:
                QMessageBox.warning(self, "Error", "Could not determine local save path.")
                return

        # Start restoration
        from src.ui.threads import ConflictResolveThread
        # Use ConflictResolveThread as a "Force Pull" thread
        self.rt = ConflictResolveThread(self.main_window.watcher, self.game['id'], self.game['name'], item, local_path, is_folder)
        self.rt.finished.connect(lambda ok: QMessageBox.information(self, "Done", "Save restored successfully!") if ok else QMessageBox.warning(self, "Failed", "Restoration failed."))
        self.rt.start()

    def delete_version(self, item):
        if QMessageBox.question(self, "Delete version?", "Delete this version from the cloud permanently?") != QMessageBox.Yes:
            return
        
        success = False
        if item['_type'] == 'save':
            success = self.client.delete_save(item['id'])
        else:
            success = self.client.delete_state(item['id'])
        
        if success:
            self.load_history()
        else:
            QMessageBox.warning(self, "Error", "Delete failed.")

from src import emulators
from src.save_strategies import get_strategy
from src.ui.widgets import format_speed
from src.ui.threads import ConflictResolveThread
