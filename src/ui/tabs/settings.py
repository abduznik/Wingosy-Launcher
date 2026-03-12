import os
import sys
import subprocess
import logging
import webbrowser
from pathlib import Path
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QMessageBox, QProgressBar, 
                             QComboBox, QFileDialog, QSpinBox, QScrollArea,
                             QCheckBox, QFrame)
from PySide6.QtCore import Qt, QTimer

from src.ui.threads import UpdaterThread, SelfUpdateThread

def _get_check_icon_path():
    import os
    from pathlib import Path
    from PySide6.QtGui import QPixmap, QPainter, QPen, QColor
    from PySide6.QtCore import Qt, QPointF
    
    check_path = Path.home() / ".wingosy" / "check.png"
    
    if not check_path.exists():
        check_path.parent.mkdir(parents=True, exist_ok=True)
        px = QPixmap(14, 14)
        px.fill(QColor(0, 0, 0, 0))
        painter = QPainter(px)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#ffffff"))
        pen.setWidth(2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        # Draw checkmark: ✓
        painter.drawPolyline([
            QPointF(2, 7),
            QPointF(5, 10),
            QPointF(12, 3)
        ])
        painter.end()
        px.save(str(check_path))
    
    return str(check_path).replace("\\", "/")

class SettingsTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.config = main_window.config
        
        # Main Layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        
        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.scroll_layout = QVBoxLayout(self.container)
        self.scroll_layout.setContentsMargins(20, 20, 20, 20)
        self.scroll_layout.setSpacing(16)
        
        self._setup_sections()
        
        self.scroll_layout.addStretch()
        self.scroll.setWidget(self.container)
        self.layout.addWidget(self.scroll)

        # Version Label (Fixed at bottom)
        self.version_label = QLabel(f"Wingosy v{self.main_window.version}")
        self.version_label.setStyleSheet("color: #444; font-size: 10px; padding: 10px;")
        self.version_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.version_label)

    def _make_section_card(self, title):
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: #242424;
                border: 1px solid #333333;
                border-radius: 8px;
            }
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)
        
        title_label = QLabel(title)
        title_label.setStyleSheet("""
            color: #ffffff;
            font-size: 12px;
            font-weight: bold;
            border: none;
            background: transparent;
        """)
        layout.addWidget(title_label)
        
        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("color: #333; border: none; background: #333; max-height: 1px;")
        layout.addWidget(div)
        
        return card, layout

    def _make_row(self, label_text, widget, action_btn=None):
        row = QWidget()
        row.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        lbl = QLabel(label_text)
        lbl.setFixedWidth(160)
        lbl.setStyleSheet("color: #aaaaaa; font-size: 11px; border: none;")
        layout.addWidget(lbl)
        
        layout.addWidget(widget, 1)
        
        if action_btn:
            layout.addWidget(action_btn)
            
        return row

    def _apply_widget_style(self, widget):
        if isinstance(widget, (QLineEdit, QSpinBox)):
            widget.setStyleSheet("""
                background: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
                color: #ffffff;
                padding: 5px 8px;
                font-size: 11px;
            """)
        elif isinstance(widget, QComboBox):
            widget.setStyleSheet("""
                QComboBox {
                    background: #1a1a1a;
                    border: 1px solid #444;
                    border-radius: 4px;
                    color: #ffffff;
                    padding: 5px 8px;
                    font-size: 11px;
                    min-width: 160px;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 20px;
                }
                QComboBox::down-arrow {
                    image: none;
                    border-left: 4px solid transparent;
                    border-right: 4px solid transparent;
                    border-top: 5px solid #aaaaaa;
                }
            """)
        elif isinstance(widget, QCheckBox):
            check_path = _get_check_icon_path()
            widget.setStyleSheet(f"""
                QCheckBox {{
                    color: #cccccc;
                    font-size: 11px;
                    spacing: 8px;
                    border: none;
                }}
                QCheckBox::indicator {{
                    width: 16px;
                    height: 16px;
                    border: 1px solid #555;
                    border-radius: 3px;
                    background: #1a1a1a;
                }}
                QCheckBox::indicator:checked {{
                    background: #0d6efd;
                    border: 1px solid #0d6efd;
                    image: url("{check_path}");
                }}
                QCheckBox::indicator:hover {{
                    border: 1px solid #0d6efd;
                }}
            """)

    def _make_action_btn(self, text, danger=False):
        btn = QPushButton(text)
        if danger:
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #f44336;
                    border: 1px solid #f44336;
                    border-radius: 4px;
                    padding: 6px 20px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background: #f44336;
                    color: #ffffff;
                }
            """)
            btn.setMaximumWidth(120)
        else:
            btn.setStyleSheet("""
                QPushButton {
                    background: #2d2d2d;
                    color: #cccccc;
                    border: 1px solid #444;
                    border-radius: 4px;
                    padding: 5px 14px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background: #3a3a3a;
                    color: #ffffff;
                    border: 1px solid #555;
                }
            """)
        return btn

    def _setup_sections(self):
        # ── Server Connection ──────────────────────────────────────────
        card, layout = self._make_section_card("Server Connection")
        
        self.host_input = QLineEdit(self.config.get("host", ""))
        self.host_input.setPlaceholderText("http://your-romm-server:8285")
        self._apply_widget_style(self.host_input)
        self.test_btn = self._make_action_btn("Test Connection")
        self.test_btn.clicked.connect(self._test_host_connection)
        layout.addWidget(self._make_row("RomM Host", self.host_input, self.test_btn))
        
        self.re_btn = QPushButton("✅ Apply & Restart")
        self.re_btn.setVisible(False)
        self.re_btn.setStyleSheet("background: #2e7d32; color: white; border-radius: 4px; padding: 5px; font-size: 11px;")
        self.re_btn.clicked.connect(self._apply_and_restart)
        layout.addWidget(self.re_btn)
        
        account_val = QLabel(f"Logged in as: {self.config.get('username')}")
        account_val.setStyleSheet("color: #ffffff; font-size: 11px; border: none;")
        self.logout_btn = self._make_action_btn("Log Out", danger=True)
        self.logout_btn.clicked.connect(self.do_logout)
        layout.addWidget(self._make_row("Account", account_val, self.logout_btn))
        
        self.scroll_layout.addWidget(card)

        # ── Windows Games ─────────────────────────────────────────────
        card, layout = self._make_section_card("Windows Games")
        
        self.win_input = QLineEdit(self.config.get("windows_games_dir", ""))
        self.win_input.setPlaceholderText("Folder where Windows games are installed")
        self._apply_widget_style(self.win_input)
        self.browse_btn = self._make_action_btn("Browse")
        self.browse_btn.clicked.connect(self.browse_win)
        layout.addWidget(self._make_row("Games Folder", self.win_input, self.browse_btn))
        
        self.wiki_check = QCheckBox("Auto-suggest save locations")
        self.wiki_check.setChecked(self.config.get("pcgamingwiki_enabled", True))
        self.wiki_check.stateChanged.connect(lambda s: self.config.set("pcgamingwiki_enabled", s == Qt.Checked.value))
        self._apply_widget_style(self.wiki_check)
        layout.addWidget(self._make_row("PCGamingWiki", self.wiki_check))
        
        self.scroll_layout.addWidget(card)

        # ── Sync & Behavior ───────────────────────────────────────────
        card, layout = self._make_section_card("Sync & Behavior")
        
        self.ap_check = QCheckBox("Pull saves before launch")
        self.ap_check.setChecked(self.config.get("auto_pull_saves", True))
        self.ap_check.toggled.connect(lambda checked: self.config.set("auto_pull_saves", checked))
        self._apply_widget_style(self.ap_check)
        layout.addWidget(self._make_row("Cloud Sync", self.ap_check))
        
        self.ra_combo = QComboBox()
        self.ra_combo.addItems(["Both", "SRM only", "States only"])
        ra_mode = self.config.get("retroarch_save_mode", "srm")
        self.ra_combo.setCurrentText({"srm": "SRM only", "state": "States only", "both": "Both"}.get(ra_mode))
        self.ra_combo.currentTextChanged.connect(self.set_ra_save_mode)
        self._apply_widget_style(self.ra_combo)
        layout.addWidget(self._make_row("RetroArch Mode", self.ra_combo))

        self.ver_spin = QSpinBox()
        self.ver_spin.setRange(1, 20)
        self.ver_spin.setValue(self.config.get("max_save_versions", 5))
        self.ver_spin.valueChanged.connect(lambda val: self.config.set("max_save_versions", val))
        self._apply_widget_style(self.ver_spin)
        layout.addWidget(self._make_row("Max Cloud Versions", self.ver_spin))
        
        self.scroll_layout.addWidget(card)

        # ── Controller ────────────────────────────────────────────────
        card, layout = self._make_section_card("Controller / Gamepad")
        
        self.controller_combo = QComboBox()
        self.controller_combo.addItem("Xbox / XInput", "xinput")
        self.controller_combo.addItem("PlayStation 4 (DS4)", "ps4")
        self.controller_combo.addItem("PlayStation 5 (DualSense)", "ps5")
        self.controller_combo.addItem("Nintendo Switch Pro", "switch")
        self.controller_combo.addItem("Generic / Other", "generic")
        
        current_type = self.config.get("controller_type", "xinput")
        idx = self.controller_combo.findData(current_type)
        if idx >= 0: self.controller_combo.setCurrentIndex(idx)
        self.controller_combo.currentIndexChanged.connect(self._on_controller_type_changed)
        self._apply_widget_style(self.controller_combo)
        layout.addWidget(self._make_row("Controller Type", self.controller_combo))
        
        self.mapping_preview = QLabel()
        self.mapping_preview.setStyleSheet("color: #666666; font-size: 10px; font-style: italic; margin-left: 170px; border: none;")
        self._update_mapping_preview()
        layout.addWidget(self.mapping_preview)
        
        self.scroll_layout.addWidget(card)

        # ── Appearance & Debug ────────────────────────────────────────
        card, layout = self._make_section_card("Appearance & Debug")
        
        self.row_spin = QSpinBox()
        self.row_spin.setRange(1, 12)
        self.row_spin.setValue(self.config.get("cards_per_row", 6))
        self.row_spin.valueChanged.connect(self.set_cards_per_row)
        self._apply_widget_style(self.row_spin)
        layout.addWidget(self._make_row("Cards per row", self.row_spin))
        
        self.log_combo = QComboBox()
        self.log_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_combo.setCurrentText(self.config.get("log_level", "INFO").upper())
        self.log_combo.currentTextChanged.connect(self.set_log_level)
        self._apply_widget_style(self.log_combo)
        layout.addWidget(self._make_row("Log Level", self.log_combo))
        
        self.scroll_layout.addWidget(card)

        # ── Maintenance ───────────────────────────────────────────────
        card, layout = self._make_section_card("Maintenance")
        
        self.check_updates_btn = self._make_action_btn("Check for Updates")
        self.check_updates_btn.clicked.connect(self.check_updates)
        layout.addWidget(self._make_row("Updates", self.check_updates_btn))
        
        self.up_btn = QPushButton("Upgrade Available!")
        self.up_btn.setStyleSheet("background: #2e7d32; color: white; padding: 8px; border-radius: 4px; font-size: 11px;")
        self.up_btn.setVisible(False)
        layout.addWidget(self.up_btn)
        
        self.pbar = QProgressBar()
        self.pbar.setVisible(False)
        self.pbar.setStyleSheet("QProgressBar { border: 1px solid #444; border-radius: 4px; text-align: center; color: white; } QProgressBar::chunk { background-color: #0d6efd; }")
        layout.addWidget(self.pbar)
        
        self.scroll_layout.addWidget(card)

    def browse_win(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Folder")
        if directory:
            self.win_input.setText(directory)
            self.config.set("windows_games_dir", directory)
            
    def _test_host_connection(self):
        host = self.host_input.text().strip()
        if not host: return
        self.test_btn.setText("Testing...")
        self.test_btn.setEnabled(False)
        ok, msg = self.main_window.client.test_connection(
            host_override=host, 
            retry_callback=lambda: self.test_btn.setText("Retrying...")
        )
        self.test_btn.setText("Test Connection")
        self.test_btn.setEnabled(True)
        if ok:
            QMessageBox.information(self, "Success", f"{msg} Click Apply.")
            self.re_btn.setVisible(True)
        else:
            QMessageBox.warning(self, "Failed", msg)
            self.re_btn.setVisible(False)
            
    def _apply_and_restart(self):
        self.config.set("host", self.host_input.text().strip())
        self._do_restart()
        
    def _do_restart(self):
        if sys.platform == "win32":
            subprocess.Popen([sys.executable], close_fds=True, creationflags=(0x00000008 | 0x00000200), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen([sys.executable], close_fds=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        sys.exit(0)
        
    def set_cards_per_row(self, val):
        self.config.set("cards_per_row", val)
        self.main_window.library_tab._resize_all_cards()
        
    def set_log_level(self, text):
        self.config.set("log_level", text)
        logging.getLogger().setLevel(getattr(logging, text.upper(), logging.INFO))
        
    def set_ra_save_mode(self, text):
        mode = {"SRM only": "srm", "States only": "state", "Both": "both"}.get(text, "srm")
        self.config.set("retroarch_save_mode", mode)
        
    def _on_controller_type_changed(self):
        selected_type = self.controller_combo.currentData()
        self.config.set("controller_type", selected_type)
        self._update_mapping_preview()

    def _update_mapping_preview(self):
        ctype = self.controller_combo.currentData()
        preview = {
            "xinput": "Xbox: A=Confirm, B=Back, LStick=Navigate",
            "ps4": "PS4: ✕=Confirm, ○=Back, LStick=Navigate",
            "ps5": "PS5: ✕=Confirm, ○=Back, LStick=Navigate",
            "switch": "Switch: A=Confirm, B=Back, LStick=Navigate",
            "generic": "Generic: Btn0=Confirm, Btn1=Back"
        }.get(ctype, "")
        self.mapping_preview.setText(preview)

    def check_updates(self):
        self.updater = UpdaterThread(self.main_window.version)
        self.updater.finished.connect(self.on_update_result)
        self.updater.start()
        
    def on_update_result(self, available, version, url):
        if available:
            self.latest_url = url
            self.up_btn.setText(f"Upgrade to v{version}")
            self.up_btn.setVisible(True)
            if getattr(sys, 'frozen', False):
                self.up_btn.clicked.connect(self.start_self_update)
            else:
                self.up_btn.clicked.connect(lambda: webbrowser.open(url))
        else:
            QMessageBox.information(self, "No Updates", "You are on the latest version.")
            
    def start_self_update(self):
        self.up_btn.setEnabled(False)
        self.pbar.setVisible(True)
        self.t = SelfUpdateThread(self.latest_url, Path(sys.executable).resolve())
        self.t.progress.connect(self.pbar.setValue)
        self.t.finished.connect(self.on_self_update_finished)
        self.t.start()
        
    def on_self_update_finished(self, success, msg):
        if success:
            QMessageBox.information(self, "Done", "Update installed. Restarting...")
            subprocess.Popen(['cmd.exe', '/c', f'timeout /t 2 >NUL & start "" "{sys.executable}"'], creationflags=subprocess.CREATE_NO_WINDOW)
            sys.exit(0)
        else:
            QMessageBox.critical(self, "Failed", msg)
            
    def do_logout(self):
        if QMessageBox.question(self, "Log Out", "Are you sure you want to log out?") == QMessageBox.Yes:
            self.main_window.client.logout()
            self.config.set("password", None)
            sys.exit(0)
