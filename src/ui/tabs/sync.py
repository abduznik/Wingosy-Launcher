import os
import logging
from pathlib import Path
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QScrollArea, QFormLayout, 
                             QComboBox, QSpinBox, QCheckBox)
from PySide6.QtCore import Qt
from src import emulators

class SyncTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.config = main_window.config
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Section 1: Per-Emulator Sync Toggle
        layout.addWidget(QLabel("<h2>Emulator Save Sync</h2>"))
        layout.addWidget(QLabel("<p style='color:#888;'>Choose which emulators sync saves to RomM.</p>"))
        
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
        
        # Section 2: Global Conflict Behavior
        layout.addWidget(QLabel("<h2>Conflict Resolution</h2>"))
        layout.addWidget(QLabel("<p style='color:#888;'>What happens when local and cloud saves differ on launch?</p>"))
        
        conflict_layout = QHBoxLayout()
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItem("Always Ask", "ask")
        self.conflict_combo.addItem("Prefer Cloud Save", "prefer_cloud")
        self.conflict_combo.addItem("Prefer Local Save", "prefer_local")
        
        current_behavior = self.config.get("conflict_behavior", "ask")
        idx = self.conflict_combo.findData(current_behavior)
        if idx >= 0: self.conflict_combo.setCurrentIndex(idx)
        self.conflict_combo.currentIndexChanged.connect(self.save_conflict_behavior)
        
        conflict_layout.addWidget(self.conflict_combo)
        conflict_layout.addStretch()
        layout.addLayout(conflict_layout)
        
        layout.addSpacing(20)
        
        # Section 3: Auto-Sync Interval
        layout.addWidget(QLabel("<h2>Auto-Sync Interval</h2>"))
        layout.addWidget(QLabel("<p style='color:#888;'>How often to check for save changes while a game is running.</p>"))
        
        interval_layout = QHBoxLayout()
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(30, 600)
        self.interval_spin.setSingleStep(30)
        self.interval_spin.setSuffix(" seconds")
        self.interval_spin.setValue(self.config.get("sync_interval_seconds", 120))
        self.interval_spin.valueChanged.connect(self.save_sync_interval)
        
        interval_layout.addWidget(self.interval_spin)
        interval_layout.addStretch()
        layout.addLayout(interval_layout)
        
        layout.addStretch()
        
        self.populate_emu_sync()

    def populate_emu_sync(self):
        for i in reversed(range(self.emu_sync_layout.count())):
            item = self.emu_sync_layout.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)
        
        all_emus = emulators.load_emulators()
        for emu in all_emus:
            row = QWidget()
            row.setStyleSheet("background: #252525; border-radius: 5px; margin: 2px;")
            rl = QHBoxLayout(row)
            
            check = QCheckBox()
            check.setChecked(emu.get("sync_enabled", True))
            check.toggled.connect(lambda checked, eid=emu["id"]: self.toggle_emu_sync(eid, checked))
            rl.addWidget(check)
            
            name_label = QLabel(f"<b>{emu['name']}</b>")
            name_label.setFixedWidth(200)
            rl.addWidget(name_label)
            
            # Platform badges
            badges_layout = QHBoxLayout()
            badges_layout.setSpacing(4)
            for slug in emu.get("platform_slugs", [])[:5]: # Show first 5
                badge = QLabel(slug.upper())
                badge.setStyleSheet("background: #444; font-size: 9px; padding: 2px 4px; border-radius: 3px;")
                badges_layout.addWidget(badge)
            badges_layout.addStretch()
            rl.addLayout(badges_layout, 1)
            
            self.emu_sync_layout.addWidget(row)
            
        # Also add Windows Native if not in emulators.json list (it should be now)
        # But we also have a specific config for Windows sync enabled?
        # Requirement says: Include Windows Native in this list. 
        # and store in config.json as "windows_sync_enabled".
        # Let's find it in all_emus first.
        win_native = next((e for e in all_emus if e["id"] == "windows_native"), None)
        # We'll rely on the emulators.json entry for the toggle if it's there,
        # but the requirement says specifically store in config.json.
        # I will sync the two or just use the config one for Windows specifically.

    def toggle_emu_sync(self, emu_id, enabled):
        all_emus = emulators.load_emulators()
        emu = next((e for e in all_emus if e["id"] == emu_id), None)
        if emu:
            emu["sync_enabled"] = enabled
            emulators.save_emulators(all_emus)
            logging.info(f"🔄 Sync {'enabled' if enabled else 'disabled'} for {emu['name']}")
            self.main_window.log(f"🔄 Sync {'enabled' if enabled else 'disabled'} for {emu['name']}")
            
            # Special case for Windows Native to keep config in sync
            if emu_id == "windows_native":
                self.config.set("windows_sync_enabled", enabled)

    def save_conflict_behavior(self, index):
        val = self.conflict_combo.itemData(index)
        self.config.set("conflict_behavior", val)
        self.main_window.log(f"🔄 Conflict behavior set to: {self.conflict_combo.currentText()}")

    def save_sync_interval(self, value):
        self.config.set("sync_interval_seconds", value)
        # No restart needed, watcher reads it fresh
