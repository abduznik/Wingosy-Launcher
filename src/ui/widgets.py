import sys
import os
from pathlib import Path
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton
from PySide6.QtCore import Qt

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

RETROARCH_PLATFORMS = [
    "n64", "psx", "ps1", "snes", "nes", "gba", "gbc", "gb",
    "genesis", "megadrive", "sega-genesis", "32x", "segacd",
    "gamegear", "mastersystem", "atari2600", "atari7800",
    "lynx", "ngp", "ngpc", "pcengine", "wonderswan", "msx",
    "arcade", "fba", "neogeo", "c64", "dos", "3do", "jaguar",
    "saturn", "dreamcast", "nds", "gba", "psp"
]

RETROARCH_CORES = {
    "n64":        "mupen64plus_next_libretro.dll",
    "psx":        "pcsx_rearmed_libretro.dll",
    "ps1":        "pcsx_rearmed_libretro.dll",
    "snes":       "snes9x_libretro.dll",
    "nes":        "nestopia_libretro.dll",
    "gba":        "mgba_libretro.dll",
    "gbc":        "gambatte_libretro.dll",
    "gb":         "gambatte_libretro.dll",
    "genesis":    "genesis_plus_gx_libretro.dll",
    "megadrive":  "genesis_plus_gx_libretro.dll",
    "sega-genesis": "genesis_plus_gx_libretro.dll",
    "32x":        "picodrive_libretro.dll",
    "segacd":     "genesis_plus_gx_libretro.dll",
    "gamegear":   "genesis_plus_gx_libretro.dll",
    "mastersystem": "genesis_plus_gx_libretro.dll",
    "atari2600":  "stella2014_libretro.dll",
    "atari7800":  "prosystem_libretro.dll",
    "psp":        "ppsspp_libretro.dll",
    "nds":        "desmume2015_libretro.dll",
    "saturn":     "yabasanshiro_libretro.dll",
    "dreamcast":  "flycast_libretro.dll",
    "arcade":     "mame_libretro.dll",
    "neogeo":     "fbalpha2012_neogeo_libretro.dll",
    "pcengine":   "mednafen_pce_libretro.dll",
}

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
        
        if hasattr(thread, 'progress'):
            thread.progress.connect(self.update_progress)

    def update_progress(self, val, speed=0):
        self.pbar.setValue(val)
        if speed > 0:
            self.speed_label.setText(format_speed(speed))

    def cancel(self):
        if self.thread:
            self.thread.requestInterruption()
        self.parent_queue.remove_download(self.thread)

class DownloadQueueWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        self._rows = {} # thread: (row_widget, name_label, pbar, cancel_btn, speed_label)

    def add_download(self, name, thread):
        row = DownloadRow(name, thread, self)
        self._rows[thread] = (row, row.name_label, row.pbar, row.cancel_btn, row.speed_label)
        self.layout.addWidget(row)

    def remove_download(self, thread):
        if thread in self._rows:
            row_widget, name_label, pbar, cancel_btn, speed_label = self._rows[thread]
            # Show brief completion state
            pbar.setValue(100)
            speed_label.setText("✅ Done")
            cancel_btn.setVisible(False)
            # Remove after 3 seconds
            from PySide6.QtCore import QTimer
            QTimer.singleShot(3000, lambda: self._remove_row(thread))

    def _remove_row(self, thread):
        if thread in self._rows:
            row_widget = self._rows[thread][0]
            self.layout.removeWidget(row_widget)
            row_widget.setParent(None)
            row_widget.deleteLater()
            del self._rows[thread]
