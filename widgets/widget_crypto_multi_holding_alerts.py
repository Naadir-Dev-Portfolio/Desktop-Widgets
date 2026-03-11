import sys
import os
import json
import time
import ctypes
from ctypes import wintypes
from pathlib import Path
from datetime import datetime
import threading

import requests
import websocket
import winsound
import pyttsx3

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QMenu, QScrollArea, QSizePolicy, QToolTip
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize, QUrl
from PyQt6.QtGui import QMouseEvent, QAction, QIcon, QCursor, QDesktopServices

if __package__:
    from .widget_core import hide_from_taskbar_later
else:
    from widget_core import hide_from_taskbar_later

# =========================
# CONSTANTS
# =========================
APP_WIDTH = 284
APP_HEIGHT = 460
APP_OPACITY = 0.51

BOTTOM_OFFSET = 365
RIGHT_OFFSET = 445

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws/"

DEFAULT_PAIRS = ["solusdt", "atomusdt", "paxgusdt", "avaxusdt"]

DEFAULT_HOLDINGS = {
    "solusdt": 0.0,
    "atomusdt": 0.0,
    "paxgusdt": 0.0,
    "avaxusdt": 0.0,
}
DEFAULT_TARGETS = {
    "solusdt": None,
    "atomusdt": None,
    "paxgusdt": None,
    "avaxusdt": None,
}

USD_TO_GBP_FALLBACK = 0.74
DOTS = "••••"

# =========================
# HIT-TEST TRANSPARENCY (CRITICAL)
# =========================
HITTEST_BG = "rgba(0, 0, 0, 2)"   # almost invisible, still captures mouse wheel/clicks
ROOT_BG    = "rgba(0, 0, 0, 2)"   # root must NOT be alpha=0

# =========================
# THEME (MATCHING YOUTUBE WIDGET)
# =========================

FONT_FAMILY = "Segoe UI"

BUTTON_STYLE = f"""
QPushButton {{
    color: #F0F0F0;
    border: none;
    border-radius: 6px;
    padding: 5px 10px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #343434, stop:1 #1A1A1A);
    font-family: '{FONT_FAMILY}';
    font-weight: 600;
    font-size: 9pt;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #424242, stop:1 #232323);
}}
QPushButton:pressed {{ background: #0F0F0F; }}
"""

ICON_BUTTON_STYLE = f"""
QPushButton {{
    color: #F0F0F0;
    border: none;
    border-radius: 6px;
    padding: 0px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #343434, stop:1 #1A1A1A);
    font-family: '{FONT_FAMILY}';
    font-size: 14pt;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #424242, stop:1 #232323);
}}
QPushButton:pressed {{ background: #0F0F0F; }}
"""

INPUT_STYLE = f"""
QLineEdit {{
    background: rgba(45, 45, 45, 0.9);
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 4px;
    color: #F0F0F0;
    font-family: '{FONT_FAMILY}';
    font-size: 9pt;
}}
QLineEdit:focus {{
    background: rgba(55, 55, 55, 0.95);
    border: 1px solid #555555;
}}
"""

PRICE_STYLE = f"color: #E0E0E0; font-family: '{FONT_FAMILY}'; font-size: 9pt; font-weight: 600;"
PRICE_UP_STYLE = f"color: #4CAF50; font-family: '{FONT_FAMILY}'; font-size: 9pt; font-weight: 600;"
PRICE_DOWN_STYLE = f"color: #FF5252; font-family: '{FONT_FAMILY}'; font-size: 9pt; font-weight: 600;"

TOTAL_STYLE = f"color: #AAAAAA; font-family: '{FONT_FAMILY}'; font-size: 9pt; font-weight: 400;"

# =========================
# FIX: THE DARK BLOCK IS THE CARD BACKGROUND.
# KEEP HIT-TEST (NON-ZERO ALPHA) BUT MAKE IT VISUALLY TRANSPARENT.
# =========================
CARD_STYLE = f"""
QWidget {{
    background: {HITTEST_BG};
    border: none;
    border-radius: 8px;
}}
"""

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
"""

CONTEXT_MENU_STYLE = """
QMenu {
    background-color: #2b2b2b;
    border: 1px solid #3a3a3a;
    border-radius: 10px;
    padding: 6px;
    color: #f0f0f0;
    font-family: 'Segoe UI';
}
QMenu::item { padding: 6px 12px; border-radius: 6px; background: transparent; }
QMenu::item:selected { background-color: #3a3a3a; }
"""

# =========================
# PATHS
# =========================
_SCRIPT_DIR = Path(__file__).resolve().parent
_GUI_DIR = _SCRIPT_DIR.parent
_ICONS_DIR = _GUI_DIR / "resources" / "icons"

HIDE_ICON = str(_ICONS_DIR / "hide.png")
SHOW_ICON = str(_ICONS_DIR / "show.png")

# =========================
# STORE
# =========================
class PositionStore:
    def __init__(self, app_id: str):
        p = Path(__file__).resolve()
        self.path = p.parent / "widget_positions" / f"{p.stem}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.app_id = app_id

    def _read_all(self) -> dict:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _write_all(self, data: dict) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

    def load_app(self) -> dict:
        data = self._read_all()
        v = data.get(self.app_id)
        return v if isinstance(v, dict) else {}

    def save_app(self, payload: dict) -> None:
        data = self._read_all()
        data[self.app_id] = payload
        self._write_all(data)

    def load_position(self):
        v = self.load_app()
        if "x" in v and "y" in v:
            try:
                return int(v["x"]), int(v["y"])
            except Exception:
                return None
        return None

    def save_position(self, x: int, y: int):
        v = self.load_app()
        v["x"] = int(x)
        v["y"] = int(y)
        self.save_app(v)

    def load_state(self):
        v = self.load_app()
        state = v.get("state")
        return state if isinstance(state, dict) else {}

    def save_state(self, state: dict):
        v = self.load_app()
        v["state"] = state
        self.save_app(v)

# =========================
# THREADS
# =========================
class WebSocketThread(QThread):
    price_signal = pyqtSignal(int, float)

    def __init__(self, row_id: int, symbol: str):
        super().__init__()
        self.row_id = row_id
        self.symbol = symbol.lower()
        self._stop = threading.Event()
        self.ws = None

    def run(self):
        self._stop.clear()
        try:
            url = BINANCE_WS_URL + f"{self.symbol}@ticker"
            self.ws = websocket.WebSocketApp(
                url,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close
            )
            self.ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception:
            pass

    def _on_open(self, ws):
        pass

    def _on_close(self, ws, *args):
        pass

    def _on_error(self, ws, error):
        pass

    def _on_message(self, ws, message):
        if self._stop.is_set():
            return
        try:
            data = json.loads(message)
            if "c" in data:
                self.price_signal.emit(self.row_id, float(data["c"]))
        except Exception:
            pass

    def stop(self):
        self._stop.set()
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass

class AlertThread(QThread):
    def __init__(self, message: str):
        super().__init__()
        self.message = message
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 150)
            engine.setProperty("volume", 1.0)
        except Exception:
            engine = None

        while not self._stop.is_set():
            try:
                for _ in range(2):
                    winsound.Beep(1000, 250)
                if engine:
                    engine.say(self.message)
                    engine.runAndWait()
                for _ in range(2):
                    winsound.Beep(1000, 250)
            except Exception:
                pass

            for _ in range(12):
                if self._stop.is_set():
                    break
                time.sleep(0.25)

# =========================
# WIDGET
# =========================
class CryptoWidget(QWidget):
    APP_ID = "CryptoWidget_HitTest_Alpha2_CardFix"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Multiple Crypto Holdings")
        self.pos_store = PositionStore(self.APP_ID)

        self._save_pos_debounce = QTimer(self)
        self._save_pos_debounce.setInterval(250)
        self._save_pos_debounce.setSingleShot(True)
        self._save_pos_debounce.timeout.connect(self._save_position_now)

        self._save_state_debounce = QTimer(self)
        self._save_state_debounce.setInterval(250)
        self._save_state_debounce.setSingleShot(True)
        self._save_state_debounce.timeout.connect(self._save_state_now)

        self.monitoring_active = False
        self.alerts_enabled = True
        self.masked = False

        self.rows = []
        self.ws_threads: dict[int, WebSocketThread | None] = {}
        self.alert_threads: dict[int, AlertThread | None] = {}
        self.prev_prices: dict[int, float | None] = {}
        self.last_prices: dict[int, float | None] = {}

        self.usd_to_gbp = self._get_usd_to_gbp()

        self._drag_active = False
        self._drag_start = None

        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)

        self._init_tooltip_theme()
        self._init_ui()
        self._load_or_defaults()
        self._restore_or_anchor()
        self._apply_masking()

    def _init_tooltip_theme(self):
        if QApplication.instance():
            QApplication.instance().setStyleSheet("""
                QToolTip {
                    background-color: #2b2b2b;
                    color: #f0f0f0;
                    border: 1px solid #3a3a3a;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 9pt;
                    font-family: 'Segoe UI';
                }
            """)

    def _init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnBottomHint |
            Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(APP_WIDTH, APP_HEIGHT)
        self.setWindowOpacity(APP_OPACITY)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        self.setStyleSheet(f"""
            QWidget {{
                font-family: '{FONT_FAMILY}', sans-serif;
                background-color: {ROOT_BG};
            }}
            QScrollArea {{
                background-color: {HITTEST_BG};
                border: none;
            }}
            QWidget#qt_scrollarea_viewport {{
                background-color: {HITTEST_BG};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(6)

        self.play_btn = QPushButton("▶")
        self.play_btn.setStyleSheet(ICON_BUTTON_STYLE)
        self.play_btn.setFixedSize(46, 30)
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.clicked.connect(self._toggle_monitoring)

        self.alerts_btn = QPushButton("Stop Alerts")
        self.alerts_btn.setStyleSheet(BUTTON_STYLE)
        self.alerts_btn.setFixedHeight(30)
        self.alerts_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.alerts_btn.clicked.connect(self._toggle_alerts)

        self.hide_btn = QPushButton()
        self.hide_btn.setStyleSheet(BUTTON_STYLE)
        self.hide_btn.setFixedSize(30, 30)
        self.hide_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide_btn.clicked.connect(self._toggle_masking)
        self._set_hide_icon(masked=False)

        top.addWidget(self.play_btn, 0)
        top.addWidget(self.alerts_btn, 1)
        top.addWidget(self.hide_btn, 0)
        root.addLayout(top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setStyleSheet(
            SCROLLBAR_STYLE
            + f"QScrollArea {{ background-color: {HITTEST_BG}; }}"
            + f"QScrollArea > QWidget {{ background-color: {HITTEST_BG}; }}"
            + f"QWidget#qt_scrollarea_viewport {{ background-color: {HITTEST_BG}; }}"
        )
        self.scroll.viewport().setStyleSheet(f"background-color: {HITTEST_BG};")
        self.scroll.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self.rows_host = QWidget()
        self.rows_host.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.rows_host.setStyleSheet(f"background-color: {HITTEST_BG};")

        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)

        self.scroll.setWidget(self.rows_host)
        root.addWidget(self.scroll, 1)
        hide_from_taskbar_later(self)

    # -------------------------
    # Rows
    # -------------------------
    def _display_pair(self, sym_norm: str) -> str:
        s = self._normalize_symbol(sym_norm)
        if s.endswith("usdt"):
            base = s[:-4].upper()
            quote = "USDT"
        elif s.endswith("usdc"):
            base = s[:-4].upper()
            quote = "USDC"
        else:
            base = s.upper()
            quote = ""
        return f"{base}/{quote}" if quote else base

    def _ws_symbol(self, text: str) -> str:
        return self._normalize_symbol(text).lower()

    def _add_row(self, row_id: int, sym_norm: str, holding: float, target: float | None):
        card = QWidget()
        card.setStyleSheet(CARD_STYLE)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(6)

        r1 = QGridLayout()
        r1.setContentsMargins(0, 0, 0, 0)
        r1.setHorizontalSpacing(8)
        r1.setVerticalSpacing(0)

        pair_edit = QLineEdit()
        pair_edit.setStyleSheet(INPUT_STYLE)
        pair_edit.setFixedHeight(28)
        pair_edit.setToolTip("Enter pair (e.g. BTC/USDT)")
        pair_edit.setText(self._display_pair(sym_norm))
        pair_edit.editingFinished.connect(lambda rid=row_id: self._on_symbol_commit(rid))

        price_label = QLabel(DOTS if self.masked else "—")
        price_label.setStyleSheet(PRICE_STYLE)
        price_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        r1.addWidget(pair_edit, 0, 0)
        r1.addWidget(price_label, 0, 1)
        r1.setColumnStretch(0, 1)
        r1.setColumnStretch(1, 1)

        card_layout.addLayout(r1)

        r2 = QGridLayout()
        r2.setContentsMargins(0, 0, 0, 0)
        r2.setHorizontalSpacing(8)
        r2.setVerticalSpacing(0)

        target_edit = QLineEdit()
        target_edit.setStyleSheet(INPUT_STYLE)
        target_edit.setFixedHeight(28)
        target_edit.setToolTip("Price Target ($)")
        target_edit.setPlaceholderText("Target")
        if target is not None:
            target_edit.setText(f"{target:.6g}")
        target_edit.editingFinished.connect(lambda rid=row_id: self._on_target_commit(rid))

        hold_edit = QLineEdit()
        hold_edit.setStyleSheet(INPUT_STYLE)
        hold_edit.setFixedHeight(28)
        hold_edit.setToolTip("Amount Holding")
        hold_edit.setPlaceholderText("Amount")
        hold_edit.setText(f"{holding:.8g}")
        hold_edit.editingFinished.connect(lambda rid=row_id: self._on_holding_commit(rid))

        r2.addWidget(target_edit, 0, 0)
        r2.addWidget(hold_edit, 0, 1)
        r2.setColumnStretch(0, 1)
        r2.setColumnStretch(1, 1)

        card_layout.addLayout(r2)

        total_label = QLabel(DOTS if self.masked else "$0.00 / £0.00")
        total_label.setStyleSheet(TOTAL_STYLE)
        total_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        card_layout.addWidget(total_label)

        self.rows_layout.addWidget(card)

        self.rows.append({
            "card": card,
            "pair_edit": pair_edit,
            "price_label": price_label,
            "target_edit": target_edit,
            "hold_edit": hold_edit,
            "total_label": total_label,
        })

        self.ws_threads[row_id] = None
        self.alert_threads[row_id] = None
        self.prev_prices[row_id] = None
        self.last_prices[row_id] = None

    # -------------------------
    # Monitoring
    # -------------------------
    def _toggle_monitoring(self):
        if self.monitoring_active:
            self._stop_monitoring()
        else:
            self._start_monitoring()
        self._request_save_state(debounce=True)

    def _start_monitoring(self):
        self.monitoring_active = True
        self._update_controls()
        for rid in range(len(self.rows)):
            self._start_ws_for_row(rid, self._ws_symbol(self.rows[rid]["pair_edit"].text()))

    def _stop_monitoring(self):
        self.monitoring_active = False
        self._update_controls()
        for rid in list(self.ws_threads.keys()):
            self._stop_ws_for_row(rid)

    def _start_ws_for_row(self, row_id: int, symbol: str):
        self._stop_ws_for_row(row_id)
        if not self.monitoring_active:
            return

        if not self.masked:
            self.rows[row_id]["price_label"].setText("...")
        else:
            self.rows[row_id]["price_label"].setText(DOTS)

        t = WebSocketThread(row_id, symbol)
        t.price_signal.connect(self._on_price)
        t.start()
        self.ws_threads[row_id] = t

    def _stop_ws_for_row(self, row_id: int):
        old = self.ws_threads.get(row_id)
        if old:
            try:
                old.stop()
                old.wait(800)
            except Exception:
                pass
        self.ws_threads[row_id] = None

    def _toggle_alerts(self):
        self.alerts_enabled = not self.alerts_enabled
        if not self.alerts_enabled:
            self._stop_all_alerts()
        else:
            for rid in range(len(self.rows)):
                p = self.last_prices.get(rid)
                if isinstance(p, float):
                    self._evaluate_alert(rid, p)
        self._update_controls()
        self._request_save_state(debounce=True)

    def _update_controls(self):
        self.play_btn.setText("■" if self.monitoring_active else "▶")
        self.alerts_btn.setText("Stop Alerts" if self.alerts_enabled else "Start Alerts")

    # -------------------------
    # Commit
    # -------------------------
    def _parse_pair_input(self, s: str) -> str:
        s = (s or "").strip().upper().replace(" ", "")
        if "/" in s:
            a, b = s.split("/", 1)
            s = f"{a}{b}"
        return self._normalize_symbol(s)

    def _on_symbol_commit(self, row_id: int):
        edit = self.rows[row_id]["pair_edit"]
        sym_norm = self._parse_pair_input(edit.text())
        edit.setText(self._display_pair(sym_norm))

        self.prev_prices[row_id] = None
        self.last_prices[row_id] = None
        self._stop_alert(row_id)

        self.rows[row_id]["price_label"].setText(DOTS if self.masked else "—")
        self.rows[row_id]["price_label"].setStyleSheet(PRICE_STYLE)
        self.rows[row_id]["total_label"].setText(DOTS if self.masked else "$0.00 / £0.00")

        self._request_save_state(debounce=True)

        if self.monitoring_active:
            self._start_ws_for_row(row_id, sym_norm.lower())

    def _on_target_commit(self, row_id: int):
        self._safe_float(self.rows[row_id]["target_edit"].text(), None)
        self._request_save_state(debounce=True)
        p = self.last_prices.get(row_id)
        if isinstance(p, float):
            self._evaluate_alert(row_id, p)

    def _on_holding_commit(self, row_id: int):
        self._safe_float(self.rows[row_id]["hold_edit"].text(), 0.0)
        self._request_save_state(debounce=True)
        p = self.last_prices.get(row_id)
        if isinstance(p, float):
            self._update_total(row_id, p)

    # -------------------------
    # Price
    # -------------------------
    def _on_price(self, row_id: int, price: float):
        self.last_prices[row_id] = price
        price_lbl = self.rows[row_id]["price_label"]
        prev = self.prev_prices.get(row_id)

        if not self.masked:
            price_lbl.setText(f"${price:.2f} / £{price * self.usd_to_gbp:.2f}")

        if prev is None:
            price_lbl.setStyleSheet(PRICE_STYLE)
        else:
            if price > prev:
                price_lbl.setStyleSheet(PRICE_UP_STYLE)
            elif price < prev:
                price_lbl.setStyleSheet(PRICE_DOWN_STYLE)
            else:
                price_lbl.setStyleSheet(PRICE_STYLE)

        self.prev_prices[row_id] = price

        tgt = self._safe_float(self.rows[row_id]["target_edit"].text(), None)
        if tgt is None:
            tgt = price * 0.90
            self.rows[row_id]["target_edit"].setText(f"{tgt:.6g}")
            self._request_save_state(debounce=True)

        self._update_total(row_id, price)

        if self.alerts_enabled:
            self._evaluate_alert(row_id, price)

    def _evaluate_alert(self, row_id: int, price: float):
        if not self.alerts_enabled:
            return
        tgt = self._safe_float(self.rows[row_id]["target_edit"].text(), None)
        if tgt is None:
            self._stop_alert(row_id)
            return
        if price <= tgt:
            if not self._is_alert_running(row_id):
                sym_disp = self.rows[row_id]["pair_edit"].text().strip()
                msg = f"{sym_disp} is below target."
                self._start_alert(row_id, msg)
        else:
            self._stop_alert(row_id)

    def _start_alert(self, row_id: int, message: str):
        self._stop_alert(row_id)
        t = AlertThread(message)
        self.alert_threads[row_id] = t
        t.start()

    def _stop_alert(self, row_id: int):
        t = self.alert_threads.get(row_id)
        if t:
            try:
                t.stop()
                t.wait(800)
            except Exception:
                pass
        self.alert_threads[row_id] = None

    def _stop_all_alerts(self):
        for rid in list(self.alert_threads.keys()):
            self._stop_alert(rid)

    def _is_alert_running(self, row_id: int) -> bool:
        t = self.alert_threads.get(row_id)
        return bool(t and t.isRunning())

    def _update_total(self, row_id: int, price: float):
        hold = self._safe_float(self.rows[row_id]["hold_edit"].text(), 0.0)
        total_usd = hold * price
        total_gbp = total_usd * self.usd_to_gbp
        self.rows[row_id]["total_label"].setText(DOTS if self.masked else f"${total_usd:.2f} / £{total_gbp:.2f}")

    # -------------------------
    # Masking
    # -------------------------
    def _set_hide_icon(self, masked: bool):
        path = SHOW_ICON if masked else HIDE_ICON
        if os.path.exists(path):
            self.hide_btn.setIcon(QIcon(path))
            self.hide_btn.setIconSize(QSize(18, 18))
            self.hide_btn.setText("")
        else:
            self.hide_btn.setIcon(QIcon())
            self.hide_btn.setText("👁" if not masked else "🚫")

    def _toggle_masking(self):
        self.masked = not self.masked
        self._apply_masking()
        self._request_save_state(debounce=True)

    def _apply_masking(self):
        self._set_hide_icon(masked=self.masked)
        for rid, row in enumerate(self.rows):
            if self.masked:
                row["price_label"].setText(DOTS)
                row["total_label"].setText(DOTS)
                row["target_edit"].setEchoMode(QLineEdit.EchoMode.Password)
                row["hold_edit"].setEchoMode(QLineEdit.EchoMode.Password)
            else:
                row["target_edit"].setEchoMode(QLineEdit.EchoMode.Normal)
                row["hold_edit"].setEchoMode(QLineEdit.EchoMode.Normal)
                p = self.last_prices.get(rid)
                if isinstance(p, float):
                    row["price_label"].setText(f"${p:.2f} / £{p * self.usd_to_gbp:.2f}")
                    self._update_total(rid, p)
                else:
                    row["price_label"].setText("—")
                    row["total_label"].setText("$0.00 / £0.00")

    # -------------------------
    # Positioning
    # -------------------------
    def _anchor_position(self):
        g = QApplication.primaryScreen().availableGeometry()
        x = g.width() - APP_WIDTH - RIGHT_OFFSET
        y = g.height() - APP_HEIGHT - BOTTOM_OFFSET
        return x, y

    def _restore_or_anchor(self):
        saved = self.pos_store.load_position()
        if saved:
            self.move(*saved)
        else:
            self.move(*self._anchor_position())

    def _current_state_payload(self) -> dict:
        rows_payload = []
        for row in self.rows:
            sym_norm = self._normalize_symbol(row["pair_edit"].text())
            holding = self._safe_float(row["hold_edit"].text(), 0.0)
            target = self._safe_float(row["target_edit"].text(), None)
            rows_payload.append({"symbol": sym_norm, "holding": holding, "target": target})

        return {
            "rows": rows_payload,
            "masked": bool(self.masked),
            "monitoring_active": bool(self.monitoring_active),
            "alerts_enabled": bool(self.alerts_enabled),
            "updated": datetime.now().isoformat(timespec="seconds"),
        }

    def _request_save_state(self, debounce: bool = True):
        if debounce:
            self._save_state_debounce.start()
        else:
            self._save_state_now()

    def _save_state_now(self):
        self.pos_store.save_state(self._current_state_payload())

    def _load_or_defaults(self):
        state = self.pos_store.load_state()
        self.masked = bool(state.get("masked", False))
        self.monitoring_active = False
        self.alerts_enabled = bool(state.get("alerts_enabled", True))

        saved_rows = state.get("rows")
        if not isinstance(saved_rows, list) or not saved_rows:
            saved_rows = []
            for sym in DEFAULT_PAIRS:
                saved_rows.append({
                    "symbol": sym,
                    "holding": float(DEFAULT_HOLDINGS.get(sym, 0.0)),
                    "target": DEFAULT_TARGETS.get(sym, None),
                })

        self._clear_rows()
        for rid, r in enumerate(saved_rows):
            sym = self._normalize_symbol(str(r.get("symbol", DEFAULT_PAIRS[min(rid, len(DEFAULT_PAIRS) - 1)])))
            holding = self._safe_float(r.get("holding"), 0.0)
            target = self._safe_float(r.get("target"), None)
            self._add_row(rid, sym, holding, target)

        self._update_controls()
        self._request_save_state(debounce=False)

    def _clear_rows(self):
        self._stop_all_alerts()
        self._stop_monitoring()
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.rows.clear()
        self.ws_threads.clear()
        self.alert_threads.clear()
        self.prev_prices.clear()
        self.last_prices.clear()

    # -------------------------
    # Events
    # -------------------------
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(CONTEXT_MENU_STYLE)

        reset_pos = QAction("Reset Position", self)
        reset_pos.triggered.connect(lambda: self.move(*self._anchor_position()))

        toggle_mon = QAction("Toggle Monitoring", self)
        toggle_mon.triggered.connect(self._toggle_monitoring)

        toggle_alerts = QAction("Toggle Alerts", self)
        toggle_alerts.triggered.connect(self._toggle_alerts)

        close_action = QAction("Close", self)
        close_action.triggered.connect(self.close)

        menu.addAction(toggle_mon)
        menu.addAction(toggle_alerts)
        menu.addSeparator()
        menu.addAction(reset_pos)
        menu.addSeparator()
        menu.addAction(close_action)
        menu.exec(event.globalPos())

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            w = self.childAt(event.position().toPoint())
            if isinstance(w, (QPushButton, QLineEdit, QScrollArea)):
                return
            self._drag_active = True
            self._drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_active and self._drag_start is not None:
            self.move(event.globalPosition().toPoint() - self._drag_start)
            self._save_pos_debounce.start()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            self._save_pos_debounce.start()
            event.accept()

    def moveEvent(self, event):
        self._save_pos_debounce.start()
        super().moveEvent(event)

    def _save_position_now(self):
        g = self.frameGeometry().topLeft()
        self.pos_store.save_position(g.x(), g.y())

    def showEvent(self, event):
        super().showEvent(event)
        try:
            HWND_BOTTOM = 1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            SetWindowPos = ctypes.windll.user32.SetWindowPos
            SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            hwnd = int(self.winId())
            SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

    def closeEvent(self, event):
        self._stop_monitoring()
        self._stop_all_alerts()
        self._save_position_now()
        self._save_state_now()
        super().closeEvent(event)

    # -------------------------
    # Utils
    # -------------------------
    def _get_usd_to_gbp(self) -> float:
        try:
            r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5)
            data = r.json()
            v = float(data["rates"]["GBP"])
            if v > 0:
                return v
        except Exception:
            pass
        return USD_TO_GBP_FALLBACK

    def _normalize_symbol(self, s: str) -> str:
        s = (s or "").strip().lower().replace(" ", "")
        s = s.replace("/", "")
        if not s:
            return "solusdt"

        if s == "xaut" or s == "xautusdt":
            return "paxgusdt"

        if s.isalpha() and len(s) <= 6 and not s.endswith(("usdt", "usdc", "usd", "btc", "eth", "bnb", "eur")):
            s = s + "usdt"
        return s

    def _safe_float(self, v, default):
        try:
            if v is None:
                return default
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v).strip()
            if not s:
                return default
            return float(s)
        except Exception:
            return default

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = CryptoWidget()
    w.show()
    sys.exit(app.exec())