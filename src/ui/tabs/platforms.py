import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QScrollArea, QFormLayout, QComboBox)
from PySide6.QtCore import Qt
from src import emulators

class PlatformTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.config = main_window.config
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        layout.addWidget(QLabel("<h2>Platform Assignments</h2>"))
        layout.addWidget(QLabel("<p style='color:#888;'>Assign which emulator to use for each platform. Changes take effect immediately.</p>"))
        
        self.assign_layout = QFormLayout()
        self.assign_layout.setSpacing(15)
        
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
            if item and item.widget():
                item.widget().setParent(None)
        
        all_games = getattr(self.main_window, "all_games", [])
        platforms = sorted(list(set(g.get("platform_slug") for g in all_games if g.get("platform_slug"))))
        
        all_emus = emulators.load_emulators()
        assignments = self.config.get("platform_assignments", {})
        
        for slug in platforms:
            combo = QComboBox()
            # Find emus that support this slug
            matching_emus = [e for e in all_emus if slug in e.get("platform_slugs", [])]
            
            for emu in matching_emus:
                combo.addItem(emu["name"], emu["id"])
            
            assigned_id = assignments.get(slug)
            if assigned_id:
                idx = combo.findData(assigned_id)
                if idx >= 0: combo.setCurrentIndex(idx)
            
            # Use a wrapper to pass values correctly
            combo.currentIndexChanged.connect(lambda idx, s=slug, c=combo: self.save_assignment(s, c.itemData(idx)))
            
            # Prettier label
            label = QLabel(f"<b>{slug.upper()}</b>")
            label.setFixedWidth(120)
            self.assign_layout.addRow(label, combo)

    def save_assignment(self, platform_slug, emu_id):
        all_emus = emulators.load_emulators()
        emu = next((e for e in all_emus if e["id"] == emu_id), None)
        emu_name = emu["name"] if emu else emu_id
        
        assignments = self.config.get("platform_assignments", {})
        assignments[platform_slug] = emu_id
        self.config.set("platform_assignments", assignments)
        self.main_window.log(f"🎮 {platform_slug.upper()} assigned to {emu_name}")
