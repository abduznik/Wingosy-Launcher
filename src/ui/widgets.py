import sys
import os
import shutil
import logging
from pathlib import Path
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QMessageBox
from PySide6.QtCore import Qt, Signal, QTimer
from src.platforms import RETROARCH_PLATFORMS, RETROARCH_CORES, platform_matches
from src import download_registry

def get_resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def format_speed(bps):
    if bps <= 0:
        return ""
    if bps >= 1024 * 1024 * 1024:
        return f"{bps/(1024**3):.1f} GB/s"
    if bps >= 1024 * 1024:
        return f"{bps/(1024**2):.1f} MB/s"
    if bps >= 1024:
        return f"{bps/1024:.1f} KB/s"
    return f"{bps:.0f} B/s"

def format_size(bytes_count):
    if bytes_count > 1024*1024*1024:
        return f"{bytes_count/(1024*1024*1024):.2f} GB"
    return f"{bytes_count/(1024*1024):.1f} MB"

def elide_text(text, max_chars=24):
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + "…"

class DownloadRow(QWidget):
    def __init__(self, rom_id, rom_name, thread, row_type, parent_queue):
        super().__init__()
        self.rom_id = str(rom_id)
        self.rom_name = rom_name
        self.thread = thread
        self.row_type = row_type # "download" | "extraction"
        self.parent_queue = parent_queue
        
        self.setStyleSheet("""
            DownloadRow {
                background: #242424;
                border: 1px solid #333;
                border-radius: 6px;
            }
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 10, 14, 10)
        main_layout.setSpacing(6)

        # Top row: Name and Status Badge
        top_layout = QHBoxLayout()
        self.name_label = QLabel(rom_name)
        self.name_label.setStyleSheet("font-weight: bold; color: white; border: none;")
        top_layout.addWidget(self.name_label, 1)

        status_text = "Extracting" if row_type == "extraction" else row_type.capitalize() + "ing"
        self.status_badge = QLabel(status_text)
        self.status_badge.setContentsMargins(8, 2, 8, 2)
        self._update_badge_style("progress")
        top_layout.addWidget(self.status_badge)
        main_layout.addLayout(top_layout)

        # Progress row
        progress_layout = QHBoxLayout()
        self.pbar = QProgressBar()
        self.pbar.setFixedHeight(6)
        self.pbar.setTextVisible(False)
        pbar_chunk_color = "#e65100" if row_type == "extraction" else "#0d6efd"
        self.pbar.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: 3px;
                background: #2d2d2d;
                height: 6px;
            }}
            QProgressBar::chunk {{
                border-radius: 3px;
                background: {pbar_chunk_color};
            }}
        """)
        progress_layout.addWidget(self.pbar, 1)

        self.pct_label = QLabel("0%")
        self.pct_label.setFixedWidth(35)
        self.pct_label.setStyleSheet("color: #aaa; font-size: 11px; border: none;")
        progress_layout.addWidget(self.pct_label)

        self.size_label = QLabel("0 / 0 MB")
        self.size_label.setFixedWidth(120)
        self.size_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.size_label.setStyleSheet("color: #aaa; font-size: 11px; border: none;")
        progress_layout.addWidget(self.size_label)
        main_layout.addLayout(progress_layout)

        # Bottom row: Speed and Cancel Button
        bottom_layout = QHBoxLayout()
        self.speed_label = QLabel("")
        self.speed_label.setStyleSheet("color: #0d6efd; font-size: 10px; font-weight: bold; border: none;")
        bottom_layout.addWidget(self.speed_label)
        
        bottom_layout.addStretch()
        self.cancel_btn = QPushButton("✕ Cancel")
        self.cancel_btn.setFixedWidth(80)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #f44336;
                border: 1px solid #f44336;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 10px;
            }
            QPushButton:hover {
                background: #f44336;
                color: white;
            }
        """)
        self.cancel_btn.clicked.connect(self.request_cancel)
        bottom_layout.addWidget(self.cancel_btn)
        main_layout.addLayout(bottom_layout)

        # Connect to registry for updates
        download_registry.add_listener(self.rom_id, self.on_registry_update)

    def _update_badge_style(self, status):
        colors = {
            "progress": "#1565c0" if self.row_type == "download" else "#e65100",
            "done": "#2e7d32",
            "cancelled": "#555555",
            "error": "#b71c1c"
        }
        color = colors.get(status, "#555")
        self.status_badge.setStyleSheet(f"""
            background: {color};
            color: white;
            border-radius: 4px;
            font-size: 10px;
            font-weight: bold;
            padding: 2px 6px;
        """)

    def on_registry_update(self, rom_id, rtype, current, total, speed=0):
        if rtype == "extraction":
            self._on_extraction_progress(current, total)
            return

        if total > 0:
            pct = int(current / total * 100)
            self.pbar.setValue(pct)
            self.pct_label.setText(f"{pct}%")
            self.size_label.setText(f"{format_size(current)} / {format_size(total)}")
        
        if speed > 0:
            self.speed_label.setText(format_speed(speed))
        
        if rtype == "done":
            self.status_badge.setText("Done")
            self._update_badge_style("done")
            self.cancel_btn.hide()
            self.speed_label.setText("")
            QTimer.singleShot(5000, lambda: self.parent_queue.remove_download(self.thread))
        elif rtype == "cancelled":
            self.status_badge.setText("Cancelled")
            self._update_badge_style("cancelled")
            self.cancel_btn.hide()
            self.speed_label.setText("")

    def _on_extraction_progress(self, done, total):
        if total == 0 and done == 0:
            self.pbar.setRange(0, 0)
            self.size_label.setText("Extracting...")
            return
        
        self.pbar.setRange(0, 100)
        if total == 100: # 7z percentage mode
            self.pbar.setValue(done)
            self.pct_label.setText(f"{done}%")
            self.size_label.setText(f"{done}%")
        else: # zip file count mode
            pct = int(done / total * 100) if total > 0 else 0
            self.pbar.setValue(pct)
            self.pct_label.setText(f"{pct}%")
            self.size_label.setText(f"{done} / {total} files")

    def request_cancel(self):
        if self.row_type == "extraction":
            reply = QMessageBox.question(
                self, "Cancel Extraction",
                f"Cancel extracting {self.rom_name}?\n\nWhat should happen to the files extracted so far?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Cancel
            )
            if reply == QMessageBox.Cancel: return
            
            self.thread.cancel()
            if reply == QMessageBox.Discard:
                def on_cancelled(path):
                    import shutil
                    shutil.rmtree(path, ignore_errors=True)
                self.thread.cancelled.connect(on_cancelled)
        else:
            reply = QMessageBox.question(
                self, "Cancel Download",
                f"Cancel downloading {self.rom_name}?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Cancel
            )
            if reply == QMessageBox.Cancel: return
            
            self.thread.cancel()
            if reply == QMessageBox.Discard:
                def on_cancelled_dl():
                    p = getattr(self.thread, 'file_path', None)
                    if p and os.path.exists(p):
                        try: os.remove(p)
                        except: pass
                self.thread.cancelled.connect(on_cancelled_dl)

        self.status_badge.setText("Cancelled")
        self._update_badge_style("cancelled")
        self.cancel_btn.hide()
        self.speed_label.setText("")
        download_registry.update_status(self.rom_id, "cancelled")
        QTimer.singleShot(2000, lambda: download_registry.unregister(self.rom_id))

    def closeEvent(self, event):
        download_registry.remove_listener(self.rom_id, self.on_registry_update)
        super().closeEvent(event)

class DownloadQueueWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(8)
        self.layout.setAlignment(Qt.AlignTop)
        self._rows = {} # thread: row_widget

    def refresh_from_registry(self):
        for rom_id, entry in download_registry.all().items():
            if entry["thread"] not in self._rows:
                self.add_download(entry["rom_name"], entry["thread"], entry["type"], rom_id)

    def add_download(self, name, thread, row_type="download", rom_id=None):
        if thread in self._rows:
            return
        row = DownloadRow(rom_id, name, thread, row_type, self)
        self.layout.addWidget(row)
        self._rows[thread] = row

    def remove_download(self, thread):
        if thread in self._rows:
            row_widget = self._rows[thread]
            self.layout.removeWidget(row_widget)
            row_widget.deleteLater()
            del self._rows[thread]
