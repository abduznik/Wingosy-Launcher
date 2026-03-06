import os
from pathlib import Path
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QScrollArea, QGridLayout, 
                             QComboBox, QSizePolicy)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap, QImage

from src.ui.threads import ImageFetcher
from src.ui.widgets import format_speed, elide_text
from src.platforms import RETROARCH_PLATFORMS, platform_matches

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
        
        # State Indicators
        rom_exists = game.get('_local_exists', False)
        
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
        
        has_cloud_save = str(game.get('id', '')) in sync_cache
        if has_cloud_save:
            self.cloud_indicator = QLabel("☁", self)
            self.cloud_indicator.setStyleSheet("""
                color: white;
                background-color: #1565c0;
                border-radius: 7px;
                font-size: 9px;
                font-weight: bold;
                padding: 1px 3px;
            """)
            self.cloud_indicator.setFixedSize(14, 14)
            self.cloud_indicator.setAlignment(Qt.AlignCenter)
            self.cloud_indicator.move(22, 4)
            self.cloud_indicator.show()
        
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
        self._all_cards = []       # all GameCard widgets currently in grid
        self._render_generation = 0  # incremented to cancel in-flight renders
        self._loading_label = None
        self._pending_games = []    # games not yet rendered
        self._load_more_label = None  # "Load more..." indicator at bottom
        self.LOAD_BATCH = 200
        self._is_loading_batch = False  # guard against concurrent loads
        
        self._scroll_debounce = QTimer()
        self._scroll_debounce.setSingleShot(True)
        self._scroll_debounce.setInterval(150)  # ms cooldown
        self._scroll_debounce.timeout.connect(self._do_load_batch)
        
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
        self.refresh_btn.clicked.connect(lambda: self.main_window.fetch_library_and_populate(force_refresh=True))
        filter_layout.addWidget(self.refresh_btn)
        
        self.retry_btn = QPushButton("⚠️ Retry")
        self.retry_btn.setStyleSheet("background: #e65100; color: white; padding: 4px 10px;")
        self.retry_btn.setVisible(False)
        self.retry_btn.clicked.connect(lambda: self.main_window.fetch_library_and_populate(force_refresh=True))
        filter_layout.addWidget(self.retry_btn)
        
        layout.addLayout(filter_layout)

        # Grid area
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.grid_widget)
        # Connect scroll event to lazy loader
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll)
        layout.addWidget(self.scroll_area)

    def _on_scroll(self, value):
        """Debounce scroll events before loading next batch."""
        if not self._pending_games or self._is_loading_batch:
            return
        scrollbar = self.scroll_area.verticalScrollBar()
        max_val = scrollbar.maximum()
        if max_val <= 0:
            return
        if value >= max_val * 0.60:
            # Restart the debounce timer — only fires after 150ms of 
            # no scroll events, preventing rapid-fire batch loads
            self._scroll_debounce.start()

    def _do_load_batch(self):
        """Actually load the next batch — called after scroll debounce."""
        if not self._pending_games or self._is_loading_batch:
            return
        scrollbar = self.scroll_area.verticalScrollBar()
        max_val = scrollbar.maximum()
        value = scrollbar.value()
        if max_val <= 0 or value < max_val * 0.60:
            return

        print(f"[Library] Threshold hit — loading next batch. "
              f"Pending: {len(self._pending_games)}")
        self._is_loading_batch = True
        self._render_next_batch()

    def apply_filters(self):
        text = self.search_input.text().lower()
        platform = self.platform_filter.currentText()

        # Build filtered game list
        if platform == "⚠️ No Emulator":
            from src.platforms import RETROARCH_PLATFORMS
            all_known = set(RETROARCH_PLATFORMS)
            for emu in self.main_window.config.get("emulators", 
                                                    {}).values():
                all_known.update(emu.get("platform_slugs",
                                 [emu.get("platform_slug", "")]))
            filtered = [
                g for g in self.main_window.all_games
                if g.get("platform_slug") not in all_known
                and (not text
                     or text in g.get('name', '').lower()
                     or text in g.get('fs_name', '').lower())
            ]
        else:
            filtered = [
                g for g in self.main_window.all_games
                if (not text
                    or text in g.get('name', '').lower()
                    or text in g.get('fs_name', '').lower())
                and (platform == "All Platforms"
                     or g.get('platform_display_name') == platform
                     or g.get('platform_slug') == platform)
            ]

        platform_changed = (
            not hasattr(self, '_current_platform') or
            self._current_platform != platform
        )

        if not platform_changed and self._all_cards:
            # Same platform — just show/hide existing cards by game id
            filtered_ids = set(g.get('id') for g in filtered)
            for card in self._all_cards:
                try:
                    visible = card.game.get('id') in filtered_ids
                    card.setVisible(visible)
                except RuntimeError:
                    pass
        else:
            # Platform changed — rebuild grid
            self.populate_grid(filtered)

        print(f"[Library] Filter → {len(filtered)} games "
              f"(platform='{platform}' search='{text}')")

    def populate_grid(self, games):
        # Increment generation — any pending render callbacks will 
        # check this and abort immediately
        self._render_generation += 1
        my_gen = self._render_generation
        self.main_window.image_fetch_queue = []
        self.retry_btn.setVisible(False)
        self._all_cards = []
        self._pending_games = list(games)  # full list, render in batches
        self._scroll_debounce.stop()  # cancel any pending debounce on grid reset
        self._is_loading_batch = False
        self._current_platform = self.platform_filter.currentText()

        # Clear grid — use deleteLater for safety
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item and item.widget():
                item.widget().hide()
                item.widget().deleteLater()

        # Remove old load-more label ref
        self._load_more_label = None

        if not games:
            self.show_empty_message("No games match your search.")
            return

        # Render first batch immediately
        self._render_next_batch(my_gen)

    def _render_next_batch(self, generation=None):
        """Render the next LOAD_BATCH pending games into the grid."""
        # Use current generation if not specified
        if generation is None:
            generation = self._render_generation

        # Abort if stale
        if generation != self._render_generation:
            self._is_loading_batch = False
            return

        if not self._pending_games:
            # Remove load-more label if present
            if self._load_more_label:
                self._load_more_label.hide()
                self._load_more_label.deleteLater()
                self._load_more_label = None
            self._is_loading_batch = False
            return

        batch = self._pending_games[:self.LOAD_BATCH]
        self._pending_games = self._pending_games[self.LOAD_BATCH:]

        sync_cache = (self.main_window.watcher.sync_cache
                      if self.main_window.watcher else {})

        # Remove load-more label before adding new cards
        if self._load_more_label:
            self.grid_layout.removeWidget(self._load_more_label)
            self._load_more_label.hide()
            self._load_more_label.deleteLater()
            self._load_more_label = None

        self.grid_widget.setUpdatesEnabled(False)
        try:
            # Calculate starting row/col from existing card count
            total_so_far = len(self._all_cards)
            row = (total_so_far // 6)
            col = total_so_far % 6

            for i, game in enumerate(batch):
                if generation != self._render_generation:
                    return

                card = GameCard(game, self.client, self.config, sync_cache)
                card.clicked.connect(lambda g=game: self.open_detail(g))
                self.grid_layout.addWidget(card, row, col)
                self._all_cards.append(card)
                col += 1
                if col >= 6:
                    col = 0
                    row += 1
        finally:
            self.grid_widget.setUpdatesEnabled(True)

        print(f"[Library] Cards: {len(self._all_cards)} loaded, "
              f"{len(self._pending_games)} pending")

        # Queue image fetches for newly added cards (first 12 overall only)
        self.main_window.fetch_generation += 1
        my_fetch_gen = self.main_window.fetch_generation
        start_idx = len(self._all_cards) - len(batch)
        for i, card in enumerate(self._all_cards[start_idx:]):
            abs_idx = start_idx + i
            if abs_idx < 12:
                fetcher = card.start_image_fetch(
                    self.main_window, my_fetch_gen)
                if fetcher:
                    self.main_window.active_image_fetchers.append(fetcher)
            else:
                self.main_window.image_fetch_queue.append(card)

        # If more games remain, add a load-more indicator at the bottom
        if self._pending_games:
            remaining = len(self._pending_games)
            self._load_more_label = QLabel(
                f"⬇ Scroll down to load {remaining} more games...")
            self._load_more_label.setAlignment(Qt.AlignCenter)
            self._load_more_label.setStyleSheet(
                "color: #1e88e5; font-size: 13px; "
                "padding: 20px; background: #1a1a1a;")
            next_row = (len(self._all_cards) + 5) // 6
            self.grid_layout.addWidget(
                self._load_more_label, next_row, 0, 1, 6)

        self._is_loading_batch = False
        
        self._is_loading_batch = False

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
