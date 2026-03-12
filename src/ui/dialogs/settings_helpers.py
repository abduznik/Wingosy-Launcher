import re
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QFormLayout, QDialogButtonBox, QMessageBox)
from PySide6.QtCore import Qt, QTimer, Signal

class WelcomeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to Wingosy Launcher — Wingosy")
        self.setFixedSize(500, 350)
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
        
        layout.addWidget(QLabel("<h1>Welcome to Wingosy!</h1>"))
        info = QLabel("<p style='font-size: 12pt;'>Your setup is almost complete. Follow the tabs to get started.</p>")
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addStretch()
        
        btn = QPushButton("Get Started")
        btn.setStyleSheet("background: #1e88e5; color: white; padding: 10px; font-weight: bold;")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)
        
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

class SetupDialog(QDialog):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wingosy Setup — Wingosy")
        self.config = config_manager
        self.setFixedSize(400, 250)
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

        layout = QFormLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        self.host_input = QLineEdit(self.config.get("host"))
        self.host_input.setStyleSheet("background: #222; border: 1px solid #444; color: white; padding: 5px;")
        self.user_input = QLineEdit(self.config.get("username"))
        self.user_input.setStyleSheet("background: #222; border: 1px solid #444; color: white; padding: 5px;")
        self.pass_input = QLineEdit("")
        self.pass_input.setEchoMode(QLineEdit.Password)
        self.pass_input.setStyleSheet("background: #222; border: 1px solid #444; color: white; padding: 5px;")
        
        layout.addRow("RomM Host:", self.host_input)
        layout.addRow("Username:", self.user_input)
        layout.addRow("Password:", self.pass_input)
        
        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)
        
        ok_btn = QPushButton("Connect")
        ok_btn.setStyleSheet("background: #1e88e5; color: white; padding: 5px 15px; font-weight: bold;")
        ok_btn.clicked.connect(self.validate_and_accept)
        btns.addWidget(ok_btn)
        
        layout.addRow(btns)
        
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
        
    def validate_and_accept(self):
        if not re.match(r'^https?://.+', self.host_input.text().strip()):
            QMessageBox.warning(self, "Invalid Host — Wingosy", "Enter a valid URL.")
            return
        self.accept()

    def get_data(self):
        return {
            "host": self.host_input.text().strip().rstrip('/'),
            "username": self.user_input.text().strip(),
            "password": self.pass_input.text()
        }
