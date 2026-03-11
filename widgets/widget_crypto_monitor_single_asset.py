#!/usr/bin/env python3
# requirements: PyQt6, websocket-client

import sys
import os
import json
import websocket
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QLabel, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QTextEdit, QScrollArea, QMenu
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QEvent, QPoint, QRect
from PyQt6.QtGui import QMouseEvent, QMoveEvent, QFont, QAction, QColor, QTextCursor

try:
    import winsound
except ImportError:
    winsound = None

if __package__:
    from .widget_core import hide_from_taskbar_later
else:
    from widget_core import hide_from_taskbar_later

# ==========================
# Constants / Theme
# ==========================

APP_HEIGHT = 400
APP_WIDTH = 370
BOTTOM_OFFSET = 43

TRANSPARENCY = 150
BUTTON_TRANSPARENCY = 150
LOG_TEXT_OPACITY = 150

EDGE_GRAB = 28
MIN_WIDTH = 260

MAX_LOG_LINES = 1000

# Beep settings
BEEP_FREQ_HZ = 1200
BEEP_DURATION_MS = 300
BEEP_REPEAT = 3

# ---------- Hit-test background ----------
HIT_BG = "rgba(0, 0, 0, 2)"

# ---------- Suite-matched styles ----------
SCROLLBAR_STYLE = """
    QScrollBar:vertical {
        border: none;
        background: transparent;
        width: 6px;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: #555555;
        min-height: 20px;
        border-radius: 3px;
    }
    QScrollBar::handle:vertical:hover { background: #777777; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

    QScrollBar:horizontal {
        border: none;
        background: transparent;
        height: 6px;
        margin: 0px;
    }
    QScrollBar::handle:horizontal {
        background: #555555;
        min-width: 20px;
        border-radius: 3px;
    }
    QScrollBar::handle:horizontal:hover { background: #777777; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
"""

BUTTON_STYLE = """
    QPushButton {
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #343434, stop:1 #1A1A1A);
        color: rgba(255, 255, 255, 220);
        font-weight: bold;
        font-size: 11px;
        border: 1px solid #3d3d3d;
        border-radius: 6px;
        padding: 5px 10px;
    }
    QPushButton:hover {
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #424242, stop:1 #232323);
    }
    QPushButton:pressed {
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #1A1A1A, stop:1 #111111);
    }
"""

LINEEDIT_STYLE = """
    QLineEdit {
        background-color: rgba(45, 45, 45, 0.9);
        border: 1px solid #3d3d3d;
        border-radius: 6px;
        padding: 4px 6px;
        color: rgba(255, 255, 255, 220);
        font-size: 12px;
    }
    QLineEdit:focus {
        border: 1px solid #555555;
    }
"""

CONTEXT_MENU_STYLE = """
    QMenu {
        background-color: #2b2b2b;
        color: #f0f0f0;
        border: 1px solid #3a3a3a;
        border-radius: 10px;
        padding: 6px;
    }
    QMenu::item {
        background-color: transparent;
        padding: 6px 12px;
        border-radius: 6px;
    }
    QMenu::item:selected {
        background-color: #3a3a3a;
    }
"""

# ==========================
# Position persistence
# ==========================

class PositionStore:
    def __init__(self, app_id: str):
        self.app_id = app_id
        folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "widget_positions")
        os.makedirs(folder, exist_ok=True)
        filename = os.path.splitext(os.path.basename(__file__))[0] + ".json"
        self.path = os.path.join(folder, filename)

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            v = data.get(self.app_id)
            if isinstance(v, dict) and "x" in v and "y" in v:
                return v
        except Exception:
            pass
        return None

    def save(self, **kwargs):
        try:
            data = {}
            if os.path.exists(self.path):
                try:
                    with open(self.path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if not isinstance(data, dict):
                        data = {}
                except Exception:
                    data = {}
            existing = data.get(self.app_id, {})
            existing.update(kwargs)
            data[self.app_id] = existing
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

# ==========================
# WebSocket worker
# ==========================

class WebSocketThread(QThread):
    price_signal = pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self.ws = None
        self.url = None

    def set_url(self, url):
        self.url = url

    def run(self):
        if not self.url:
            return
        self.ws = websocket.WebSocketApp(
            self.url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        self.ws.on_open = self.on_open
        self.ws.run_forever()

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            if 'c' in data:
                last_price = float(data['c'])
                self.price_signal.emit(last_price)
        except Exception:
            pass

    def on_error(self, ws, error):
        pass

    def on_close(self, ws, *args):
        pass

    def on_open(self, ws):
        pass

    def stop(self):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass

# ==========================
# Main Widget
# ==========================

class PriceDisplay(QWidget):
    APP_ID = "SingleAssetTicker"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Standalone Monitor Single Asset")
        self.previous_price = None
        self.beeping_enabled = True
        self.current_price = 0.0

        self.last_color = QColor(255, 255, 255, LOG_TEXT_OPACITY)

        self.resizing = False
        self._resize_start_global_x = 0
        self._resize_start_w = 0
        self._cursor_over_edge = False

        self._pos_store = PositionStore(self.APP_ID)

        # --- Position Locking System ---
        self._locked_pos = None       # The last known-good position (QPoint)
        self._is_dragging = False     # True only while the user is actively dragging
        self._drag_occurred = False   # True if mouse actually moved during a drag
        self._drag_offset = None      # Offset from mouse cursor to window top-left (QPoint)
        self._screen_change_connected = False  # Guard for one-time screenChanged connection
        self._drag_grace_period = False  # Brief grace period after drag ends

        # Timer for resize-only saves (not position — position is drag-locked)
        self._resize_save_timer = QTimer(self)
        self._resize_save_timer.setInterval(250)
        self._resize_save_timer.setSingleShot(True)
        self._resize_save_timer.timeout.connect(self._save_size_now)

        self.ws_thread: WebSocketThread | None = None
        self.monitoring_active = False

        self.initUI()
        self.restore_or_anchor()
        self._enable_mouse_tracking()
        self._install_mouse_filters()
        self._load_settings()

        self.start_monitoring(initial=True)

    def initUI(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnBottomHint |
            Qt.WindowType.Window
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(TRANSPARENCY / 255)
        self.setFixedSize(APP_WIDTH, APP_HEIGHT)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- Log area with hit-test background for seamless scrolling ---
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll_area.setStyleSheet(
            f"QScrollArea {{ background: {HIT_BG}; border: none; }}" + SCROLLBAR_STYLE
        )
        self.scroll_area.viewport().setStyleSheet(f"background: {HIT_BG};")

        self.log_display = QTextEdit(self)
        self.log_display.setReadOnly(True)
        self.log_display.setStyleSheet(f"""
            QTextEdit {{
                background: {HIT_BG};
                border: none;
            }}
        """ + SCROLLBAR_STYLE)
        self.log_display.setFont(QFont("Segoe UI", 13))
        self.log_display.setCursor(Qt.CursorShape.IBeamCursor)
        self.log_display.setTextColor(QColor(255, 255, 255, LOG_TEXT_OPACITY))

        self.scroll_area.setWidget(self.log_display)
        root.addWidget(self.scroll_area, 1)

        # --- Input area ---
        inp_wrap = QWidget(self)
        inp_wrap.setObjectName("inp_wrap")
        inp_wrap.setStyleSheet("background: transparent;")
        inp = QVBoxLayout(inp_wrap)
        inp.setContentsMargins(0, 0, 0, 0)
        inp.setSpacing(6)

        label_w = 90

        hide_from_taskbar_later(self)

        def make_row(lbl_text, lineedit_ref_attr, placeholder, default_text=None):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            lbl = QLabel(lbl_text, self)
            lbl.setStyleSheet("color: rgba(255,255,255,220); font-size: 12px; background: transparent;")
            lbl.setFixedWidth(label_w)
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            le = QLineEdit(self)
            le.setPlaceholderText(placeholder)
            if default_text:
                le.setText(default_text)
            le.setAlignment(Qt.AlignmentFlag.AlignCenter)
            le.setStyleSheet(LINEEDIT_STYLE)
            le.setCursor(Qt.CursorShape.IBeamCursor)
            setattr(self, lineedit_ref_attr, le)
            row.addWidget(lbl)
            row.addWidget(le, 1)
            inp.addLayout(row)

        make_row("Pair:", "asset_pair_input", "ADAUSDT", "ADAUSDT")
        make_row("Input Price:", "entry_price_input", "Enter entry price")
        make_row("Target Price:", "target_price_input", "Enter target price")

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)

        self.set_button = QPushButton("Set Values", self)
        self.set_button.setStyleSheet(BUTTON_STYLE)
        self.set_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_button.clicked.connect(self.set_values)

        self.toggle_beep_button = QPushButton("Disable Notification", self)
        self.toggle_beep_button.setStyleSheet(BUTTON_STYLE)
        self.toggle_beep_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_beep_button.clicked.connect(self.toggle_beeping)

        self.stop_tracking_button = QPushButton("■ Stop", self)
        self.stop_tracking_button.setStyleSheet(BUTTON_STYLE)
        self.stop_tracking_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_tracking_button.clicked.connect(self.toggle_tracking)

        btn_row.addWidget(self.set_button)
        btn_row.addWidget(self.toggle_beep_button)
        btn_row.addWidget(self.stop_tracking_button)

        inp.addLayout(btn_row)
        root.addWidget(inp_wrap)

    # ----- Mouse helpers -----

    def _enable_mouse_tracking(self):
        self.setMouseTracking(True)
        for w in self.findChildren(QWidget):
            w.setMouseTracking(True)

    def _install_mouse_filters(self):
        self.installEventFilter(self)
        for w in self.findChildren(QWidget):
            w.installEventFilter(self)

    def _on_right_edge_local(self, local_pt):
        return local_pt.x() >= self.width() - EDGE_GRAB

    def _set_resize_cursor(self, on):
        if on and not self._cursor_over_edge:
            QApplication.setOverrideCursor(Qt.CursorShape.SizeHorCursor)
            self._cursor_over_edge = True
        elif not on and self._cursor_over_edge and not self.resizing:
            QApplication.restoreOverrideCursor()
            self._cursor_over_edge = False

    def _is_position_visible(self, x: int, y: int) -> bool:
        """True if at least 50x30 px of the widget is on any screen."""
        widget_rect = QRect(x, y, self.width(), self.height())
        app = QApplication.instance()
        if not app:
            return False
        for screen in app.screens():
            inter = widget_rect.intersected(screen.availableGeometry())
            if inter.width() >= 50 and inter.height() >= 30:
                return True
        return False

    def eventFilter(self, obj, event):
        et = event.type()

        if et in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            try:
                gp = event.globalPosition().toPoint()
            except Exception:
                return super().eventFilter(obj, event)
            local = self.mapFromGlobal(gp)

            if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if self._on_right_edge_local(local):
                    self.resizing = True
                    self._resize_start_global_x = gp.x()
                    self._resize_start_w = self.width()
                    self._set_resize_cursor(True)
                    return True

            elif et == QEvent.Type.MouseMove:
                if self.resizing:
                    delta = gp.x() - self._resize_start_global_x
                    new_w = max(MIN_WIDTH, self._resize_start_w + delta)
                    self.setFixedSize(new_w, self.height())
                    self._resize_save_timer.start()
                    return True
                else:
                    self._set_resize_cursor(self._on_right_edge_local(local))

            elif et == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if self.resizing:
                    self.resizing = False
                    self._resize_save_timer.start()
                    self._set_resize_cursor(False)
                    return True

        if et in (QEvent.Type.HoverMove, QEvent.Type.Enter, QEvent.Type.Leave):
            if et == QEvent.Type.Leave:
                self._set_resize_cursor(False)
            elif et == QEvent.Type.HoverMove:
                try:
                    gp = obj.mapToGlobal(event.position().toPoint())
                    local = self.mapFromGlobal(gp)
                    self._set_resize_cursor(self._on_right_edge_local(local))
                except Exception:
                    pass

        return super().eventFilter(obj, event)

    # ----- Position -----

    def restore_or_anchor(self):
        saved = self._pos_store.load()
        if saved:
            w = saved.get("w", APP_WIDTH)
            self.setFixedSize(int(w), APP_HEIGHT)
            x, y = int(saved["x"]), int(saved["y"])
            self.move(x, y)
            self._locked_pos = QPoint(x, y)
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            x = 0
            y = screen.height() - APP_HEIGHT - BOTTOM_OFFSET
            self.move(x, y)
            self._locked_pos = QPoint(x, y)

    # --- Glitch Protection: moveEvent ---

    def moveEvent(self, event: QMoveEvent):
        """
        Intercept ALL move events. Only allow moves caused by user dragging.
        Snap back to _locked_pos if the OS glitches the position.
        """
        if self._locked_pos is None:
            super().moveEvent(event)
            return

        # User is dragging (or in brief post-drag grace period) — allow freely
        if self._is_dragging or self._drag_grace_period:
            super().moveEvent(event)
            return

        # --- Not dragging: this move was initiated by the OS (DWM glitch) ---
        current_pos = self.pos()
        locked = self._locked_pos

        diff_x = abs(current_pos.x() - locked.x())
        diff_y_signed = locked.y() - current_pos.y()  # positive = window shifted UP
        manhattan = diff_x + abs(diff_y_signed)

        # Negligible jitter (≤2px) — allow it
        if manhattan <= 2:
            super().moveEvent(event)
            return

        # Ghost Title Bar Fix: small upward shift of ~15-80px with minimal X change
        if 15 <= diff_y_signed <= 80 and diff_x <= 5:
            QTimer.singleShot(0, lambda pos=QPoint(locked): self.move(pos))
            return

        # Massive Jump Fix: coordinate space re-index
        if manhattan > 100:
            QTimer.singleShot(0, lambda pos=QPoint(locked): self.move(pos))
            return

        # Any other unexpected OS-initiated shift — snap back
        QTimer.singleShot(0, lambda pos=QPoint(locked): self.move(pos))
        return

    def resizeEvent(self, e):
        self._resize_save_timer.start()
        return super().resizeEvent(e)

    def _save_size_now(self):
        """Save width only (position is saved exclusively via _end_drag)."""
        self._pos_store.save(w=self.width())

    def _save_position_and_size(self):
        """Save both position and width — used on close and end of drag."""
        if self._locked_pos is not None:
            self._pos_store.save(x=self._locked_pos.x(), y=self._locked_pos.y(), w=self.width())
        else:
            p = self.frameGeometry().topLeft()
            self._pos_store.save(x=p.x(), y=p.y(), w=self.width())

    # ----- Settings (persisted in same JSON) -----

    def _load_settings(self):
        saved = self._pos_store.load()
        if not saved:
            return

        pair = saved.get("pair")
        entry = saved.get("entry")
        target = saved.get("target")
        beeping = saved.get("beeping_enabled")

        if isinstance(pair, str) and pair.strip():
            self.asset_pair_input.setText(pair)

        if entry is not None:
            self.entry_price_input.setText(str(entry))

        if target is not None:
            self.target_price_input.setText(str(target))

        if isinstance(beeping, bool):
            self.beeping_enabled = beeping
            self.toggle_beep_button.setText(
                "Disable Notification" if self.beeping_enabled else "Enable Notification"
            )

    def _save_settings(self):
        pair_raw = self.asset_pair_input.text().strip()
        pair = self._sanitize_pair(pair_raw) or "ADAUSDT"
        self.asset_pair_input.setText(pair)

        entry_str = self.entry_price_input.text().strip()
        target_str = self.target_price_input.text().strip()

        save_data = {
            "pair": pair,
            "beeping_enabled": self.beeping_enabled,
        }

        # Store entry/target as floats if valid, otherwise store the string
        try:
            if entry_str:
                save_data["entry"] = float(entry_str)
        except ValueError:
            pass

        try:
            if target_str:
                save_data["target"] = float(target_str)
        except ValueError:
            pass

        self._pos_store.save(**save_data)
        return True

    # ----- WS control -----

    def _sanitize_pair(self, text: str) -> str:
        return "".join(ch for ch in text.upper() if ch.isalnum())

    def _start_ws(self, pair: str):
        self._stop_ws()
        url = f"wss://stream.binance.com:9443/ws/{pair.lower()}@ticker"
        self.ws_thread = WebSocketThread()
        self.ws_thread.price_signal.connect(self.update_price)
        self.ws_thread.set_url(url)
        self.ws_thread.start()

    def _stop_ws(self):
        if self.ws_thread is not None:
            try:
                self.ws_thread.stop()
                self.ws_thread.wait(2000)
            except Exception:
                pass
            self.ws_thread = None

    def start_monitoring(self, initial: bool = False):
        if self.monitoring_active:
            return
        pair_raw = self.asset_pair_input.text().strip() or "ADAUSDT"
        pair = self._sanitize_pair(pair_raw) or "ADAUSDT"
        self.asset_pair_input.setText(pair)

        self._start_ws(pair)
        self.monitoring_active = True
        self.stop_tracking_button.setText("■ Stop")

        if initial:
            QTimer.singleShot(30000, self._auto_stop_initial)

    def _auto_stop_initial(self):
        if self.monitoring_active:
            self.stop_monitoring("Auto-stopped monitoring after initial warmup (~30s).")

    def stop_monitoring(self, msg: str | None = None):
        if not self.monitoring_active:
            return
        self._stop_ws()
        self.monitoring_active = False
        self.stop_tracking_button.setText("▶ Start")
        if msg:
            self._log_white(msg)
        else:
            self._log_white("Stopped tracking the price.")

    # ----- Logs / beep -----

    def _trim_logs(self):
        doc = self.log_display.document()
        while doc.blockCount() > MAX_LOG_LINES:
            cursor = QTextCursor(doc)
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    def _do_beep(self):
        if not winsound:
            return
        try:
            for _ in range(BEEP_REPEAT):
                winsound.Beep(BEEP_FREQ_HZ, BEEP_DURATION_MS)
        except Exception:
            pass

    def _log_white(self, msg: str):
        """Append a message in white (for status messages, not price ticks)."""
        self.log_display.setTextColor(QColor(255, 255, 255, LOG_TEXT_OPACITY))
        self.log_display.append(msg)

    # ----- Price flow -----

    def update_price(self, price):
        self.current_price = price

        if self.previous_price is not None:
            now = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            pair = (self.asset_pair_input.text() or "").upper()

            if price > self.previous_price:
                self.last_color = QColor(0, 255, 0, LOG_TEXT_OPACITY)
            elif price < self.previous_price:
                self.last_color = QColor(255, 0, 0, LOG_TEXT_OPACITY)

            self.log_display.setTextColor(self.last_color)
            self.log_display.append(f"{now}: {pair}:-- ${price:.4f}")
            self._trim_logs()

            # Auto-scroll to bottom
            vbar = self.scroll_area.verticalScrollBar()
            if vbar:
                vbar.setValue(vbar.maximum())

            # Check target alerts
            entry = None
            target = None
            try:
                entry_str = self.entry_price_input.text().strip()
                target_str = self.target_price_input.text().strip()
                if entry_str and target_str:
                    entry = float(entry_str)
                    target = float(target_str)
            except ValueError:
                entry = None
                target = None

            if self.beeping_enabled and entry is not None and target is not None:
                if target > entry and price >= target:
                    self._do_beep()
                elif target < entry and price <= target:
                    self._do_beep()

        self.previous_price = price

    # ----- Buttons -----

    def toggle_beeping(self):
        self.beeping_enabled = not self.beeping_enabled
        self.toggle_beep_button.setText(
            "Disable Notification" if self.beeping_enabled else "Enable Notification"
        )
        self._log_white("Notifications " + ("enabled." if self.beeping_enabled else "disabled."))
        self._save_settings()

    def toggle_tracking(self):
        if self.monitoring_active:
            self.stop_monitoring()
        else:
            self.start_monitoring(initial=False)
            self._log_white("Started tracking the price.")

    def set_values(self):
        pair_raw = self.asset_pair_input.text().strip()
        pair = self._sanitize_pair(pair_raw) or "ADAUSDT"
        self.asset_pair_input.setText(pair)

        entry_str = self.entry_price_input.text().strip()
        target_str = self.target_price_input.text().strip()

        # Validate entry and target are numeric if provided
        entry_val = None
        target_val = None
        if entry_str:
            try:
                entry_val = float(entry_str)
            except ValueError:
                self._log_white("Invalid entry price — must be a number.")
                return
        if target_str:
            try:
                target_val = float(target_str)
            except ValueError:
                self._log_white("Invalid target price — must be a number.")
                return

        self._save_settings()

        parts = [f"Pair: {pair}"]
        if entry_val is not None:
            parts.append(f"Entry: {entry_val}")
        if target_val is not None:
            parts.append(f"Target: {target_val}")
        self._log_white(f"Values saved. {', '.join(parts)}")

        # Restart WS with new pair if monitoring
        if self.monitoring_active:
            self._start_ws(pair)

    # ==========================
    # POSITION LOCKING SYSTEM
    # ==========================

    # --- Centralized Drag Helpers ---

    def _start_drag(self, global_pos: QPoint):
        """Begin a user-initiated drag."""
        self._is_dragging = True
        self._drag_occurred = False
        self._drag_offset = global_pos - self.frameGeometry().topLeft()

    def _do_drag(self, global_pos: QPoint):
        """Move the window during an active drag."""
        if not self._is_dragging or self._drag_offset is None:
            return
        new_pos = global_pos - self._drag_offset
        self._drag_occurred = True
        self.move(new_pos)

    def _end_drag(self):
        """Finish a drag: save position ONLY if the user actually moved the window."""
        was_dragging = self._is_dragging
        did_move = self._drag_occurred

        self._is_dragging = False
        self._drag_occurred = False
        self._drag_offset = None

        if was_dragging and did_move:
            current = self.pos()
            if self._is_position_visible(current.x(), current.y()):
                self._locked_pos = QPoint(current)
                self._save_position_and_size()

        # Brief grace period: moveEvents can arrive slightly after mouseRelease
        if was_dragging:
            self._drag_grace_period = True
            QTimer.singleShot(150, self._clear_grace_period)

    def _clear_grace_period(self):
        self._drag_grace_period = False

    # --- Mouse Events (delegate to drag helpers) ---

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            self.show_context_menu(event)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            widget = self.childAt(event.position().toPoint())
            if not isinstance(widget, (QPushButton, QLineEdit, QTextEdit)):
                self._start_drag(event.globalPosition().toPoint())
                event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging:
            self._do_drag(event.globalPosition().toPoint())
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._end_drag()
            event.accept()

    # --- Screen Change Handler ---

    def _on_screen_changed(self, screen):
        """
        Called when the window moves to a different screen (monitor topology change).
        Only snap back if the user is NOT dragging.
        """
        if self._locked_pos is not None and not self._is_dragging:
            locked = QPoint(self._locked_pos)
            QTimer.singleShot(100, lambda: self.move(locked) if not self._is_dragging else None)
            QTimer.singleShot(300, lambda: self.move(locked) if not self._is_dragging else None)

    # --- Context Menu ---

    def show_context_menu(self, event):
        context_menu = QMenu(self)
        context_menu.setStyleSheet(CONTEXT_MENU_STYLE)
        close_action = QAction("Close", self)
        close_action.triggered.connect(self.close)
        context_menu.addAction(close_action)
        context_menu.exec(event.globalPosition().toPoint())

    # --- showEvent: stay behind + connect screenChanged ---

    def showEvent(self, e):
        super().showEvent(e)
        try:
            import ctypes
            from ctypes import wintypes
            HWND_BOTTOM = 1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            SetWindowPos = ctypes.windll.user32.SetWindowPos
            hwnd = int(self.winId())
            SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_BOTTOM), 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

        # Safely connect screenChanged signal (once only)
        if not self._screen_change_connected:
            win_handle = self.windowHandle()
            if win_handle is not None:
                try:
                    win_handle.screenChanged.connect(
                        self._on_screen_changed,
                        Qt.ConnectionType.UniqueConnection
                    )
                    self._screen_change_connected = True
                except Exception:
                    pass

    def closeEvent(self, e):
        try:
            self._stop_ws()
        except Exception:
            pass
        # Save locked position + size + settings on close
        self._save_position_and_size()
        self._save_settings()
        super().closeEvent(e)

# ==========================
# Entry
# ==========================

if __name__ == '__main__':
    app = QApplication(sys.argv)
    display = PriceDisplay()
    display.show()
    sys.exit(app.exec())