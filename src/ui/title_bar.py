import os
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QPushButton, 
                             QSpacerItem, QSizePolicy)
from PySide6.QtGui import QIcon, QPixmap, Qt
from PySide6.QtCore import Signal, Slot, QPoint

from src.ui.widgets import get_resource_path

class WingosyTitleBar(QWidget):
    tab_changed = Signal(int)
    settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self._drag_pos = None
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(8, 0, 0, 0)
        self.layout.setSpacing(0)

        # LEFT SIDE
        # App icon
        self.icon_label = QLabel()
        icon_path = get_resource_path("icon.png")
        if os.path.exists(icon_path):
            pix = QPixmap(icon_path).scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.icon_label.setPixmap(pix)
        self.icon_label.setFixedSize(20, 20)
        self.layout.addWidget(self.icon_label)
        self.layout.addSpacing(8)

        # App title
        self.title_label = QLabel("Wingosy")
        self.title_label.setStyleSheet("color: white; font-weight: bold; font-size: 13px;")
        self.layout.addWidget(self.title_label)
        self.layout.addSpacing(12)

        # Separator
        self.sep1 = QWidget()
        self.sep1.setFixedSize(1, 20)
        self.sep1.setStyleSheet("background: #444;")
        self.layout.addWidget(self.sep1)
        self.layout.addSpacing(12)

        # Connection status
        self.status_dot = QWidget()
        self.status_dot.setFixedSize(8, 8)
        self.status_dot.setStyleSheet("background: #f44336; border-radius: 4px;") # Default red
        self.layout.addWidget(self.status_dot)
        self.layout.addSpacing(6)

        self.status_text = QLabel("Disconnected")
        self.status_text.setStyleSheet("color: #aaa; font-size: 11px;")
        self.layout.addWidget(self.status_text)

        # Gamepad Indicator
        self.gamepad_indicator = QLabel("🎮")
        self.gamepad_indicator.setToolTip("Gamepad connected")
        self.gamepad_indicator.setVisible(False)
        self.gamepad_indicator.setStyleSheet("color: #4caf50; font-size: 14px; padding: 0 10px;")
        self.layout.addWidget(self.gamepad_indicator)

        # CENTER (Stretch)
        self.layout.addStretch()

        # RIGHT SIDE - Navigation
        self.nav_buttons = []
        
        self.lib_btn = self._create_nav_btn("📚 Library", 0)
        self.emu_btn = self._create_nav_btn("🎮 Emulators", 1)
        self.log_btn = self._create_nav_btn("📋 Logs", 2)
        self.settings_btn = self._create_nav_btn("⚙ Settings", 3)
        
        self.layout.addWidget(self.lib_btn)
        self.layout.addWidget(self.emu_btn)
        self.layout.addWidget(self.log_btn)
        self.layout.addWidget(self.settings_btn)

        # Separator
        self.layout.addSpacing(10)
        self.sep2 = QWidget()
        self.sep2.setFixedSize(1, 20)
        self.sep2.setStyleSheet("background: #444;")
        self.layout.addWidget(self.sep2)

        # Window Controls
        self.min_btn = self._create_ctrl_btn("─", self._minimize)
        self.max_btn = self._create_ctrl_btn("□", self._maximize_restore)
        self.close_btn = self._create_ctrl_btn("✕", self._close)
        self.close_btn.setObjectName("closeBtn")

        self.layout.addWidget(self.min_btn)
        self.layout.addWidget(self.max_btn)
        self.layout.addWidget(self.close_btn)

        self.setStyleSheet("""
            WingosyTitleBar {
                background: #1a1a1a;
                border-bottom: 1px solid #2d2d2d;
            }
        """)
        
        self.set_active_tab(0)

    def _create_nav_btn(self, text, index):
        btn = QPushButton(text)
        btn.setStyleSheet(self._nav_btn_style())
        btn.clicked.connect(lambda: self.tab_changed.emit(index))
        self.nav_buttons.append(btn)
        return btn

    def _nav_btn_style(self):
        return """
            QPushButton {
                background: transparent;
                color: #aaaaaa;
                font-size: 11px;
                padding: 0px 12px;
                border: none;
                border-bottom: 2px solid transparent;
                height: 40px;
            }
            QPushButton:hover {
                color: #ffffff;
                background: rgba(255,255,255,0.05);
            }
        """

    def _create_ctrl_btn(self, text, callback):
        btn = QPushButton(text)
        btn.setFixedSize(40, 40)
        btn.clicked.connect(callback)
        btn.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                color: #ffffff;
                font-size: 14px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.1);
            }
            QPushButton#closeBtn:hover {
                background: #e81123;
                color: white;
            }
        """)
        return btn

    def set_active_tab(self, index):
        for i, btn in enumerate(self.nav_buttons):
            if i == index:
                btn.setStyleSheet(self._nav_btn_style() + "color: #ffffff; border-bottom: 2px solid #0d6efd;")
            else:
                btn.setStyleSheet(self._nav_btn_style())

    def update_connection_status(self, status, host=""):
        if status == "connected":
            self.status_dot.setStyleSheet("background: #4caf50; border-radius: 4px;")
            self.status_text.setText(f"Connected to {host}")
        elif status == "connecting":
            self.status_dot.setStyleSheet("background: #ffeb3b; border-radius: 4px;")
            self.status_text.setText("Connecting...")
        else:
            self.status_dot.setStyleSheet("background: #f44336; border-radius: 4px;")
            self.status_text.setText("Disconnected")

    def _minimize(self):
        self.window().showMinimized()

    def _maximize_restore(self):
        if self.window().isMaximized():
            self.window().showNormal()
            self.max_btn.setText("□")
        else:
            self.window().showMaximized()
            self.max_btn.setText("❐")

    def _close(self):
        self.window().close()
