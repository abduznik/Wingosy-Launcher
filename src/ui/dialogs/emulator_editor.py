import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QListWidget, QListWidgetItem, QMessageBox)
from PySide6.QtCore import Qt, QTimer, Signal
from src.ui.widgets import format_size

class ExePickerDialog(QWidget):
    exe_selected = Signal(str)

    def __init__(self, exes, game_name, parent=None):
        super().__init__(parent)
        
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowTitleHint)
        self.setFixedSize(600, 450)
        self.setWindowTitle(f"Choose Executable — {game_name} — Wingosy")
        
        self.selected_exe = None
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
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        
        header = QLabel("Multiple executables found. Select one to launch:")
        header.setStyleSheet("font-size: 12pt; font-weight: bold; margin-bottom: 10px; background: transparent;")
        layout.addWidget(header)
        
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)
        
        for path in exes:
            try:
                size_str = format_size(os.path.getsize(path))
            except:
                size_str = "Unknown"
            item = QListWidgetItem(f"{os.path.basename(path)}\n({size_str}) — {path}")
            item.setData(Qt.UserRole, path)
            self.list_widget.addItem(item)
            
        btns = QHBoxLayout()
        btns.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("background: #444; color: #eee; padding: 10px 20px;")
        cancel_btn.clicked.connect(self.close)
        btns.addWidget(cancel_btn)
        
        launch_btn = QPushButton("▶ Launch Selected")
        launch_btn.setStyleSheet("background: #2e7d32; color: white; font-weight: bold; padding: 10px 20px; font-size: 11pt;")
        launch_btn.clicked.connect(self.accept_selection)
        btns.addWidget(launch_btn)
        
        layout.addLayout(btns)
        
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

    def accept_selection(self):
        if self.list_widget.currentItem():
            self.selected_exe = self.list_widget.currentItem().data(Qt.UserRole)
            self.exe_selected.emit(self.selected_exe)
            self.close()
        else:
            QMessageBox.warning(self, "No Selection — Wingosy", "Please select an executable.")

class AssetPickerDialog(QWidget):
    from PySide6.QtCore import Signal
    asset_selected = Signal(str, str) # name, url

    def __init__(self, emulator_name, assets, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint | Qt.WindowTitleHint)
        self.setFixedSize(600, 450)
        self.setWindowTitle(f"Download {emulator_name} — Wingosy")
        
        self.setStyleSheet("""
            QWidget { background-color: #1a1a1a; color: #ffffff; }
            QLabel { color: #ffffff; background: transparent; }
            QPushButton { border-radius: 4px; padding: 10px 20px; font-weight: bold; }
            QListWidget { background-color: #2b2b2b; color: #ffffff; border: 1px solid #555; font-size: 10pt; }
            QListWidget::item { padding: 12px; border-bottom: 1px solid #3a3a3a; }
            QListWidget::item:selected { background-color: #0d6efd; color: #ffffff; }
            QListWidget::item:hover { background-color: #3a3a3a; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        header = QLabel(f"Select a version of {emulator_name} to download:")
        header.setStyleSheet("font-size: 12pt; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(header)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        # Filter and add assets
        excluded_exts = (".tar.zst", ".AppImage", ".zsync", ".sig")
        for asset in assets:
            name = asset["name"]
            if any(name.endswith(ext) for ext in excluded_exts): continue
            if "Source" in name: continue
            
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, asset["browser_download_url"])
            self.list_widget.addItem(item)

        btns = QHBoxLayout()
        btns.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("background: #444; color: #eee;")
        cancel_btn.clicked.connect(self.close)
        btns.addWidget(cancel_btn)

        confirm_btn = QPushButton("⬇ Download Selected")
        confirm_btn.setStyleSheet("background: #0d6efd; color: white;")
        confirm_btn.clicked.connect(self.confirm)
        btns.addWidget(confirm_btn)

        layout.addLayout(btns)
        QTimer.singleShot(0, self._apply_dark_frame)

    def _apply_dark_frame(self):
        import sys, ctypes
        if sys.platform == "win32":
            try: ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 20, ctypes.byref(ctypes.c_int(1)), 4)
            except: pass

    def confirm(self):
        item = self.list_widget.currentItem()
        if item:
            self.asset_selected.emit(item.text(), item.data(Qt.UserRole))
            self.close()
        else:
            QMessageBox.warning(self, "No Selection", "Please select a file to download.")
