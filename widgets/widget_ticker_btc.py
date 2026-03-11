# glance_widget_unified.py
# One script for BOTH crypto (CoinGecko→CMC→LiveCoinWatch fallback) and TradFi (yfinance).
# Three independent elements:
#  - Ticker (LEFT-click toggle → TradingView EMBED window open/close; RIGHT-click → context menu only)
#  - Price line (left half = drag window, right half = push/pull width; slash stays centered)
#  - Percent block (push/pull horizontally; can touch the ticker)
#
# Per-ticker state (x,y, price_w, pct_gap) saved in widget_positions.json.

import sys, os, json, time, bisect
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import requests

from PyQt6.QtCore import Qt, QTimer, QPoint, QEvent, QUrl
from PyQt6.QtGui import QCursor, QAction
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QMenu, QSizePolicy,
    QPushButton, QSizeGrip
)
from PyQt6.QtWebEngineWidgets import QWebEngineView

if __package__:
    from .widget_core import hide_from_taskbar_later
else:
    from widget_core import hide_from_taskbar_later


# =============== MODE / SELECTION ===============
MODE = "crypto"          # "crypto" or "tradfi"

# Crypto (when MODE = "crypto")
CRYPTO_ID   = "bitcoin"  # CoinGecko id
CRYPTO_TICK = "BTC"      # visible ticker (also used for CMC/LCW)

# TradFi (when MODE = "tradfi")
TRADFI_YF   = "^GSPC"
TRADFI_TICK = "S&P 500"

TV_SYMBOL_OVERRIDE = {
    "^GSPC": "SPX",
    "^IXIC": "IXIC",
    "^FTSE": "OANDA:UK100GBP",   # or "FOREXCOM:UK100"
}

# =============== TRADINGVIEW EMBED WINDOW CONSTANTS ===============
TV_WIN_X = 748
TV_WIN_Y = 199
TV_WIN_W = 1459
TV_WIN_H = 803

TV_INTERVAL = "D"        # "1", "5", "15", "60", "D", "W", "M"
TV_THEME    = "dark"     # "light" or "dark"
TV_LOCALE   = "en"
TV_STYLE    = "1"        # TradingView style preset string

TV_TITLEBAR_H  = 18
TV_TITLEBAR_BG = "#202020"

# =============== API KEYS FROM FILES ===============
def _read_key_from_file(filename: str) -> str:
    try:
        root = Path(__file__).resolve().parent
        key_path = root / "keys" / filename
        if key_path.exists():
            return key_path.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""

CMC_API_KEY = _read_key_from_file("cmc_api.txt")
LCW_API_KEY = _read_key_from_file("lcw_api.txt")

# =============== LOOK & FEEL ===============
WINDOW_OPACITY = 135   # 0..255
REFRESH_MS     = 120_000

FS_TICK   = 24
FS_PRICE  = 23
FS_PCT    = 14
FS_PCTLBL = 13
ALPHA_TXT = 160

INIT_PRICE_W = 220
INIT_PCT_GAP = 7

MIN_PRICE_W  = 140
MAX_PRICE_W  = 800
MIN_PCT_GAP  = 0
MAX_PCT_GAP  = 2000

p = Path(__file__).resolve()
STATE_FILE = p.parent / "widget_positions" / f"{p.stem}.json"
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

# =============== PERSISTENCE KEYS ===============
def state_key() -> str:
    return (f"GlanceUnified_v14_CRYPTO_{CRYPTO_TICK.upper()}"
            if MODE.lower() == "crypto"
            else f"GlanceUnified_v14_TRADFI_{TRADFI_YF.upper()}")

def load_state() -> Dict[str, Any]:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8")).get(state_key(), {})
    except Exception:
        pass
    return {}

def save_state(partial: Dict[str, Any]):
    try:
        all_data = {}
        if STATE_FILE.exists():
            try:
                all_data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if not isinstance(all_data, dict): all_data = {}
            except Exception:
                all_data = {}
        d = all_data.get(state_key(), {})
        d.update(partial)
        all_data[state_key()] = d
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(all_data, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception:
        pass

# =============== HELPERS ===============
def rgba_white(a=ALPHA_TXT): return f"rgba(255,255,255,{a})"
def green(a=ALPHA_TXT):      return f"rgba(9,233,9,{a})"
def red(a=ALPHA_TXT):        return f"rgba(255,0,0,{a})"

def tv_symbol() -> str:
    if MODE.lower() == "crypto":
        return f"{CRYPTO_TICK.upper()}USD"
    return TV_SYMBOL_OVERRIDE.get(TRADFI_YF, TRADFI_YF)

def fx_usd_gbp(timeout=6) -> Optional[float]:
    for url in ("https://open.er-api.com/v6/latest/USD",
                "https://api.exchangerate-api.com/v4/latest/USD"):
        try:
            r = requests.get(url, timeout=timeout, headers=_http_headers())
            d = r.json()
            rates = d.get("rates") or d
            if rates and "GBP" in rates:
                return float(rates["GBP"])
        except Exception:
            continue
    return None

class Snap:
    def __init__(self, usd, gbp, p1h, p24, p7, p30, prev1h=None, prev24=None, prev7=None, prev30=None):
        self.usd = usd; self.gbp = gbp
        self.p1h = p1h; self.p24 = p24; self.p7 = p7; self.p30 = p30
        self.prev1h = prev1h; self.prev24 = prev24; self.prev7 = prev7; self.prev30 = prev30

def pct_from(cur, past):
    try:
        if cur is not None and past is not None and past > 0:
            return (cur - past) / past * 100.0
    except Exception:
        pass
    return None

# =============== HTTP SESSION / RETRY ===============
def _http_headers() -> Dict[str, str]:
    return {
        "User-Agent": "glance-widget/1.0 (+https://example.local)",
        "Accept": "application/json,text/plain,*/*",
    }

_SESS = requests.Session()
_SESS.headers.update(_http_headers())

def _get_json(url: str, *, params=None, headers=None, timeout=8, tries=2, backoff=0.35):
    last_exc = None
    for i in range(max(1, tries)):
        try:
            r = _SESS.get(url, params=params, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_exc = e
            if i < tries - 1:
                time.sleep(backoff * (2 ** i))
    raise last_exc  # type: ignore

def _post_json(url: str, *, json_body=None, headers=None, timeout=8, tries=2, backoff=0.35):
    last_exc = None
    for i in range(max(1, tries)):
        try:
            r = _SESS.post(url, json=json_body, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_exc = e
            if i < tries - 1:
                time.sleep(backoff * (2 ** i))
    raise last_exc  # type: ignore

# =============== COINGECKO % COMPUTATION (STABLE) ===============
def _cg_prices_range_usd(cg_id: str, from_ts: int, to_ts: int) -> List[Tuple[int, float]]:
    j = _get_json(
        f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart/range",
        params={"vs_currency": "usd", "from": str(from_ts), "to": str(to_ts)},
        timeout=12,
        tries=2,
    )
    prices = j.get("prices") or []
    out: List[Tuple[int, float]] =[]
    for it in prices:
        try:
            tms = int(it[0])
            px = float(it[1])
            out.append((tms, px))
        except Exception:
            continue
    out.sort(key=lambda x: x[0])
    return out

def _nearest_price(prices: List[Tuple[int, float]], target_ms: int) -> Optional[float]:
    if not prices:
        return None
    ts_list = [t for t, _ in prices]
    idx = bisect.bisect_left(ts_list, target_ms)
    if idx <= 0:
        return prices[0][1]
    if idx >= len(prices):
        return prices[-1][1]
    t0, p0 = prices[idx - 1]
    t1, p1 = prices[idx]
    return p0 if abs(target_ms - t0) <= abs(t1 - target_ms) else p1

def _cg_percentages_from_range(cg_id: str) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float],
                                                    Optional[float], Optional[float], Optional[float], Optional[float]]:
    now_s = int(time.time())
    from_s = now_s - (31 * 24 * 3600) - (3 * 3600)
    to_s   = now_s + 60

    prices = _cg_prices_range_usd(cg_id, from_s, to_s)
    now_ms = now_s * 1000

    p_now = _nearest_price(prices, now_ms)
    p_1h  = _nearest_price(prices, (now_s - 3600) * 1000)
    p_24h = _nearest_price(prices, (now_s - 86400) * 1000)
    p_7d  = _nearest_price(prices, (now_s - 7 * 86400) * 1000)
    p_30d = _nearest_price(prices, (now_s - 30 * 86400) * 1000)

    p1h  = pct_from(p_now, p_1h)
    p24  = pct_from(p_now, p_24h)
    p7   = pct_from(p_now, p_7d)
    p30  = pct_from(p_now, p_30d)

    return p1h, p24, p7, p30, p_1h, p_24h, p_7d, p_30d

def _cg_price_usd_gbp(cg_id: str) -> Tuple[Optional[float], Optional[float]]:
    j = _get_json(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": cg_id, "vs_currencies": "usd,gbp"},
        timeout=8,
        tries=2,
    )
    cur = j.get(cg_id) or {}
    usd = cur.get("usd")
    gbp = cur.get("gbp")
    try: usd = float(usd) if usd is not None else None
    except Exception: usd = None
    try: gbp = float(gbp) if gbp is not None else None
    except Exception: gbp = None
    return usd, gbp

def _cg_percentages_from_markets(cg_id: str) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    j = _get_json(
        "https://api.coingecko.com/api/v3/coins/markets",
        params={
            "vs_currency": "usd",
            "ids": cg_id,
            "price_change_percentage": "1h,24h,7d,30d",
        },
        timeout=10,
        tries=2,
    )
    if not isinstance(j, list) or not j:
        return None, None, None, None
    row = j[0]
    def f(k):
        v = row.get(k)
        try:
            return float(v) if v is not None else None
        except Exception:
            return None
    return (
        f("price_change_percentage_1h_in_currency"),
        f("price_change_percentage_24h_in_currency"),
        f("price_change_percentage_7d_in_currency"),
        f("price_change_percentage_30d_in_currency"),
    )

# Crypto: CG (stable computed) → CMC → LCW
def fetch_crypto() -> Optional[Snap]:
    try:
        cg_id = CRYPTO_ID
        usd, gbp = _cg_price_usd_gbp(cg_id)
        if usd is None:
            raise RuntimeError("CG missing usd")

        try:
            p1h, p24, p7, p30, prev1h, prev24, prev7, prev30 = _cg_percentages_from_range(cg_id)
        except Exception:
            p1h, p24, p7, p30 = _cg_percentages_from_markets(cg_id)
            prev1h = prev24 = prev7 = prev30 = None

        if gbp is None:
            rate = fx_usd_gbp() or 0.78
            gbp = usd * rate

        return Snap(usd, gbp, p1h, p24, p7, p30, prev1h=prev1h, prev24=prev24, prev7=prev7, prev30=prev30)
    except Exception:
        pass

    try:
        if not CMC_API_KEY:
            raise RuntimeError("no CMC key")
        r = _get_json(
            "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest",
            params={"symbol": CRYPTO_TICK.upper()},
            headers={"X-CMC_PRO_API_KEY": CMC_API_KEY, **_http_headers()},
            timeout=8,
            tries=2,
        )
        d = r["data"][CRYPTO_TICK.upper()][0]["quote"]["USD"]
        usd = float(d["price"])
        p1h = float(d.get("percent_change_1h"))  if d.get("percent_change_1h")  is not None else None
        p24 = float(d.get("percent_change_24h")) if d.get("percent_change_24h") is not None else None
        p7  = float(d.get("percent_change_7d"))  if d.get("percent_change_7d")  is not None else None
        p30 = float(d.get("percent_change_30d")) if d.get("percent_change_30d") is not None else None
        rate = fx_usd_gbp() or 0.78

        def prev_from_pct(curv, pctv):
            try:
                return curv / (1.0 + (pctv / 100.0)) if pctv is not None else None
            except Exception:
                return None

        return Snap(
            usd, usd * rate, p1h, p24, p7, p30,
            prev1h=prev_from_pct(usd, p1h),
            prev24=prev_from_pct(usd, p24),
            prev7=prev_from_pct(usd, p7),
            prev30=prev_from_pct(usd, p30),
        )
    except Exception:
        pass

    try:
        if not LCW_API_KEY:
            raise RuntimeError("no LCW key")
        j = _post_json(
            "https://api.livecoinwatch.com/coins/single",
            headers={"x-api-key": LCW_API_KEY, "content-type": "application/json", **_http_headers()},
            json_body={"currency": "USD", "code": CRYPTO_TICK.upper(), "meta": True},
            timeout=8,
            tries=2,
        )
        usd = float(j.get("rate"))
        rate = fx_usd_gbp() or 0.78
        delta = j.get("delta") or {}

        def cv_to_percent(x):
            try:
                return (float(x) - 1.0) * 100.0
            except Exception:
                return None

        p1h_pct = cv_to_percent(delta.get("hour"))
        p24_pct = cv_to_percent(delta.get("day"))
        p7_pct  = cv_to_percent(delta.get("week"))
        p30_pct = cv_to_percent(delta.get("month"))

        def prev_from_pct(curv, pctv):
            try:
                return curv / (1.0 + (pctv / 100.0)) if pctv is not None else None
            except Exception:
                return None

        return Snap(
            usd, usd * rate, p1h_pct, p24_pct, p7_pct, p30_pct,
            prev1h=prev_from_pct(usd, p1h_pct),
            prev24=prev_from_pct(usd, p24_pct),
            prev7=prev_from_pct(usd, p7_pct),
            prev30=prev_from_pct(usd, p30_pct),
        )
    except Exception:
        pass

    return None

def fetch_tradfi() -> Optional[Snap]:
    try:
        import yfinance as yf
        t = yf.Ticker(TRADFI_YF)

        hist = t.history(period="31d")
        if hist.empty: return None
        cur = float(hist["Close"].iloc[-1])
        p1  = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
        p7  = float(hist["Close"].iloc[-6]) if len(hist) >= 6 else None
        p30 = float(hist["Close"].iloc[0])  if len(hist) >= 1 else None

        p1h = None
        try:
            ih = t.history(period="2d", interval="60m")
            if not ih.empty and len(ih["Close"]) >= 2:
                last = float(ih["Close"].iloc[-1])
                prev = float(ih["Close"].iloc[-2])
                p1h = pct_from(last, prev)
        except Exception:
            pass

        rate = fx_usd_gbp() or 0.78
        return Snap(cur, cur * rate, p1h, pct_from(cur, p1), pct_from(cur, p7), pct_from(cur, p30))
    except Exception:
        return None


# =============== TRADINGVIEW EMBED WINDOW ===============
def _tradingview_html(symbol: str) -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>TradingView Embed</title>
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

class _TitleBar(QWidget):
    def __init__(self, parent: "TradingViewWindow"):
        super().__init__(parent)
        self._win = parent
        self.setFixedHeight(TV_TITLEBAR_H)
        self.setStyleSheet(f"""
            QWidget {{ background: {TV_TITLEBAR_BG}; }}
            QLabel  {{ color: rgba(255,255,255,210); font: 600 11px 'Segoe UI'; }}
            QPushButton {{
                border: none;
                background: transparent;
                color: rgba(255,255,255,210);
                font: 700 14px 'Segoe UI';
                padding: 0 8px;
                margin: 0;
            }}
            QPushButton:hover {{ background: #B51623; color: white; }}
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 4, 0)
        lay.setSpacing(6)

        self.title = QLabel("")
        self.title.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        self.btn_close = QPushButton("×")
        self.btn_close.setFixedHeight(TV_TITLEBAR_H)
        self.btn_close.clicked.connect(self._win.close)

        lay.addWidget(self.title, 1)
        lay.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignRight)

        self._dragging = False
        self._drag_off = QPoint()

    def set_text(self, t: str):
        self.title.setText(t)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_off = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._win.move(e.globalPosition().toPoint() - self._drag_off)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            e.accept()
            return
        super().mouseReleaseEvent(e)

class TradingViewWindow(QWidget):
    def __init__(self, symbol: str):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Window
        )

        self.setStyleSheet(f"background: {TV_TITLEBAR_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = _TitleBar(self)
        root.addWidget(self.titlebar, 0)

        self.view = QWebEngineView()
        root.addWidget(self.view, 1)

        grip_wrap = QWidget(self)
        grip_wrap.setStyleSheet(f"background: {TV_TITLEBAR_BG};")
        grip_lay = QHBoxLayout(grip_wrap)
        grip_lay.setContentsMargins(0, 0, 4, 4)
        grip_lay.addStretch(1)
        self._grip = QSizeGrip(grip_wrap)
        grip_lay.addWidget(self._grip, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        root.addWidget(grip_wrap, 0)

        self.resize(TV_WIN_W, TV_WIN_H)
        self.move(TV_WIN_X, TV_WIN_Y)

        self.set_symbol(symbol)

        hide_from_taskbar_later(self)

    def set_symbol(self, symbol: str):
        self.titlebar.set_text(f"TradingView — {symbol}")
        self.view.setHtml(_tradingview_html(symbol), baseUrl=QUrl("https://www.tradingview.com/"))

    def closeEvent(self, e):
        try:
            self.view.setUrl(QUrl("about:blank"))
            self.view.deleteLater()
        except Exception:
            pass
        e.accept()


# =============== WIDGET ===============
class GlanceWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._is_hovered = False
        
        self.setWindowTitle(p.stem)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnBottomHint |
            Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(WINDOW_OPACITY / 255.0)

        self._tv_win: Optional[TradingViewWindow] = None
        self._tv_open = False

        # state
        st = load_state()
        self.price_w = int(st.get("price_w", INIT_PRICE_W))
        self.pct_gap = int(st.get("pct_gap", INIT_PCT_GAP))
        self.restore_pos = (int(st["x"]), int(st["y"])) if "x" in st and "y" in st else None

        # dragging/resizing flags
        self.dragging_win = False
        self.resizing_price = False
        self.dragging_pct = False
        self.mouse_grabbed = False
        self.drag_off = QPoint()
        self.start_price_w = self.price_w
        self.start_pct_gap = self.pct_gap

        # layout
        root = QVBoxLayout(self); root.setContentsMargins(10, 8, 10, 8); root.setSpacing(8)

        # row 1: TICKER | spacer(pct_gap) | PCT block
        row1 = QHBoxLayout(); row1.setContentsMargins(0, 0, 0, 0); row1.setSpacing(0)

        self.ticker = QLabel(TRADFI_TICK if MODE == "tradfi" else CRYPTO_TICK)
        self.ticker.setStyleSheet(f"color:{rgba_white()}; font:700 {FS_TICK}px 'Segoe UI'; background:transparent;")
        self.ticker.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.ticker.mousePressEvent = self._ticker_mouse_press
        row1.addWidget(self.ticker, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.gap_spacer = QWidget(); self.gap_spacer.setFixedWidth(self.pct_gap)
        self.gap_spacer.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.gap_spacer.setStyleSheet("background:transparent;")
        row1.addWidget(self.gap_spacer, 0)

        self.pct_box = QWidget(); self.pct_box.setStyleSheet("background:transparent;")
        pctg = QGridLayout(self.pct_box); pctg.setContentsMargins(0, 0, 0, 0); pctg.setHorizontalSpacing(12); pctg.setVerticalSpacing(0)

        self.lbl1h = QLabel("1h"); self.lbl24 = QLabel("24h"); self.lbl7 = QLabel("7d"); self.lbl30 = QLabel("30d")
        for w in (self.lbl1h, self.lbl24, self.lbl7, self.lbl30):
            w.setStyleSheet(f"color:{rgba_white()}; font:{FS_PCTLBL}px 'Segoe UI'; background:transparent;")
            w.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.p1h = QLabel("—"); self.p24 = QLabel("—"); self.p7 = QLabel("—"); self.p30 = QLabel("—")
        for w in (self.p1h, self.p24, self.p7, self.p30):
            w.setStyleSheet(f"color:{rgba_white()}; font:{FS_PCT}px 'Segoe UI'; background:transparent;")
            w.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        pctg.addWidget(self.lbl1h, 0, 0); pctg.addWidget(self.lbl24, 0, 1); pctg.addWidget(self.lbl7, 0, 2); pctg.addWidget(self.lbl30, 0, 3)
        pctg.addWidget(self.p1h, 1, 0);   pctg.addWidget(self.p24, 1, 1);   pctg.addWidget(self.p7, 1, 2);   pctg.addWidget(self.p30, 1, 3)

        row1.addWidget(self.pct_box, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(row1)

        # row 2: PRICE box
        self.price_box = QWidget(); self.price_box.setStyleSheet("background:transparent;")
        self.price_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.price_box.setFixedWidth(self.price_w)

        grid = QGridLayout(self.price_box); grid.setContentsMargins(0, 0, 0, 0); grid.setHorizontalSpacing(0)
        self.usd = QLabel("—"); self.slash = QLabel(" "); self.gbp = QLabel("—")
        for w in (self.usd, self.slash, self.gbp):
            w.setStyleSheet(f"color:{rgba_white()}; font:{FS_PRICE}px 'Segoe UI'; background:transparent;")
        self.usd.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.slash.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.gbp.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self.usd, 0, 0)
        grid.addWidget(self.slash, 0, 1)
        grid.addWidget(self.gbp, 0, 2)

        root.addWidget(self.price_box, 0, Qt.AlignmentFlag.AlignLeft)

        # context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)

        # event filters
        self._watch(self.price_box)
        self._watch(self.pct_box)

        if self.restore_pos:
            self.move(self.restore_pos[0], self.restore_pos[1])

        self._last = {"usd": None, "gbp": None, "p1h": None, "p24": None, "p7": None, "p30": None,
                      "prev1h": None, "prev24": None, "prev7": None, "prev30": None}
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(REFRESH_MS)
        QTimer.singleShot(0, self.refresh)

        hide_from_taskbar_later(self)

    def enterEvent(self, e):
        self._is_hovered = True
        self.update_ui()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._is_hovered = False
        self.update_ui()
        super().leaveEvent(e)

    def update_ui(self):
        if not hasattr(self, "_last"):
            return
            
        merged = self._last
        have_any = any(v is not None for v in merged.values())

        # Determine Alpha strictly for Text styling based on hover state
        alpha = 255 if getattr(self, "_is_hovered", False) else ALPHA_TXT
        c_white = f"rgba(255,255,255,{alpha})"
        c_green = f"rgba(9,233,9,{alpha})"
        c_red   = f"rgba(255,0,0,{alpha})"

        # Reapply text colors with appropriate alpha
        self.ticker.setStyleSheet(f"color:{c_white}; font:700 {FS_TICK}px 'Segoe UI'; background:transparent;")
        for w in (self.lbl1h, self.lbl24, self.lbl7, self.lbl30):
            w.setStyleSheet(f"color:{c_white}; font:{FS_PCTLBL}px 'Segoe UI'; background:transparent;")
        for w in (self.usd, self.slash, self.gbp):
            w.setStyleSheet(f"color:{c_white}; font:{FS_PRICE}px 'Segoe UI'; background:transparent;")

        if not have_any:
            self.usd.setText("—"); self.gbp.setText("—")
            for w in (self.p1h, self.p24, self.p7, self.p30):
                w.setText("—")
                w.setStyleSheet(f"color:{c_white}; font:{FS_PCT}px 'Segoe UI'; background:transparent;")
            return

        if merged["usd"] is not None:
            self.usd.setText(f"${merged['usd']:,.2f}")
        else:
            self.usd.setText("—")

        if merged["gbp"] is not None:
            self.gbp.setText(f"£{merged['gbp']:,.2f}")
        else:
            self.gbp.setText("—")

        def pf(v):
            if v is None:
                return "—", c_white
            return f"{v:+.2f}%", (c_green if v > 0 else c_red if v < 0 else c_white)

        t1h, col1h = pf(merged["p1h"])
        t24, col24 = pf(merged["p24"])
        t7,  col7  = pf(merged["p7"])
        t30, col30 = pf(merged["p30"])

        self.p1h.setText(t1h); self.p1h.setStyleSheet(f"color:{col1h}; font:{FS_PCT}px 'Segoe UI'; background:transparent;")
        self.p24.setText(t24); self.p24.setStyleSheet(f"color:{col24}; font:{FS_PCT}px 'Segoe UI'; background:transparent;")
        self.p7.setText(t7);   self.p7.setStyleSheet(f"color:{col7};  font:{FS_PCT}px 'Segoe UI'; background:transparent;")
        self.p30.setText(t30); self.p30.setStyleSheet(f"color:{col30}; font:{FS_PCT}px 'Segoe UI'; background:transparent;")

        self.price_box.setFixedWidth(self.price_w)
        self.gap_spacer.setFixedWidth(self.pct_gap)
        self.adjustSize()

    def _ticker_mouse_press(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            # let Qt generate the customContextMenuRequested signal at this position
            self._ctx(self.mapFromGlobal(e.globalPosition().toPoint()))
            e.accept()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self.toggle_tradingview()
            e.accept()
            return

    def toggle_tradingview(self):
        if self._tv_open and self._tv_win is not None:
            self._tv_win.close()
            return
        self.open_tradingview()

    def open_tradingview(self):
        sym = tv_symbol()
        if self._tv_win is None or not self._tv_win.isVisible():
            self._tv_win = TradingViewWindow(sym)
            self._tv_open = True
            self._tv_win.destroyed.connect(self._on_tv_destroyed)
        else:
            self._tv_win.set_symbol(sym)
            self._tv_open = True
        self._tv_win.show()
        self._tv_win.raise_()
        self._tv_win.activateWindow()

    def _on_tv_destroyed(self, *_):
        self._tv_win = None
        self._tv_open = False

    def _watch(self, w: QWidget):
        w.installEventFilter(self)
        for c in w.findChildren(QWidget):
            c.installEventFilter(self)

    # ----- data refresh -----
    def refresh(self):
        if not hasattr(self, "_last"):
            self._last = {"usd": None, "gbp": None, "p1h": None, "p24": None, "p7": None, "p30": None,
                          "prev1h": None, "prev24": None, "prev7": None, "prev30": None}

        snap = fetch_crypto() if MODE == "crypto" else fetch_tradfi()

        def pick(new, old):
            return new if new is not None else old

        if snap:
            merged = {
                "usd": pick(snap.usd, self._last["usd"]),
                "gbp": pick(snap.gbp, self._last["gbp"]),
                "p1h": pick(snap.p1h, self._last["p1h"]),
                "p24": pick(snap.p24, self._last["p24"]),
                "p7":  pick(snap.p7,  self._last["p7"]),
                "p30": pick(snap.p30, self._last["p30"]),
                "prev1h": pick(snap.prev1h, self._last["prev1h"]),
                "prev24": pick(snap.prev24, self._last["prev24"]),
                "prev7":  pick(snap.prev7,  self._last["prev7"]),
                "prev30": pick(snap.prev30, self._last["prev30"]),
            }
        else:
            merged = dict(self._last)

        self._last.update(merged)
        
        # Apply data explicitly to UI and trigger correct alpha logic
        self.update_ui()

        def fnum(x):
            try:
                return f"{x:,.8f}" if x is not None and x < 1 else f"{x:,.2f}"
            except Exception:
                return "None"

        label = CRYPTO_TICK if MODE == "crypto" else TRADFI_TICK
        print(
            f"[DEBUG] {label} prev prices USD | "
            f"1h: {fnum(merged['prev1h'])} | "
            f"24h: {fnum(merged['prev24'])} | "
            f"7d: {fnum(merged['prev7'])} | "
            f"30d: {fnum(merged['prev30'])} | "
            f"now: {fnum(merged['usd'])}"
        )

    # ----- context menu -----
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
        a = QAction("Close", self)
        a.triggered.connect(self.close)
        m.addAction(a)
        m.exec(self.mapToGlobal(pos))

    # ----- mouse handling (drag / push-pull) -----
    def eventFilter(self, obj, ev):
        if obj is self.price_box or obj.parent() is self.price_box:
            if ev.type() == QEvent.Type.Enter:
                self._update_price_cursor()
            elif ev.type() == QEvent.Type.MouseMove:
                self._update_price_cursor()
            elif ev.type() == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                local_x = self.price_box.mapFromGlobal(ev.globalPosition().toPoint()).x()
                half = self.price_box.width() // 2
                if local_x < half:
                    self.dragging_win = True
                    self.drag_off = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    self.grabMouse(); self.mouse_grabbed = True
                    self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                else:
                    self.resizing_price = True
                    self.drag_off = ev.globalPosition().toPoint()
                    self.start_price_w = self.price_w
                    self.grabMouse(); self.mouse_grabbed = True
                    self.setCursor(QCursor(Qt.CursorShape.SplitHCursor))
            elif ev.type() == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
                self._stop_all_mouse_ops()

        if obj is self.pct_box or obj.parent() is self.pct_box:
            if ev.type() == QEvent.Type.Enter:
                self.pct_box.setCursor(QCursor(Qt.CursorShape.SplitHCursor))
            elif ev.type() == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                self.dragging_pct = True
                self.drag_off = ev.globalPosition().toPoint()
                self.start_pct_gap = self.pct_gap
                self.grabMouse(); self.mouse_grabbed = True
                self.setCursor(QCursor(Qt.CursorShape.SplitHCursor))
            elif ev.type() == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
                self._stop_all_mouse_ops()
        return super().eventFilter(obj, ev)

    def mouseMoveEvent(self, e):
        gp = e.globalPosition().toPoint()
        if self.dragging_win:
            self.move(gp - self.drag_off)
            self._persist(pos_only=True)
        elif self.resizing_price:
            dx = gp.x() - self.drag_off.x()
            self.price_w = max(MIN_PRICE_W, min(MAX_PRICE_W, self.start_price_w + dx))
            self.price_box.setFixedWidth(self.price_w)
            self.adjustSize()
        elif self.dragging_pct:
            dx = gp.x() - self.drag_off.x()
            self.pct_gap = max(MIN_PCT_GAP, min(MAX_PCT_GAP, self.start_pct_gap + dx))
            self.gap_spacer.setFixedWidth(self.pct_gap)
            self.adjustSize()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._stop_all_mouse_ops()
        super().mouseReleaseEvent(e)

    def _stop_all_mouse_ops(self):
        if self.mouse_grabbed:
            self.releaseMouse()
            self.mouse_grabbed = False
        if self.dragging_win or self.resizing_price or self.dragging_pct:
            self.dragging_win = self.resizing_price = self.dragging_pct = False
            self.unsetCursor()
            self._persist()

    def _update_price_cursor(self):
        x = self.price_box.mapFromGlobal(QCursor.pos()).x()
        half = self.price_box.width() // 2
        self.price_box.setCursor(QCursor(Qt.CursorShape.SizeAllCursor if x < half else Qt.CursorShape.SplitHCursor))

    def moveEvent(self, e):
        self._persist(pos_only=True)
        super().moveEvent(e)

    def _persist(self, pos_only=False):
        g = self.frameGeometry().topLeft()
        data = {"x": int(g.x()), "y": int(g.y())}
        if not pos_only:
            data["price_w"] = int(self.price_w)
            data["pct_gap"] = int(self.pct_gap)
        save_state(data)

# =============== RUN ===============
def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    w = GlanceWidget()
    if not w.restore_pos:
        scr = QApplication.primaryScreen().availableGeometry()
        w.move(scr.left() + 120, scr.top() + 140)
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()