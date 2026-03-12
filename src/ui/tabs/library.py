import os
import re
import logging
import ctypes
import sys
from pathlib import Path
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,   
                             QPushButton, QLineEdit, QScrollArea, QGridLayout,
                             QComboBox, QSizePolicy, QAbstractItemView, QGraphicsDropShadowEffect, QStackedWidget)
from PySide6.QtCore import Qt, Signal, QTimer, QEvent, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPixmap, QImage, QColor

from src.ui.threads import ImageFetcher
from src.ui.widgets import format_speed, elide_text
from src.platforms import RETROARCH_PLATFORMS, platform_matches
from src import emulators

CONTROLLER_MAPS = {
    "xinput": {
        "confirm":  0x1000,  # A button
        "back":     0x2000,  # B button
        "up":       0x0001,  # DPAD UP
        "down":     0x0002,  # DPAD DOWN
        "left":     0x0004,  # DPAD LEFT
        "right":    0x0008,  # DPAD RIGHT
        "stick_deadzone": 8000,
    },
    "ps4": {
        "confirm":  0x1000,  # ✕ (Cross)
        "back":     0x2000,  # ○ (Circle)
        "up":       0x0001,
        "down":     0x0002,
        "left":     0x0004,
        "right":    0x0008,
        "stick_deadzone": 8000,
    },
    "ps5": {
        "confirm":  0x1000,  # ✕ (Cross)
        "back":     0x2000,  # ○ (Circle)
        "up":       0x0001,
        "down":     0x0002,
        "left":     0x0004,
        "right":    0x0008,
        "stick_deadzone": 8000,
    },
    "switch": {
        "confirm":  0x1000,  # A (right)
        "back":     0x2000,  # B (bottom)
        "up":       0x0001,
        "down":     0x0002,
        "left":     0x0004,
        "right":    0x0008,
        "stick_deadzone": 8000,
    },
    "generic": {
        "confirm":  0x1000,
        "back":     0x2000,
        "up":       0x0001,
        "down":     0x0002,
        "left":     0x0004,
        "right":    0x0008,
        "stick_deadzone": 10000,
    },
}

class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]

class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", ctypes.c_ulong),
        ("Gamepad", XINPUT_GAMEPAD),
    ]

class SmoothScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._scroll_animation = QPropertyAnimation(self.verticalScrollBar(), b"value")
        self._scroll_animation.setDuration(180)
        self._scroll_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._target_value = 0

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        step = 120  # pixels per scroll tick
        self._target_value = max(
            self.verticalScrollBar().minimum(),
            min(
                self.verticalScrollBar().maximum(),
                (self._target_value if self._scroll_animation.state() == QPropertyAnimation.Running else self.verticalScrollBar().value()) - (delta / 120 * step)
            )
        )
        self._scroll_animation.stop()
        self._scroll_animation.setStartValue(self.verticalScrollBar().value())
        self._scroll_animation.setEndValue(int(self._target_value))
        self._scroll_animation.start()

class GameCard(QWidget):
    clicked = Signal(object)
    def __init__(self, game, client, config, sync_cache):
        super().__init__()
        self.game, self.client, self.config, self.sync_cache = game, client, config, sync_cache
        self._selected = False
        
        self.update_style()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.img_label = QLabel()
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
        self.title_label.setWordWrap(False)
        self.title_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        
        display_name = game.get('name', 'Unknown')
        fs_name = game.get('fs_name', '')
        disc_match = re.search(r'\((disc|disk|cd)\s*(\d+)\)', fs_name, re.IGNORECASE)
        if disc_match:
            disc_num = disc_match.group(2)
            display_name = f"[D{disc_num}] {display_name}"
            
        self.title_label.setText(elide_text(display_name))   
        self.title_label.setToolTip(display_name)
        layout.addWidget(self.title_label)
        self.disc_label = None
        self.fetcher = None
        self._full_pixmap = None

    def set_local_exists(self, exists):
        """Dynamically add or remove the local ROM checkmark."""
        self.game['_local_exists'] = exists
        if exists:
            if not hasattr(self, 'local_indicator'):
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
        elif hasattr(self, 'local_indicator'):
            self.local_indicator.hide()

    def set_selected(self, selected):
        self._selected = selected
        if selected:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(20)
            shadow.setColor(QColor(13, 110, 253, 150))
            shadow.setOffset(0, 0)
            self.setGraphicsEffect(shadow)
        else:
            self.setGraphicsEffect(None)
        self.update_style()

    def update_style(self):
        border = "2px solid #0d6efd" if self._selected else "none"
        bg = "#2c2c2c" if self._selected else "#1e1e1e"
        self.setStyleSheet(f"""
            GameCard {{ 
                background: {bg}; 
                border-radius: 8px; 
                border: {border};
            }}
            GameCard:hover {{ background: #2c2c2c; border: 2px solid #1565c0; }}
        """)

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
        try:
            self._full_pixmap = pixmap
            w = self.img_label.width()
            h = self.img_label.height()
            if w > 0 and h > 0:
                self.img_label.setPixmap(
                    pixmap.scaled(w, h,
                        Qt.KeepAspectRatioByExpanding,
                        Qt.SmoothTransformation)
                )
        except RuntimeError:
            # Widget might have been deleted while thread was finishing
            pass

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.game)

class LibraryTab(QWidget):
    def __init__(self, main_window):
        # ... (rest of __init__ is unchanged)
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
        self._total_server_games = 0
        self._loaded_count = 0
        self._selected_index = -1

        self._scroll_debounce = QTimer()
        self._scroll_debounce.setSingleShot(True)
        self._scroll_debounce.setInterval(150)  # ms cooldown
        self._scroll_debounce.timeout.connect(self._do_load_batch)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Filter controls (Header)
        self.filter_widget = QWidget()
        filter_layout = QHBoxLayout(self.filter_widget)
        filter_layout.setContentsMargins(10, 10, 10, 10)
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

        self.main_layout.addWidget(self.filter_widget)

        # Installation Toggle Bar
        self.install_filter_widget = QWidget()
        self.install_filter_widget.setStyleSheet("background: #111; border-bottom: 1px solid #222;")
        install_layout = QHBoxLayout(self.install_filter_widget)
        install_layout.setContentsMargins(10, 5, 10, 5)
        install_layout.setSpacing(5)

        self.install_filter_group = []
        self.current_install_filter = "all" # "all", "installed", "not_installed"

        for label, filter_id in [("All", "all"), ("Installed", "installed"), ("Not Installed", "not_installed")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            if filter_id == "all": btn.setChecked(True)
            
            btn.setStyleSheet("""
                QPushButton {
                    background: #222;
                    color: #888;
                    border: none;
                    padding: 6px 15px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #333;
                    color: #fff;
                }
                QPushButton:checked {
                    background: #0d6efd;
                    color: #fff;
                }
            """)
            btn.clicked.connect(lambda checked, fid=filter_id: self._set_install_filter(fid))
            install_layout.addWidget(btn)
            self.install_filter_group.append(btn)
        
        install_layout.addStretch()
        self.main_layout.addWidget(self.install_filter_widget)

        # Stack area
        self.stack = QStackedWidget()
        
        # Page 0: Grid
        self.grid_page = QWidget()
        grid_page_layout = QVBoxLayout(self.grid_page)
        grid_page_layout.setContentsMargins(0, 0, 0, 0)
        
        # Grid area inside scroll
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.scroll_area = SmoothScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.grid_widget)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.scroll_area.viewport().installEventFilter(self)

        self._resize_debounce = QTimer()
        self._resize_debounce.setSingleShot(True)
        self._resize_debounce.setInterval(80)
        self._resize_debounce.timeout.connect(self._resize_all_cards)       

        grid_page_layout.addWidget(self.scroll_area)

        # Status label
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #bbb; padding: 5px; background: #222; border-top: 1px solid #333;")
        self.status_label.setVisible(False)
        grid_page_layout.addWidget(self.status_label)
        
        self.stack.addWidget(self.grid_page)
        
        # Page 1: Detail Panel (placeholder)
        self.detail_panel = None
        
        self.main_layout.addWidget(self.stack, 1)
        
        # Gamepad support via XInput polling
        self._last_buttons = 0
        self._last_axis = [0.0, 0.0]
        self._controller_lost_count = 0
        self.gamepad_timer = QTimer(self)
        self.gamepad_timer.timeout.connect(self._poll_gamepad)
        if sys.platform == 'win32':
            try:
                self.xinput = ctypes.windll.xinput1_4
                self.gamepad_timer.start(100) # 100ms polling
            except Exception:
                try:
                    self.xinput = ctypes.windll.xinput1_3
                    self.gamepad_timer.start(100)
                except Exception:
                    logging.debug("[Library] XInput unavailable — gamepad support disabled")
        else:
            logging.debug("[Library] Gamepad support currently only available on Windows via XInput")

    def _poll_gamepad(self):
        if not hasattr(self, 'xinput'):
            return

        controller_type = self.config.get("controller_type", "xinput")
        mapping = CONTROLLER_MAPS.get(controller_type, CONTROLLER_MAPS["xinput"])
        
        state = XINPUT_STATE()
        res = self.xinput.XInputGetState(0, ctypes.byref(state))
        
        if res == 0:
            # Controller connected
            self._controller_lost_count = 0
            if hasattr(self.main_window, 'title_bar'):
                self.main_window.title_bar.gamepad_indicator.setVisible(True)
        else:
            # Controller disconnected
            self._controller_lost_count += 1
            if self._controller_lost_count >= 3:
                if hasattr(self.main_window, 'title_bar'):
                    self.main_window.title_bar.gamepad_indicator.setVisible(False)
            return

        buttons = state.Gamepad.wButtons
        lx = state.Gamepad.sThumbLX
        ly = state.Gamepad.sThumbLY
        dz = mapping["stick_deadzone"]
        
        # Detect new presses only (not holds)
        prev = getattr(self, '_prev_buttons', 0)
        prev_lx = getattr(self, '_prev_lx', 0)
        prev_ly = getattr(self, '_prev_ly', 0)
        
        def pressed(mask):
            return (buttons & mask) and not (prev & mask)

        if pressed(mapping["up"]):    self._gamepad_up()
        if pressed(mapping["down"]):  self._gamepad_down()
        if pressed(mapping["left"]):  self._gamepad_left()
        if pressed(mapping["right"]): self._gamepad_right()
        if pressed(mapping["confirm"]): self._gamepad_confirm()
        if pressed(mapping["back"]):    self._gamepad_back()

        # Left stick — only trigger on crossing deadzone threshold
        stick_up    = ly >  dz and prev_ly <= dz
        stick_down  = ly < -dz and prev_ly >= -dz
        stick_left  = lx < -dz and prev_lx >= -dz
        stick_right = lx >  dz and prev_lx <= dz
        
        if stick_up:    self._gamepad_up()
        if stick_down:  self._gamepad_down()
        if stick_left:  self._gamepad_left()
        if stick_right: self._gamepad_right()

        self._prev_buttons = buttons
        self._prev_lx = lx
        self._prev_ly = ly

    def _gamepad_up(self):      self._on_nav_key(Qt.Key_Up)
    def _gamepad_down(self):    self._on_nav_key(Qt.Key_Down)
    def _gamepad_left(self):    self._on_nav_key(Qt.Key_Left)
    def _gamepad_right(self):   self._on_nav_key(Qt.Key_Right)
    def _gamepad_confirm(self): self._on_nav_key(Qt.Key_Return)
    def _gamepad_back(self):    self._on_nav_key(Qt.Key_Escape)

    def keyPressEvent(self, event):
        if self._on_nav_key(event.key()):
            event.accept()
        else:
            super().keyPressEvent(event)

    def _on_nav_key(self, key):
        if not self._all_cards: return False
        
        visible_cards = [c for c in self._all_cards if c.isVisible()]
        if not visible_cards: return False
        
        if self._selected_index == -1:
            if key in [Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down]:
                self._select_card(0, visible_cards)
                return True
            return False

        _, _, cols = self._get_card_size()
        idx = self._selected_index
        
        if key == Qt.Key_Right:
            idx = min(len(visible_cards) - 1, idx + 1)
        elif key == Qt.Key_Left:
            idx = max(0, idx - 1)
        elif key == Qt.Key_Down:
            idx = min(len(visible_cards) - 1, idx + cols)
        elif key == Qt.Key_Up:
            idx = max(0, idx - cols)
        elif key == Qt.Key_Return:
            self.open_detail(visible_cards[idx].game)
            return True
        elif key == Qt.Key_Escape:
            if self.stack.currentWidget() == self.detail_panel:
                self._close_detail()
            else:
                self._select_card(-1, visible_cards)
            return True
        else:
            return False
            
        self._select_card(idx, visible_cards)
        return True

    def _select_card(self, index, visible_cards):
        if self._selected_index != -1 and self._selected_index < len(visible_cards):
            visible_cards[self._selected_index].set_selected(False)
            
        self._selected_index = index
        if index != -1:
            card = visible_cards[index]
            card.set_selected(True)
            self.scroll_area.ensureWidgetVisible(card)

    def set_status(self, text, color=None):
        if not text:
            self.status_label.setVisible(False)
            return
        self.status_label.setText(text)
        if color:
            self.status_label.setStyleSheet(f"color: {color}; padding: 5px; background: #222; border-top: 1px solid #333;")
        else:
            self.status_label.setStyleSheet("color: #bbb; padding: 5px; background: #222; border-top: 1px solid #333;")
        self.status_label.setVisible(True)

    def append_batch(self, games):
        """Append a batch of games to the grid without full re-render."""   
        sync_cache = (self.main_window.watcher.sync_cache
                      if self.main_window.watcher else {})

        card_w, card_h, cols_per_row = self._get_card_size()

        self.grid_widget.setUpdatesEnabled(False)
        try:
            total_so_far = len(self._all_cards)
            row = total_so_far // cols_per_row
            col = total_so_far % cols_per_row

            # Determine if current filter allows these games
            text = self.search_input.text().lower()
            platform = self.platform_filter.currentText()

            for game in games:
                # Filter check
                matches_search = not text or text in game.get('name', '').lower() or text in game.get('fs_name', '').lower()
                matches_platform = (platform == "All Platforms"
                                   or game.get('platform_display_name') == platform
                                   or game.get('platform_slug') == platform)

                if matches_search and matches_platform:
                    card = GameCard(game, self.client, self.config, sync_cache)
                    if game.get('_local_exists'):
                        card.set_local_exists(True)
                    card.clicked.connect(lambda g=game: self.open_detail(g))
                    card.setFixedSize(card_w, card_h)
                    card.img_label.setFixedSize(card_w - 10, card_h - 30)   
                    card.title_label.setFixedWidth(card_w - 10)
                    self.grid_layout.addWidget(card, row, col)
                    self._all_cards.append(card)

                    col += 1
                    if col >= cols_per_row:
                        col = 0
                        row += 1
        finally:
            self.grid_widget.setUpdatesEnabled(True)

    def _get_card_size(self):
        """Compute card width/height based on viewport width and cols setting."""
        cols = max(1, int(self.config.get("cards_per_row", 6)))
        spacing = self.grid_layout.horizontalSpacing() * (cols - 1) + 20    
        available = self.scroll_area.viewport().width() - spacing
        w = max(100, available // cols)
        h = int(w * 1.5)
        return w, h, cols

    def _resize_all_cards(self):
        """Resize every rendered card to match current viewport width."""   
        if not self._all_cards:
            return
        w, h, cols = self._get_card_size()
        self.grid_widget.setUpdatesEnabled(False)
        try:
            for card in self._all_cards:
                card.setFixedSize(w, h)
                card.img_label.setFixedSize(w - 10, h - 30)
                if card._full_pixmap:
                    card.img_label.setPixmap(
                        card._full_pixmap.scaled(
                            w - 10, h - 30,
                            Qt.KeepAspectRatioByExpanding,
                            Qt.SmoothTransformation
                        )
                    )
                card.title_label.setFixedWidth(w - 10)
        finally:
            self.grid_widget.setUpdatesEnabled(True)

    def eventFilter(self, obj, event):
        try:
            if (obj is self.scroll_area.viewport()
                    and event.type() == QEvent.Type.Resize):
                self._resize_debounce.start()
        except Exception:
            pass
        return super().eventFilter(obj, event)

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

        print(f"[Library] Threshold hit — loading next batch. Pending: {len(self._pending_games)}")
        self._is_loading_batch = True
        self._render_next_batch()

    def _set_install_filter(self, filter_id):
        self.current_install_filter = filter_id
        self.apply_filters()

    def apply_filters(self):
        from src import download_registry
        text = self.search_input.text().lower()
        platform = self.platform_filter.currentText()
        self._selected_index = -1 # Reset selection on filter

        # build base filtered list by text/platform
        if platform == "⚠️ No Emulator":
            all_known = set(RETROARCH_PLATFORMS)
            for emu in emulators.load_emulators():
                all_known.update(emu.get("platform_slugs", []))
            base_filtered = [
                g for g in self.main_window.all_games
                if g.get("platform_slug") not in all_known
                and (not text
                     or text in g.get('name', '').lower()
                     or text in g.get('fs_name', '').lower())
            ]
        else:
            base_filtered = [
                g for g in self.main_window.all_games
                if (not text
                    or text in g.get('name', '').lower()
                    or text in g.get('fs_name', '').lower())
                and (platform == "All Platforms"
                     or g.get('platform_display_name') == platform
                     or g.get('platform_slug') == platform)
            ]

        # Apply installation status filter
        filtered = []
        for g in base_filtered:
            is_installed = g.get('_local_exists', False) or download_registry.get(str(g.get('id'))) is not None
            
            if self.current_install_filter == "installed":
                if is_installed: filtered.append(g)
            elif self.current_install_filter == "not_installed":
                if not is_installed: filtered.append(g)
            else:
                filtered.append(g)

        platform_changed = (
            not hasattr(self, '_current_platform') or
            self._current_platform != platform
        )

        if not platform_changed and self._all_cards:
            # Same platform — just show/hide existing cards and REFLOW them
            self.grid_widget.setUpdatesEnabled(False)
            try:
                filtered_ids = set(g.get('id') for g in filtered)
                visible_cards = []
                
                # 1. Update visibility and collect visible cards
                for card in self._all_cards:
                    try:
                        visible = card.game.get('id') in filtered_ids
                        card.setVisible(visible)
                        card.set_selected(False)
                        if visible:
                            visible_cards.append(card)
                    except RuntimeError:
                        pass
                
                # 2. Clear current layout positions (without deleting widgets)
                while self.grid_layout.count():
                    item = self.grid_layout.takeAt(0)
                    # We just take it out, it stays a child of grid_widget
                
                # 3. Re-add only visible ones in order
                _, _, cols = self._get_card_size()
                for idx, card in enumerate(visible_cards):
                    row = idx // cols
                    col = idx % cols
                    self.grid_layout.addWidget(card, row, col)
                
                # 4. Handle "No games match" case
                if not visible_cards:
                    self.show_empty_message("No games match your search.")
                else:
                    # Clear any empty message labels
                    for i in range(self.grid_layout.count()):
                        item = self.grid_layout.itemAt(i)
                        if item and hasattr(item.widget(), 'text') and "No games" in item.widget().text():
                            item.widget().deleteLater()

            finally:
                self.grid_widget.setUpdatesEnabled(True)
        else:
            # Platform changed — rebuild grid
            self.populate_grid(filtered)

        print(f"[Library] Filter → {len(filtered)} games (platform='{platform}' search='{text}')")

    def update_game_local_status(self, game_id, exists):
        """Dynamically updates a GameCard's checkmark status."""
        found = False
        for card in self._all_cards:
            try:
                if card.game.get('id') == game_id:
                    card.set_local_exists(exists)
                    found = True
                    break
            except RuntimeError:
                continue

        if found and self.current_install_filter != "all":
            # Re-apply filters if we are in an install-specific view (e.g. "Not Installed")
            # so the card can disappear or appear correctly.
            self.apply_filters()

    def populate_games(self, games, status=None):
        """Standard method to populate the grid from a list of games."""
        self.populate_grid(games)
        if status:
            self.set_status(status)

    def populate_grid(self, games):
        # Increment generation — any pending render callbacks will        
        # check this and abort immediately
        self._render_generation += 1
        my_gen = self._render_generation
        
        # Clear image fetch state in main window
        self.main_window.image_fetch_queue = []
        # Stop any active fetchers to prevent "QThread: Destroyed while running"
        for f in self.main_window.active_image_fetchers[:]:
            try:
                if f.isRunning():
                    # We don't terminate() because it's unsafe, 
                    # but by clearing the list, we let them finish 
                    # and they'll be ignored by generation check.
                    pass
            except RuntimeError:
                pass
        self.main_window.active_image_fetchers = []

        self.retry_btn.setVisible(False)
        self._all_cards = []
        self._pending_games = list(games)  # full list, render in batches   
        self._scroll_debounce.stop()  # cancel any pending debounce on grid reset
        self._is_loading_batch = False
        self._current_platform = self.platform_filter.currentText()
        self._selected_index = -1

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

        card_w, card_h, cols_per_row = self._get_card_size()

        self.grid_widget.setUpdatesEnabled(False)
        try:
            # Calculate starting row/col from existing card count
            total_so_far = len(self._all_cards)
            row = total_so_far // cols_per_row
            col = total_so_far % cols_per_row

            for i, game in enumerate(batch):
                if generation != self._render_generation:
                    return

                card = GameCard(game, self.client, self.config, sync_cache)
                if game.get('_local_exists'):
                    card.set_local_exists(True)
                card.clicked.connect(lambda g=game: self.open_detail(g))
    
                card.setFixedSize(card_w, card_h)
                card.img_label.setFixedSize(card_w - 10, card_h - 30)       
                card.title_label.setFixedWidth(card_w - 10)
                self.grid_layout.addWidget(card, row, col)
                self._all_cards.append(card)
                col += 1
                if col >= cols_per_row:
                    col = 0
                    row += 1
        finally:
            self.grid_widget.setUpdatesEnabled(True)

        print(f"[Library] Cards: {len(self._all_cards)} loaded, {len(self._pending_games)} pending")

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
            self._load_more_label = QLabel(f"⬇ Scroll down to load {remaining} more games...")       
            self._load_more_label.setAlignment(Qt.AlignCenter)
            self._load_more_label.setStyleSheet(
                "color: #1e88e5; font-size: 13px; "
                "padding: 20px; background: #1a1a1a;")
            next_row = (len(self._all_cards) + cols_per_row - 1) // cols_per_row
            self.grid_layout.addWidget(
                self._load_more_label, next_row, 0, 1, cols_per_row)        

        self._is_loading_batch = False

    def open_detail(self, game):
        # Local import to avoid circular dependency
        from src.ui.dialogs.game_detail import GameDetailPanel
        
        # Remove old detail page if exists
        if self.detail_panel:
            self.stack.removeWidget(self.detail_panel)
            self.detail_panel.deleteLater()
        
        self.detail_panel = GameDetailPanel(
            game, self.client, self.config,
            self.main_window,
            on_close=self._close_detail,
            parent=self
        )
        self.stack.addWidget(self.detail_panel)
        self.stack.setCurrentWidget(self.detail_panel)
        self.filter_widget.hide() # Hide filters while in detail view

    def _close_detail(self):
        self.stack.setCurrentWidget(self.grid_page)
        self.filter_widget.show()
        if self.detail_panel:
            self.stack.removeWidget(self.detail_panel)
            self.detail_panel.deleteLater()
            self.detail_panel = None

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
