# tradingview_desktop_widget.py
# Standalone DESKTOP widget: QWebEngine TradingView embed ONLY.
# - Frameless
# - Right-click → styled menu: Info + Close
# - Info shows a tooltip (definition + how to read up/down/trend)
# - Ctrl+MouseWheel zooms (PERSISTED)
# - Zoom persistence uses QWebEnginePage.zoomFactorChanged (compat)
# - Re-applies persisted zoom after loadFinished (TradingView load can reset)
# - Bottom drag bar: FULL WIDTH of webview, rounded corners, height is configurable
# - Minimal resize grip (small, subtle)
# - Persistent per-symbol state: x,y,w,h,zoom in widget_positions/<script>.json
#
# pip install PyQt6 PyQt6-WebEngine

import sys, json
from pathlib import Path
from typing import Dict, Any

from PyQt6.QtCore import Qt, QPoint, QUrl
from PyQt6.QtGui import QAction, QCursor
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QMenu, QSizeGrip, QToolTip
from PyQt6.QtWebEngineWidgets import QWebEngineView

if __package__:
    from .widget_core import hide_from_taskbar_later
else:
    from widget_core import hide_from_taskbar_later


# ===================== CONFIG =====================
TV_SYMBOL = "NASDAQ:IEF"
TV_INTERVAL = "D"
TV_THEME    = "dark"
TV_LOCALE   = "en"
TV_STYLE    = "1"

# Update THIS when you swap TV_SYMBOL in copies
SYMBOL_INFO_TEXT = (
    "IEF (NASDAQ:IEF) — iShares 7–10 Year Treasury Bond ETF\n\n"
    "What it is:\n"
    "• An ETF holding U.S. Treasury notes in the ~7–10 year maturity bucket.\n"
    "• Practical, highly-liquid proxy for the level/direction of intermediate U.S. rates.\n\n"
    "CRITICAL inversion vs yields:\n"
    "• IEF up = yields down (bond prices up → discount rates easing).\n"
    "• IEF down = yields up (bond prices down → discount rates tightening).\n\n"
    "How to read it (macro context):\n"
    "• Sustained IEF rally: falling yields; can mean easing conditions OR growth scare (confirm with SPY).\n"
    "• Sustained IEF selloff: rising yields; tighter financial conditions; valuation headwind for equities.\n"
    "• IEF up + SPY down: classic risk-off / flight-to-safety.\n"
    "• IEF down + SPY down: tightening shock (rates up while risk assets fall)."
)

DEFAULT_ZOOM_FACTOR = 0.85

DEFAULT_W = 900
DEFAULT_H = 560
DEFAULT_X = 120
DEFAULT_Y = 120

# Opacity of the entire widget (0 = completely transparent, 255 = completely opaque)
WIDGET_OPACITY = 135

# Bottom bar geometry (YOU control height here)
BOTTOM_BAR_H        = 4
BOTTOM_BAR_RADIUS   = 12
BOTTOM_BAR_BG       = "rgba(20,20,20,0.35)"
BOTTOM_BAR_BORDER   = "rgba(255,255,255,0.16)"
BOTTOM_BAR_BORDER_W = 1

# Minimal resize grip
GRIP_SIZE   = 10
GRIP_MARGIN = 2

ZOOM_STEP = 0.05
ZOOM_MIN  = 0.25
ZOOM_MAX  = 3.00
# ==================================================



p = Path(__file__).resolve()
STATE_FILE = p.parent / "widget_positions" / f"{p.stem}.json"
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def state_key() -> str:
    return f"TradingViewDesktopWidget_{TV_SYMBOL}"


def load_state() -> Dict[str, Any]:
    try:
        if STATE_FILE.exists():
            d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                v = d.get(state_key(), {})
                return v if isinstance(v, dict) else {}
    except Exception:
        pass
    return {}


def save_state(partial: Dict[str, Any]):
    try:
        all_data: Dict[str, Any] = {}
        if STATE_FILE.exists():
            try:
                all_data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if not isinstance(all_data, dict):
                    all_data = {}
            except Exception:
                all_data = {}

        cur = all_data.get(state_key(), {})
        if not isinstance(cur, dict):
            cur = {}
        cur.update(partial)
        all_data[state_key()] = cur

        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(all_data, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception:
        pass


def tradingview_html(symbol: str) -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>TradingView Desktop Widget</title>
  <style>
    html, body {{
      margin: 0;
      height: 100%;
      width: 100%;
      background: #0b0e11;
      overflow: hidden;
    }}
    #tv {{
      height: 100%;
      width: 100%;
    }}
  </style>
</head>
<body>
  <div id="tv"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
  <script type="text/javascript">
    new TradingView.widget({{
      "autosize": true,
      "symbol": "{symbol}",
      "interval": "{TV_INTERVAL}",
      "timezone": "Etc/UTC",
      "theme": "{TV_THEME}",
      "style": "{TV_STYLE}",
      "locale": "{TV_LOCALE}",
      "toolbar_bg": "#0b0e11",
      "enable_publishing": false,
      "allow_symbol_change": true,
      "save_image": false,
      "hide_side_toolbar": false,
      "container_id": "tv"
    }});
  </script>
</body>
</html>
"""


class BottomDragBar(QWidget):
    def __init__(self, owner: "TradingViewDesktopWidget"):
        super().__init__(owner)
        self._owner = owner
        self.setFixedHeight(BOTTOM_BAR_H)
        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        self.setObjectName("BottomDragBar")

        self._dragging = False
        self._drag_off = QPoint()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_off = e.globalPosition().toPoint() - self._owner.frameGeometry().topLeft()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._owner.move(e.globalPosition().toPoint() - self._drag_off)
            self._owner._persist(pos_only=True)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._owner._persist(pos_only=False)
            e.accept()
            return
        super().mouseReleaseEvent(e)


class TVWebView(QWebEngineView):
    def __init__(self, owner: "TradingViewDesktopWidget"):
        super().__init__(owner)
        self._owner = owner

    def wheelEvent(self, e):
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            dy = e.angleDelta().y()
            cur = float(self.zoomFactor())
            if dy > 0:
                self._owner._set_zoom(cur + ZOOM_STEP)
            elif dy < 0:
                self._owner._set_zoom(cur - ZOOM_STEP)
            e.accept()
            return
        super().wheelEvent(e)


class TradingViewDesktopWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnBottomHint |
            Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        
        # Apply the overall window opacity mapping (0-255) -> (0.0-1.0)
        self.setWindowOpacity(max(0, min(255, WIDGET_OPACITY)) / 255.0)
        
        self.setWindowTitle("Trading View Charts")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)

        st = load_state()
        self._zoom = float(st.get("zoom", DEFAULT_ZOOM_FACTOR))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)   # bar == exact webview width
        root.setSpacing(0)

        self.view = TVWebView(self)
        self.view.setStyleSheet("border: 0px; outline: 0px;")
        self.view.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.view.page().zoomFactorChanged.connect(self._on_page_zoom_changed)
        self.view.loadFinished.connect(self._apply_zoom_after_load)

        self.view.setHtml(tradingview_html(TV_SYMBOL), baseUrl=QUrl("https://www.tradingview.com/"))
        root.addWidget(self.view, 1)

        self.drag_bar = BottomDragBar(self)
        root.addWidget(self.drag_bar, 0)

        self._grip = QSizeGrip(self)
        self._grip.setFixedSize(GRIP_SIZE, GRIP_SIZE)
        self._grip.setStyleSheet("QSizeGrip { background: transparent; }")

        self.setStyleSheet(f"""
            QWidget#BottomDragBar {{
                background: {BOTTOM_BAR_BG};
                border: {BOTTOM_BAR_BORDER_W}px solid {BOTTOM_BAR_BORDER};
                border-radius: {BOTTOM_BAR_RADIUS}px;
            }}
            QToolTip {{
                background-color: #2b2b2b;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 10px;
                padding: 10px;
                font-size: 12px;
            }}
        """)

        x = int(st.get("x", DEFAULT_X))
        y = int(st.get("y", DEFAULT_Y))
        w = int(st.get("w", DEFAULT_W))
        h = int(st.get("h", DEFAULT_H))
        self.resize(w, h)
        self.move(x, y)

        self.view.setZoomFactor(self._zoom)
        self._persist_zoom()
        self._place_grip()

        hide_from_taskbar_later(self)

    def _place_grip(self):
        self._grip.move(
            max(0, self.width() - GRIP_SIZE - GRIP_MARGIN),
            max(0, self.height() - GRIP_SIZE - GRIP_MARGIN),
        )

    def _show_info_tooltip(self):
        # Show near cursor; clamp-ish by letting Qt handle screen bounds
        QToolTip.showText(QCursor.pos(), SYMBOL_INFO_TEXT, self)

    def _clamp_zoom(self, z: float) -> float:
        return max(ZOOM_MIN, min(ZOOM_MAX, float(z)))

    def _set_zoom(self, z: float):
        z = self._clamp_zoom(z)
        self._zoom = z
        self.view.setZoomFactor(z)
        self._persist_zoom()

    def _on_page_zoom_changed(self, z: float):
        z = self._clamp_zoom(z)
        if abs(z - self._zoom) > 1e-6:
            self._zoom = z
        self._persist_zoom()

    def _apply_zoom_after_load(self, ok: bool):
        self.view.setZoomFactor(self._zoom)

    def _persist_zoom(self):
        save_state({"zoom": float(self._zoom)})

    def moveEvent(self, e):
        self._persist(pos_only=True)
        super().moveEvent(e)

    def resizeEvent(self, e):
        self._persist(pos_only=False)
        self._place_grip()
        super().resizeEvent(e)

    def _persist(self, pos_only=False):
        g = self.frameGeometry().topLeft()
        data = {"x": int(g.x()), "y": int(g.y()), "zoom": float(self._zoom)}
        if not pos_only:
            data["w"] = int(self.width())
            data["h"] = int(self.height())
        save_state(data)

    def closeEvent(self, e):
        self._persist(pos_only=False)
        try:
            self.view.setUrl(QUrl("about:blank"))
            self.view.deleteLater()
        except Exception:
            pass
        super().closeEvent(e)

    def _ctx(self, pos):
        m = QMenu(self)
        m.setStyleSheet("""
            QMenu {
                background-color: #2b2b2b;
                border: 1px solid #3a3a3a;
                border-radius: 10px;
                padding: 6px;
                color: #f0f0f0;
            }
            QMenu::item {
                padding: 6px 12px;
                border-radius: 6px;
                background: transparent;
            }
            QMenu::item:selected { background-color: #3a3a3a; }
            QMenu::separator { height: 1px; background: #3a3a3a; margin: 6px 4px; }
        """)

        a_info = QAction("Info", self)
        a_info.triggered.connect(self._show_info_tooltip)

        a_close = QAction("Close", self)
        a_close.triggered.connect(self.close)

        m.addAction(a_info)
        m.addSeparator()
        m.addAction(a_close)
        m.exec(self.mapToGlobal(pos))


def main():
    app = QApplication(sys.argv)
    w = TradingViewDesktopWidget()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()