import os
from pathlib import Path
import logging
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,   
                             QPushButton, QScrollArea, QFormLayout,
                             QLineEdit, QFileDialog, QMessageBox,
                             QDialog, QComboBox, QDialogButtonBox, QTabWidget,
                             QSpinBox, QCheckBox)
from PySide6.QtCore import Qt

from src.ui.threads import (DirectDownloader, DolphinDownloader,
                             GithubDownloader, BiosDownloader, CoreDownloadThread)
from src.ui.widgets import format_speed, get_resource_path
from src import emulators

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

class EmulatorEditDialog(QDialog):
    def __init__(self, emu_data=None, parent=None):
        super().__init__(parent)
        self.emu_data = emu_data
        self.setWindowTitle("Edit Emulator" if emu_data else "Add Custom Emulator")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. DuckStation")
        if emu_data: self.name_input.setText(emu_data.get("name", ""))      
        form.addRow("Emulator Name:", self.name_input)

        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("C:/Path/to/emulator.exe")       
        if emu_data: self.path_input.setText(emu_data.get("executable_path", ""))
        path_layout.addWidget(self.path_input)
        self.browse_exe_btn = QPushButton("Browse")
        self.browse_exe_btn.clicked.connect(self.browse_exe)
        path_layout.addWidget(self.browse_exe_btn)
        form.addRow("Executable Path:", path_layout)

        self.slugs_input = QLineEdit()
        self.slugs_input.setPlaceholderText("e.g. psx, ps1, playstation")   
        if emu_data: self.slugs_input.setText(", ".join(emu_data.get("platform_slugs", [])))
        form.addRow("Platform Slugs:", self.slugs_input)

        helper = QLabel("<small style='color:#888;'>Common: psx, ps2, ps3, switch, wiiu, 3ds, gc, wii, xbox, xbox360, nds, gba, snes, n64</small>")     
        form.addRow("", helper)

        self.args_input = QLineEdit()
        self.args_input.setPlaceholderText("{rom_path}")
        if emu_data: self.args_input.setText(" ".join(emu_data.get("launch_args", ["{rom_path}"])))
        form.addRow("Launch Arguments:", self.args_input)

        args_helper = QLabel("<small style='color:#888;'>Use {rom_path} for the game file. Example: --fullscreen {rom_path}</small>")
        form.addRow("", args_helper)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Direct File (.sav/.mcr etc)", "direct_file")
        self.mode_combo.addItem("Folder Sync (zip entire folder)", "folder")
        self.mode_combo.addItem("No Save Sync", "none")

        save_res = emu_data.get("save_resolution", {}) if emu_data else {}  
        mode = save_res.get("mode", "none")
        idx = self.mode_combo.findData(mode)
        if idx >= 0: self.mode_combo.setCurrentIndex(idx)
        form.addRow("Save Sync Mode:", self.mode_combo)

        save_path_layout = QHBoxLayout()
        self.save_path_input = QLineEdit()
        if emu_data: self.save_path_input.setText(save_res.get("path", "") or save_res.get("srm_dir", ""))
        save_path_layout.addWidget(self.save_path_input)
        self.browse_save_btn = QPushButton("Browse")
        self.browse_save_btn.clicked.connect(self.browse_dir)
        self.save_path_label = QLabel("Save Directory:")
        form.addRow(self.save_path_label, save_path_layout)

        self.ext_input = QLineEdit()
        self.ext_input.setPlaceholderText(".mcd")
        if emu_data: self.ext_input.setText(save_res.get("extension", ""))  
        self.ext_label = QLabel("Save File Extension:")
        form.addRow(self.ext_label, self.ext_input)

        self.mode_combo.currentIndexChanged.connect(self.update_visibility) 
        self.update_visibility()

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Emulator Executable", "", "Executables (*.exe)")
        if path: self.path_input.setText(path)

    def browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Save Directory")
        if path: self.save_path_input.setText(path)

    def update_visibility(self):
        mode = self.mode_combo.currentData()
        is_none = (mode == "none")
        is_direct = (mode == "direct_file")

        self.save_path_input.setEnabled(not is_none)
        self.browse_save_btn.setEnabled(not is_none)

        self.ext_input.setVisible(is_direct)
        self.ext_label.setVisible(is_direct)

    def validate_and_save(self):
        name = self.name_input.text().strip()
        exe = self.path_input.text().strip()
        slugs = [s.strip() for s in self.slugs_input.text().split(",") if s.strip()]

        if not name or not exe or not slugs:
            QMessageBox.warning(self, "Error", "Name, path, and at least one slug are required.")
            return

        emu_id = name.lower().replace(" ", "_")

        if not self.emu_data:
            all_emus = emulators.load_emulators()
            existing = next((e for e in all_emus if e["id"] == emu_id), None)
            if existing and not existing.get("user_defined"):
                QMessageBox.warning(self, "Error", "Cannot overwrite a built-in emulator. Choose a different name.")
                return

        mode = self.mode_combo.currentData()
        save_res = {"mode": mode}
        if mode != "none":
            save_res["path"] = self.save_path_input.text().strip()
            if mode == "direct_file":
                save_res["extension"] = self.ext_input.text().strip()       

        new_data = {
            "id": emu_id,
            "name": name,
            "executable_path": exe,
            "launch_args": self.args_input.text().split(),
            "platform_slugs": slugs,
            "save_resolution": save_res,
            "user_defined": True,
            "sync_enabled": True,
            "conflict_behavior": "ask"
        }
        self.result_data = new_data
        self.accept()

class EmuListWidget(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.config = main_window.config
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Global Paths
        paths_widget = QWidget()
        form_layout = QFormLayout(paths_widget)

        rom_path_layout = QHBoxLayout()
        self.rom_path_input = QLineEdit(self.config.get("base_rom_path"))   
        rom_path_layout.addWidget(self.rom_path_input)
        browse_rom_btn = QPushButton("Browse")
        browse_rom_btn.clicked.connect(lambda: self.browse_directory("base_rom_path", self.rom_path_input))
        rom_path_layout.addWidget(browse_rom_btn)
        form_layout.addRow("ROM Path:", rom_path_layout)

        emu_path_layout = QHBoxLayout()
        self.emu_path_input = QLineEdit(self.config.get("base_emu_path"))   
        emu_path_layout.addWidget(self.emu_path_input)
        browse_emu_btn = QPushButton("Browse")
        browse_emu_btn.clicked.connect(lambda: self.browse_directory("base_emu_path", self.emu_path_input))
        emu_path_layout.addWidget(browse_emu_btn)
        form_layout.addRow("Emu Path:", emu_path_layout)

        save_paths_btn = QPushButton("Save Paths")
        save_paths_btn.clicked.connect(self.save_paths)
        form_layout.addRow(save_paths_btn)
        layout.addWidget(paths_widget)

        # Emulator List
        layout.addSpacing(10)
        self.emu_list_layout = QVBoxLayout()
        self.emu_list_layout.setAlignment(Qt.AlignTop)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        emulator_container = QWidget()
        emulator_container.setLayout(self.emu_list_layout)
        scroll_area.setWidget(emulator_container)
        layout.addWidget(scroll_area)

        # Add Custom Emu Button
        add_emu_btn = QPushButton("＋ Add Custom Emulator")
        add_emu_btn.setStyleSheet("background: #1565c0; color: white; padding: 10px; font-weight: bold;")
        add_emu_btn.clicked.connect(self.add_custom_emulator)
        layout.addWidget(add_emu_btn)

        self.populate_emus()

    def browse_directory(self, key, line_edit):
        directory = QFileDialog.getExistingDirectory(self, "Select Folder") 
        if directory:
            line_edit.setText(directory)
            self.config.set(key, directory)

    def save_paths(self):
        self.config.set("base_rom_path", self.rom_path_input.text())        
        self.config.set("base_emu_path", self.emu_path_input.text())        
        self.main_window.log("✅ Paths saved.")
        self.populate_emus()
        self.main_window.library_tab.apply_filters()

    def populate_emus(self):
        for i in reversed(range(self.emu_list_layout.count())):
            item = self.emu_list_layout.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)

        all_emus = emulators.load_emulators()
        for emu_data in all_emus:
            emu_id = emu_data.get("id")
            if emu_id == "windows_native":
                continue
            name = emu_data.get("name")
            is_user = emu_data.get("user_defined", False)

            row = QWidget()
            row.setStyleSheet("background: #252525; border-radius: 5px; margin: 2px;")
            row_layout = QHBoxLayout(row)

            path = emu_data.get("executable_path", "")
            indicator = "✅" if path and os.path.exists(path) else ""      
            indicator_label = QLabel(indicator)
            indicator_label.setFixedWidth(24)
            row_layout.addWidget(indicator_label)

            name_label = QLabel(f"<b>{name}</b>")
            name_label.setFixedWidth(180)
            row_layout.addWidget(name_label)

            path_label = QLabel(path or "Not Set")
            path_label.setStyleSheet("color: #888;")
            row_layout.addWidget(path_label, 1)

            if is_user:
                btn_edit = QPushButton("📝 Edit")
                btn_edit.clicked.connect(lambda checked, eid=emu_id: self.edit_custom_emulator(eid))
                row_layout.addWidget(btn_edit)
                btn_del = QPushButton("🗑 Remove")
                btn_del.setStyleSheet("color: #ff5252;")
                btn_del.clicked.connect(lambda checked, eid=emu_id: self.remove_emulator(eid))
                row_layout.addWidget(btn_del)
            else:
                btn_path = QPushButton("Path")
                btn_path.clicked.connect(lambda checked, eid=emu_id: self.edit_emulator_path(eid))
                row_layout.addWidget(btn_path)
                btn_latest = QPushButton("⬇️ Latest")
                btn_latest.clicked.connect(lambda checked, n=name: self.main_window.dl_emu(n))
                row_layout.addWidget(btn_latest)
                btn_fw = QPushButton("📂 Firmware")
                btn_fw.clicked.connect(lambda checked, n=name: self.main_window.open_fw(n))
                row_layout.addWidget(btn_fw)

            self.emu_list_layout.addWidget(row)

    def add_custom_emulator(self):
        dialog = EmulatorEditDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            all_emus = emulators.load_emulators()
            all_emus.append(dialog.result_data)
            emulators.save_emulators(all_emus)
            self.main_window.log(f"✅ Added emulator: {dialog.result_data['name']}")
            self.populate_emus()
            self.main_window.emulators_tab.refresh_all()

    def edit_custom_emulator(self, emu_id):
        all_emus = emulators.load_emulators()
        emu_idx = next((i for i, e in enumerate(all_emus) if e["id"] == emu_id), -1)
        if emu_idx == -1: return
        dialog = EmulatorEditDialog(emu_data=all_emus[emu_idx], parent=self)
        if dialog.exec() == QDialog.Accepted:
            all_emus[emu_idx] = dialog.result_data
            emulators.save_emulators(all_emus)
            self.main_window.log(f"✅ Updated emulator: {dialog.result_data['name']}")
            self.populate_emus()
            self.main_window.emulators_tab.refresh_all()

    def remove_emulator(self, emu_id):
        all_emus = emulators.load_emulators()
        emu = next((e for e in all_emus if e["id"] == emu_id), None)        
        if not emu: return
        reply = QMessageBox.question(self, "Remove Emulator", f"Are you sure you want to remove {emu['name']}?")
        if reply == QMessageBox.Yes:
            all_emus = [e for e in all_emus if e["id"] != emu_id]
            emulators.save_emulators(all_emus)
            self.main_window.log(f"🗑 Removed emulator: {emu['name']}")   
            self.populate_emus()
            self.main_window.emulators_tab.refresh_all()

    def edit_emulator_path(self, emu_id):
        all_emus = emulators.load_emulators()
        emu = next((e for e in all_emus if e["id"] == emu_id), None)        
        if not emu: return
        start_dir = os.path.dirname(emu.get("executable_path")) if emu.get("executable_path") else ""
        if not start_dir or not os.path.exists(start_dir): start_dir = self.config.get("base_emu_path")
        file_path, _ = QFileDialog.getOpenFileName(self, f"Select {emu['name']} Executable", start_dir, "Executables (*.exe)")
        if file_path:
            emu["executable_path"] = file_path
            emulators.save_emulators(all_emus)
            self.main_window.log(f"✅ {emu['name']} path updated.")        
            self.populate_emus()
            self.main_window.library_tab.apply_filters()

class SyncSettingsWidget(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.config = main_window.config
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)

        layout.addWidget(QLabel("<h2>Emulator Save Sync</h2>"))
        layout.addWidget(QLabel("<p style='color:#888;'>Choose which emulators sync saves to RomM and set conflict behavior.</p>"))
        self.emu_sync_layout = QVBoxLayout()
        self.emu_sync_layout.setAlignment(Qt.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(250)
        container = QWidget()
        container.setLayout(self.emu_sync_layout)
        scroll.setWidget(container)
        layout.addWidget(scroll)

        layout.addSpacing(20)
        layout.addWidget(QLabel("<h2>Auto-Sync Interval</h2>"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(30, 600)
        self.interval_spin.setSingleStep(30)
        self.interval_spin.setSuffix(" seconds")
        self.interval_spin.setValue(self.config.get("sync_interval_seconds", 120))
        self.interval_spin.valueChanged.connect(lambda v: self.config.set("sync_interval_seconds", v))
        layout.addWidget(self.interval_spin)
        layout.addStretch()
        self.populate_emu_sync()

    def populate_emu_sync(self):
        for i in reversed(range(self.emu_sync_layout.count())):
            item = self.emu_sync_layout.itemAt(i)
            if item and item.widget(): item.widget().setParent(None)        

        # 1. Real emulators
        all_emus = emulators.load_emulators()
        emu_data_list = []
        for e in all_emus:
            emu_data_list.append({
                "id": e["id"],
                "name": e["name"],
                "sync_enabled": e.get("sync_enabled", True),
                "conflict_behavior": e.get("conflict_behavior", "ask"),     
                "platform_slugs": e.get("platform_slugs", []),
                "is_config_based": False
            })

        # 2. Synthetic Windows Entry
        emu_data_list.append({
            "id": "windows_native",
            "name": "Windows (Native)",
            "sync_enabled": self.config.get("windows_sync_enabled", True),  
            "conflict_behavior": self.config.get("windows_conflict_behavior", "ask"),
            "platform_slugs": ["windows"],
            "is_config_based": True
        })

        for emu in emu_data_list:
            row = QWidget()
            row.setStyleSheet(f"""
                QWidget {{ background: #252525; border-radius: 5px; margin: 2px; }}
                QCheckBox {{ color: #cccccc; font-size: 11px; spacing: 8px; border: none; }}
                QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #555; border-radius: 3px; background: #1a1a1a; }}
                QCheckBox::indicator:checked {{ background: #0d6efd; border: 1px solid #0d6efd; image: url("{_get_check_icon_path()}"); }}
                QCheckBox::indicator:hover {{ border: 1px solid #0d6efd; }}
            """)
            rl = QHBoxLayout(row)
            rl.setSpacing(8)

            check = QCheckBox()
            check.setFixedWidth(20)
            check.setChecked(emu["sync_enabled"])

            name_label = QLabel(f"<b>{emu['name']}</b>")
            name_label.setMinimumWidth(160)

            # Platform badges
            badges_text = ", ".join(emu["platform_slugs"][:3]).upper()      
            badges = QLabel(badges_text)
            badges.setStyleSheet("color: #888; font-size: 10px;")

            lbl_on = QLabel("On conflict:")
            lbl_on.setStyleSheet("color: #888; font-size: 10px;")
            lbl_on.setFixedWidth(65)

            conflict_combo = QComboBox()
            conflict_combo.setFixedWidth(150)
            conflict_combo.addItem("Always Ask", "ask")
            conflict_combo.addItem("Prefer Cloud", "prefer_cloud")
            conflict_combo.addItem("Prefer Local", "prefer_local")

            idx = conflict_combo.findData(emu["conflict_behavior"])
            if idx >= 0: conflict_combo.setCurrentIndex(idx)

            # Connections
            check.toggled.connect(lambda checked, e=emu, c=conflict_combo, nl=name_label: self.save_emu_sync(e, checked, c, nl))
            conflict_combo.currentIndexChanged.connect(lambda idx, e=emu, c=conflict_combo: self.save_emu_conflict(e, c.itemData(idx)))

            # Initial state
            conflict_combo.setEnabled(emu["sync_enabled"])
            name_label.setEnabled(emu["sync_enabled"])

            rl.addWidget(check)
            rl.addWidget(name_label)
            rl.addWidget(badges, 1)
            rl.addWidget(lbl_on)
            rl.addWidget(conflict_combo)

            self.emu_sync_layout.addWidget(row)

    def save_emu_sync(self, emu_data, enabled, combo, label):
        combo.setEnabled(enabled)
        label.setEnabled(enabled)

        if emu_data["is_config_based"]:
            self.config.set("windows_sync_enabled", enabled)
        else:
            all_emus = emulators.load_emulators()
            emu = next((e for e in all_emus if e["id"] == emu_data["id"]), None)
            if emu:
                emu["sync_enabled"] = enabled
                emulators.save_emulators(all_emus)

        logging.info(f"🔄 Sync {'enabled' if enabled else 'disabled'} for {emu_data['name']}")
        self.main_window.log(f"🔄 Sync {'enabled' if enabled else 'disabled'} for {emu_data['name']}")

    def save_emu_conflict(self, emu_data, behavior):
        if emu_data["is_config_based"]:
            self.config.set("windows_conflict_behavior", behavior)
        else:
            all_emus = emulators.load_emulators()
            emu = next((e for e in all_emus if e["id"] == emu_data["id"]), None)
            if emu:
                emu["conflict_behavior"] = behavior
                emulators.save_emulators(all_emus)

        logging.info(f"⚙ {emu_data['name']} conflict behavior: {behavior}")
        self.main_window.log(f"⚙ {emu_data['name']} conflict: {behavior}")

class PlatformAssignWidget(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.config = main_window.config
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.addWidget(QLabel("<h2>Platform Assignments</h2>"))
        layout.addWidget(QLabel("<p style='color:#888;'>Assign which emulator to use for each platform.</p>"))
        self.assign_layout = QFormLayout()
        container = QWidget()
        container.setLayout(self.assign_layout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        layout.addWidget(scroll)
        self.populate_assignments()

    def populate_assignments(self):
        for i in reversed(range(self.assign_layout.count())):
            item = self.assign_layout.itemAt(i)
            if item and item.widget(): item.widget().setParent(None)        
        all_games = getattr(self.main_window, "all_games", [])
        platforms = sorted(list(set(g.get("platform_slug") for g in all_games if g.get("platform_slug"))))
        all_emus = emulators.load_emulators()
        assignments = self.config.get("platform_assignments", {})
        for slug in platforms:
            combo = QComboBox()
            matching_emus = [e for e in all_emus if slug in e.get("platform_slugs", [])]
            for emu in matching_emus: combo.addItem(emu["name"], emu["id"]) 
            assigned_id = assignments.get(slug)
            if assigned_id:
                idx = combo.findData(assigned_id)
                if idx >= 0: combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(lambda idx, s=slug, c=combo: self.save_assignment(s, c.itemData(idx)))
            self.assign_layout.addRow(QLabel(f"<b>{slug.upper()}</b>"), combo)

    def save_assignment(self, platform_slug, emu_id):
        all_emus = emulators.load_emulators()
        emu = next((e for e in all_emus if e["id"] == emu_id), None)        
        assignments = self.config.get("platform_assignments", {})
        assignments[platform_slug] = emu_id
        self.config.set("platform_assignments", assignments)
        self.main_window.log(f"🕹 {platform_slug.upper()} assigned to {emu['name'] if emu else emu_id}")

class EmulatorsTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.sub_tabs = QTabWidget()
        self.sub_tabs.setStyleSheet("""
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
        self.emu_list = EmuListWidget(main_window)
        self.sync_settings = SyncSettingsWidget(main_window)
        self.platform_assign = PlatformAssignWidget(main_window)
        self.sub_tabs.addTab(self.emu_list, "Emulators")
        self.sub_tabs.addTab(self.sync_settings, "Sync")
        self.sub_tabs.addTab(self.platform_assign, "Platforms")        

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.sub_tabs)

    def populate_emus(self): self.emu_list.populate_emus()
    def refresh_all(self):
        self.emu_list.populate_emus()
        self.sync_settings.populate_emu_sync()
        self.platform_assign.populate_assignments()
