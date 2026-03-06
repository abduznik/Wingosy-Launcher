import sys
import os
from pathlib import Path
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton
from PySide6.QtCore import Qt
from src.platforms import RETROARCH_PLATFORMS, RETROARCH_CORES, platform_matches

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

def elide_text(text, max_chars=24):
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + "…"

class DownloadRow(QWidget):
    def __init__(self, name, thread, parent_queue):
        super().__init__()
        self.thread = thread
        self.parent_queue = parent_queue
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        self.name_label = QLabel(name)
        self.name_label.setFixedWidth(150)
        layout.addWidget(self.name_label)
        
        self.pbar = QProgressBar()
        layout.addWidget(self.pbar)
        
        self.speed_label = QLabel("0 KB/s")
        self.speed_label.setFixedWidth(80)
        layout.addWidget(self.speed_label)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedWidth(60)
        self.cancel_btn.clicked.connect(self.cancel)
        layout.addWidget(self.cancel_btn)
        
        # Connect signals
        self.thread.progress.connect(self.update_progress)
        self.thread.finished.connect(self.on_finished)

    def update_progress(self, p, speed):
        self.pbar.setValue(p)
        self.speed_label.setText(format_speed(speed))

    def cancel(self):
        self.thread.requestInterruption()
        self.on_finished(False, "Cancelled")

    def on_finished(self, ok, msg):
        self.parent_queue.remove_download(self.thread)

class DownloadQueueWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)
        self._rows = {}

    def add_download(self, name, thread):
        row = DownloadRow(name, thread, self)
        self.layout.addWidget(row)
        self._rows[thread] = (row, name)

    def remove_download(self, thread):
        if thread in self._rows:
            row_widget = self._rows[thread][0]
            self.layout.removeWidget(row_widget)
            row_widget.setParent(None)
            row_widget.deleteLater()
            del self._rows[thread]
