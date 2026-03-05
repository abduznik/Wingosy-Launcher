import os
from pathlib import Path
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QScrollArea, QGridLayout, 
                             QComboBox, QSizePolicy)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QImage

from src.ui.threads import ImageFetcher
from src.ui.widgets import format_speed, RETROARCH_PLATFORMS, elide_text

class GameCard(QWidget):
    clicked = Signal(object)
    def __init__(self, game, client, config, sync_cache):
        super().__init__()
        self.game, self.client, self.config, self.sync_cache = game, client, config, sync_cache
        self.setFixedSize(160, 240)
        self.setStyleSheet("""
            QWidget { background: #1e1e1e; border-radius: 8px; }
            QWidget:hover { background: #2c2c2c; border: 2px solid #1565c0; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        self.img_label = QLabel()
        self.img_label.setFixedSize(150, 200)
        self.img_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.img_label)
        
        # State Indicators as floating labels
        # Local ROM check
        rom_exists = False
        rom_name = game.get('fs_name')
        platform = game.get('platform_slug')
        base_rom = config.get("base_rom_path")
        if rom_name and base_rom:
            if os.path.exists(Path(base_rom) / platform / rom_name) or os.path.exists(Path(base_rom) / rom_name):
                rom_exists = True
        
        if rom_exists:
            self.local_indicator = QLabel("✓", self)
            self.local_indicator.setStyleSheet("""
                color: white;
                background-color: #4caf50;
                border-radius: 7px;
                font-size: 9px;
                font-weight: bold;
                padding: 1px 3px;
            """)
            self.local_indicator.setFixedSize(14, 14)
            self.local_indicator.setAlignment(Qt.AlignCenter)
            self.local_indicator.move(4, 4)
            self.local_indicator.show()
        
        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("color: white; font-weight: bold; border: none;")
        self.title_label.setFixedWidth(150)
        self.title_label.setWordWrap(False)
        self.title_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.title_label.setText(elide_text(game.get('name', 'Unknown')))
        self.title_label.setToolTip(game.get('name', 'Unknown'))
        layout.addWidget(self.title_label)
        self.fetcher = None

    def start_image_fetch(self, main_window, generation):
        url = self.client.get_cover_url(self.game)
        if url:
            self.fetcher = ImageFetcher(self.game['id'], url)
            self.fetcher.finished.connect(self.set_image)
            self.fetcher.finished.connect(lambda gid, pix: main_window._on_image_fetched(self.fetcher, generation))
            self.fetcher.start()
            return self.fetcher
        return None

    def set_image(self, game_id, pixmap):
        self.img_label.setPixmap(pixmap.scaled(150, 200, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))

    def mouseReleaseEvent(self, event): 
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.game)

class LibraryTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.client = main_window.client
        self.config = main_window.config
        
        layout = QVBoxLayout(self)
        
        # Filter controls
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter games (Ctrl+F)...")
        self.search_input.textChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.search_input)
        
        filter_layout.addWidget(QLabel("Platform:"))
        self.platform_filter = QComboBox()
        self.platform_filter.addItem("All Platforms")
        self.platform_filter.currentTextChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.platform_filter)
        
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.main_window.fetch_library_and_populate)
        filter_layout.addWidget(self.refresh_btn)
        
        self.retry_btn = QPushButton("⚠️ Retry")
        self.retry_btn.setStyleSheet("background: #e65100; color: white; padding: 4px 10px;")
        self.retry_btn.setVisible(False)
        self.retry_btn.clicked.connect(self.main_window.fetch_library_and_populate)
        filter_layout.addWidget(self.retry_btn)
        
        layout.addLayout(filter_layout)

        # Grid area
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.grid_widget)
        layout.addWidget(scroll_area)

    def apply_filters(self):
        text = self.search_input.text().lower()
        platform = self.platform_filter.currentText()
        filtered = [g for g in self.main_window.all_games if (text in g.get('name', '').lower() or text in g.get('fs_name', '').lower()) and (platform == "All Platforms" or g.get('platform_display_name') == platform)]
        self.populate_grid(filtered)

    def populate_grid(self, games):
        self.main_window.fetch_generation += 1
        my_generation = self.main_window.fetch_generation
        self.main_window.image_fetch_queue = []
        self.retry_btn.setVisible(False)
        
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)
        
        row, col = 0, 0
        all_cards = []
        sync_cache = self.main_window.watcher.sync_cache if self.main_window.watcher else {}
        for game in games:
            card = GameCard(game, self.client, self.config, sync_cache)
            card.clicked.connect(lambda g=game: self.open_detail(g))
            self.grid_layout.addWidget(card, row, col)
            all_cards.append(card)
            col += 1
            if col >= 6:
                col = 0
                row += 1
        
        for i, card in enumerate(all_cards):
            if i < 10:
                fetcher = card.start_image_fetch(self.main_window, my_generation)
                if fetcher:
                    self.main_window.active_image_fetchers.append(fetcher)
            else:
                self.main_window.image_fetch_queue.append(card)

    def open_detail(self, game):
        # Local import to avoid circular dependency with dialogs.py
        from src.ui.dialogs import GameDetailDialog
        GameDetailDialog(game, self.client, self.config, self.main_window, self.main_window).exec()

    def show_empty_message(self, message):
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                item.widget().setParent(None)
        
        empty_label = QLabel(message)
        empty_label.setAlignment(Qt.AlignCenter)
        empty_label.setStyleSheet("color: #888; font-size: 14px; padding: 40px;")
        self.grid_layout.addWidget(empty_label, 0, 0)
        self.retry_btn.setVisible(True)
