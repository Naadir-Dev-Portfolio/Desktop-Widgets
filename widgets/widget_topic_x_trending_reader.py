#!/usr/bin/env python3
# requirements: PyQt6

import sys, csv, time, json, subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QPoint, QSize, QEvent, QRect, QUrl
from PyQt6.QtGui import QCursor, QAction, QPixmap, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QMenu,
    QScrollArea, QFrame, QSizePolicy
)

if __package__:
    from .widget_core import hide_from_taskbar_later
else:
    from widget_core import hide_from_taskbar_later

# =================== CONFIG ===================
ALIGN = "left"  # "left" or "right"

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "webScrapes" / "trends.csv"
SCRAPER  = ROOT / "widget_topic_x_trending_scraper.py"

# Relative icon path
_GUI_DIR = ROOT.parent
REFRESH_ICON = str(_GUI_DIR / "resources" / "icons" / "refresh.png")

WINDOW_OPACITY = 100
FS_TITLE = 26
FS_ROW   = 16
FS_TOPIC = FS_ROW + 2
FS_SUB   = 14
ALPHA_TXT = 160
ROW_SPACING = 4
SCROLL_MARGINS = (10, 10, 10, 8)

AUTO_SCRAPE_MINUTES = 25
MTIME_POLL_MS = 1_000

# ---------- State persistence ----------
p = Path(__file__).resolve()
STATE_FILE = p.parent / "widget_positions" / f"{p.stem}.json"
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
STATE_KEY  = "X_TrendingReader"

# Layout / behavior — narrower columns for short trending topics
COL_WIDTH    = 210
COL_GAP_INIT = 105
COL_GAP_MIN  = -COL_WIDTH + 10
COL_GAP_MAX  = 4000
DEFAULT_APP_WIDTH = 900
MIN_APP_WIDTH = 300

LIST_HEIGHT = 230

# Right-edge resize grab zone — generous so it's easy to grab
EDGE_PX = 28

# ---------- Hit-test background ----------
HIT_BG = "rgba(0, 0, 0, 2)"

# ---------- Region display names ----------
REGION_DISPLAY = {
    "united-kingdom": "United Kingdom",
    "united-states":  "United States",
    "japan":          "Japan",
    "russia":         "Russia",
    "germany":        "Germany",
}

# =================== STYLES ===================
SCROLLBAR_V_STYLE = """
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
    QScrollBar::handle:vertical:hover {
        background: #777777;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
"""

SCROLLBAR_H_STYLE = """
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
    QScrollBar::handle:horizontal:hover {
        background: #777777;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
"""

TOOLTIP_STYLE = """
    QToolTip {
        background-color: #1a1a1a;
        color: #e0e0e0;
        border: 1px solid #3a3a3a;
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 10pt;
    }
"""

CONTEXT_MENU_STYLE = """
    QMenu { background-color: #2b2b2b; border: 1px solid #3a3a3a; border-radius: 10px; padding: 6px; color: #f0f0f0; }
    QMenu::item { padding: 6px 12px; border-radius: 6px; background: transparent; }
    QMenu::item:selected { background-color: #3a3a3a; }
"""

# =================== HELPERS ===================
def rgba_white(a=ALPHA_TXT): return f"rgba(255,255,255,{a})"
def align_flag(): return Qt.AlignmentFlag.AlignRight if ALIGN.lower() == "right" else Qt.AlignmentFlag.AlignLeft
def fmt_mmss(sec: int) -> str:
    if sec < 0: sec = 0
    return f"{sec//60:02d}:{sec%60:02d}"

def capitalize_topic(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s
    words = s.split()
    result = []
    for w in words:
        if w.isupper() and len(w) > 1:
            result.append(w)
        elif w.startswith("#"):
            result.append(w)
        else:
            result.append(w.capitalize())
    return " ".join(result)

def load_state():
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8")).get(STATE_KEY, {})
    except Exception: pass
    return {}

def save_state(partial: dict):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        base = {}
        if STATE_FILE.exists():
            try:
                base = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if not isinstance(base, dict): base = {}
            except Exception:
                base = {}
        d = base.get(STATE_KEY, {}); d.update(partial); base[STATE_KEY] = d
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(base, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception: pass

def read_csv_grouped(path: Path):
    order, by = [], {}
    if not path.exists(): return order, by
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                region = (row.get("region") or "").strip()
                topic  = (row.get("topic") or "").strip()
                url    = (row.get("url") or "").strip()
                try:    rank = int((row.get("rank") or "").strip())
                except: rank = None
                if not region: continue
                if region not in by:
                    by[region] = []; order.append(region)
                by[region].append({"rank": rank, "topic": topic, "url": url})
    except Exception: pass
    for lst in by.values():
        lst.sort(key=lambda x: (x["rank"] is None, x["rank"] if x["rank"] is not None else 10**9))
        for i, it in enumerate(lst, 1):
            if it["rank"] is None: it["rank"] = i
    return order, by

def _format_item(rank: int, topic: str) -> str:
    import html as _html
    shown = _html.escape(capitalize_topic(topic))
    num   = f'<span style="color:{rgba_white(180)}">{rank:02d}.</span>'
    if ALIGN.lower() == "right":
        return f'<span style="color:{rgba_white()}; text-decoration:none;">{shown}</span> {num}'
    return f'{num} <span style="color:{rgba_white()}; text-decoration:none;">{shown}</span>'

# =================== COLUMN WIDGETS ===================
class TopicRow(QLabel):
    def __init__(self, rank: int, topic: str, url: str, get_vbar):
        super().__init__()
        self.url = url or ""
        self.get_vbar = get_vbar
        self.dragging = False
        self.press_pos = None
        self.last_y = None
        self.drag_threshold = 6

        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setWordWrap(False)
        self.setStyleSheet(f"color:{rgba_white()}; font:{FS_TOPIC}px 'Segoe UI'; background:transparent;")
        self.setText(_format_item(rank, topic))
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self.setFixedWidth(COL_WIDTH)
        self.setToolTip(capitalize_topic(topic))
        self.setAlignment(align_flag() | Qt.AlignmentFlag.AlignTop)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.press_pos = e.position().toPoint()
            self.last_y = self.press_pos.y()
        e.accept()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self.press_pos is not None:
            y = e.position().toPoint().y()
            dy_total = y - self.press_pos.y()
            if not self.dragging and abs(dy_total) >= self.drag_threshold:
                self.dragging = True
            if self.dragging:
                dy_step = y - (self.last_y if self.last_y is not None else y)
                self.last_y = y
                vbar = self.get_vbar()
                if vbar:
                    vbar.setValue(vbar.value() - int(dy_step))
        e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if not self.dragging and self.url:
                QDesktopServices.openUrl(QUrl(self.url))
            self.dragging = False
            self.press_pos = None
            self.last_y = None
        e.accept()

class Column(QWidget):
    def __init__(self, title: str, draggable_header: bool, on_gap_delta=None):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self.setFixedWidth(COL_WIDTH)

        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(6)

        self.title = QLabel(title)
        self.title.setStyleSheet(f"color:{rgba_white()}; font:700 {FS_ROW+2}px 'Segoe UI'; background:transparent;")
        self.title.setAlignment(align_flag() | Qt.AlignmentFlag.AlignVCenter)
        v.addWidget(self.title, 0)

        self.scroller = QScrollArea()
        self.scroller.setWidgetResizable(True)
        self.scroller.setFrameShape(QFrame.Shape.NoFrame)
        self.scroller.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroller.setStyleSheet(
            f"QScrollArea {{ background: {HIT_BG}; border: none; }}" + SCROLLBAR_V_STYLE
        )
        self.scroller.viewport().setStyleSheet(f"background: {HIT_BG};")
        v.addWidget(self.scroller, 0)

        self.rows_widget = QWidget()
        self.rows_widget.setStyleSheet(f"background: {HIT_BG};")
        self.rows_box = QVBoxLayout(self.rows_widget)
        self.rows_box.setContentsMargins(0,0,0,0)
        self.rows_box.setSpacing(ROW_SPACING)
        self.scroller.setWidget(self.rows_widget)

        self._drag_header = draggable_header
        self._on_gap_delta = on_gap_delta
        self._dragging = False
        self._gx0 = 0
        if draggable_header:
            self.title.installEventFilter(self)
            self.title.setCursor(QCursor(Qt.CursorShape.SplitHCursor))

    def vbar(self): return self.scroller.verticalScrollBar()

    def add_rows(self, rows):
        while self.rows_box.count():
            it = self.rows_box.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()
        for rec in rows:
            self.rows_box.addWidget(
                TopicRow(rec["rank"], rec["topic"], rec["url"], self.vbar),
                0, align_flag() | Qt.AlignmentFlag.AlignTop
            )
        self.rows_box.addStretch(1)
        self.rows_widget.adjustSize()

    def eventFilter(self, obj, ev):
        if self._drag_header and obj is self.title:
            if ev.type() == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                self._dragging = True; self._gx0 = int(ev.globalPosition().toPoint().x()); return True
            if ev.type() == QEvent.Type.MouseMove and self._dragging and (ev.buttons() & Qt.MouseButton.LeftButton):
                gx = int(ev.globalPosition().toPoint().x()); dx = gx - self._gx0; self._gx0 = gx
                if callable(self._on_gap_delta): self._on_gap_delta(dx, persist=False); return True
            if ev.type() == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
                self._dragging = False
                if callable(self._on_gap_delta): self._on_gap_delta(0, persist=True); return True
        return super().eventFilter(obj, ev)

# -------------------- MULTI-COLUMN PANE --------------------
class ColumnsPane(QWidget):
    def __init__(self, on_gap_delta_for_index):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self.cols, self.titles, self.gaps = [], [], []
        self.on_gap_delta_for_index = on_gap_delta_for_index

    def _gap_key(self, idx):
        if ALIGN.lower() == "right":
            return f"before::{self.titles[idx]}"
        else:
            return f"after::{self.titles[idx]}"

    def build(self, sources_order, data_by_source, gaps_map):
        for c in self.cols:
            c.setParent(None); c.deleteLater()
        self.cols, self.titles, self.gaps = [], [], []

        self.titles = list(sources_order)
        n = len(self.titles)
        for idx, title in enumerate(self.titles):
            if ALIGN.lower() == "right":
                draggable = (idx != n-1)
            else:
                draggable = (idx != 0)
            def make_cb(i):
                return lambda dx, persist=False: self.on_gap_delta_for_index(i, dx, persist)
            display = REGION_DISPLAY.get(title, title.replace("-", " ").title())
            col = Column(display, draggable_header=draggable, on_gap_delta=make_cb(idx))
            col.setParent(self); col.show()
            col.add_rows(data_by_source.get(title, []))
            col.scroller.setFixedHeight(LIST_HEIGHT)
            self.cols.append(col)

        for i in range(n-1):
            key = self._gap_key(i if ALIGN.lower()=="left" else i+1)
            try: saved = int(gaps_map.get(key, COL_GAP_INIT))
            except Exception: saved = COL_GAP_INIT
            self.gaps.append(max(COL_GAP_MIN, min(COL_GAP_MAX, saved)))

        self._relayout()

    def desired_width(self):
        return (len(self.cols) * COL_WIDTH) + sum(self.gaps)

    def _relayout(self):
        if not self.cols: return
        t_h = max((c.title.sizeHint().height() for c in self.cols), default=FS_ROW+2)
        pane_h = t_h + LIST_HEIGHT
        total_w = self.desired_width()

        if ALIGN.lower() == "right":
            x = total_w - COL_WIDTH
            for i in reversed(range(len(self.cols))):
                self.cols[i].setGeometry(QRect(x, 0, COL_WIDTH, pane_h))
                if i > 0:
                    g = self.gaps[i-1]
                    x -= (COL_WIDTH + g)
        else:
            x = 0
            for i, col in enumerate(self.cols):
                col.setGeometry(QRect(x, 0, COL_WIDTH, pane_h))
                if i < len(self.gaps):
                    x += COL_WIDTH + self.gaps[i]

        self.setMinimumSize(max(1,total_w), pane_h)
        self.resize(max(1,total_w), pane_h)

# =================== MAIN WIDGET ===================
class TrendingReader(QWidget):
    def _is_on_right_edge(self, global_pos):
        """Check if a global screen position is within the right-edge resize zone."""
        local = self.mapFromGlobal(global_pos)
        return 0 <= local.y() <= self.height() and self.width() - local.x() <= EDGE_PX

    def __init__(self):
        super().__init__()
        self.setWindowTitle(p.stem)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnBottomHint |
            Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(max(0.05, min(1.0, WINDOW_OPACITY/255.0)))
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setMouseTracking(True)

        QApplication.instance().setStyleSheet(TOOLTIP_STYLE)

        st = load_state()
        self.restore_pos   = (int(st["x"]), int(st["y"])) if "x" in st and "y" in st else None
        self.restore_width = int(st["w"]) if "w" in st else None
        self.gaps_map = st.get("col_gaps", {})

        self.dragging = False; self.drag_off = QPoint()
        self.resizing = False
        self._drag_pending = False
        self._drag_origin = QPoint()
        self._drag_threshold = 4
        self._in_layout = False

        self.last_mtime = int(CSV_PATH.stat().st_mtime) if CSV_PATH.exists() else None
        self.sources_order, self.data_by_source = read_csv_grouped(CSV_PATH)

        self._scrape_proc = None; self._scrape_poll = None

        root = QVBoxLayout(self); root.setContentsMargins(*SCROLL_MARGINS); root.setSpacing(6)

        # --- Header row ---
        header = QWidget(); hb = QHBoxLayout(header)
        hb.setContentsMargins(0,0,0,0); hb.setSpacing(4)

        self.title_label = QLabel("Trending")
        self.title_label.setStyleSheet(f"color:{rgba_white()}; font:700 {FS_TITLE}px 'Segoe UI'; background:transparent;")
        self.title_label.setAlignment(align_flag() | Qt.AlignmentFlag.AlignVCenter)

        self.age = QLabel("updated --:-- ago")
        self.age.setStyleSheet(f"color:{rgba_white(170)}; font:{FS_SUB}px 'Segoe UI'; background:transparent;")
        self.age.setAlignment(Qt.AlignmentFlag.AlignVCenter | align_flag())

        self.btnRefresh = QLabel(); self.btnRefresh.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        try:
            px = QPixmap(REFRESH_ICON)
            if not px.isNull():
                self.btnRefresh.setPixmap(px.scaled(QSize(12,12),
                    Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except Exception:
            self.btnRefresh.setText("↻")
            self.btnRefresh.setStyleSheet(f"color:{rgba_white(200)}; font:600 {FS_SUB+2}px 'Segoe UI'; background:transparent;")
        self.btnRefresh.setToolTip("Refresh now")
        self.btnRefresh.mousePressEvent = self._manual_refresh

        if ALIGN.lower() == "right":
            hb.addStretch(1); hb.addWidget(self.age, 0); hb.addWidget(self.btnRefresh, 0); hb.addSpacing(6); hb.addWidget(self.title_label, 0)
        else:
            hb.addWidget(self.title_label, 0); hb.addSpacing(6); hb.addWidget(self.btnRefresh, 0); hb.addWidget(self.age, 0); hb.addStretch(1)
        root.addWidget(header, 0)

        # --- Horizontal scroll area wrapping the columns pane ---
        self.h_scroll = QScrollArea()
        self.h_scroll.setWidgetResizable(False)
        self.h_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.h_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.h_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.h_scroll.setStyleSheet(
            f"QScrollArea {{ background: {HIT_BG}; border: none; }}" + SCROLLBAR_H_STYLE
        )
        self.h_scroll.viewport().setStyleSheet(f"background: {HIT_BG};")
        self.h_scroll.setMouseTracking(True)
        self.h_scroll.viewport().setMouseTracking(True)

        self.pane = ColumnsPane(on_gap_delta_for_index=self._on_gap_delta_for_index)
        self.pane.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.h_scroll.setWidget(self.pane)

        root.addWidget(self.h_scroll, 1)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx_menu)

        # Install app-level event filter to catch ALL mouse events for edge detection
        QApplication.instance().installEventFilter(self)

        # initial fill
        self._build_columns()
        self._update_age_from_mtime()
        self._apply_height_only()

        initial_w = self.restore_width or DEFAULT_APP_WIDTH
        self.resize(initial_w, self.height())

        if self.restore_pos:
            self.move(self.restore_pos[0], self.restore_pos[1])

        # timers
        self.timer_age = QTimer(self); self.timer_age.timeout.connect(self._tick); self.timer_age.start(MTIME_POLL_MS)
        self.timer_auto = QTimer(self); self.timer_auto.timeout.connect(self._run_scraper); self.timer_auto.start(AUTO_SCRAPE_MINUTES * 60 * 1000)
        QTimer.singleShot(50, self._run_scraper)

        hide_from_taskbar_later(self)

    # ---------- build / sizing ----------
    def _build_columns(self):
        self.pane.build(self.sources_order, self.data_by_source, self.gaps_map)
        self._persist_gaps()
        self.pane.update(); self.pane.repaint()

    def _apply_height_only(self):
        if self._in_layout:
            return
        self._in_layout = True
        margins_tb = SCROLL_MARGINS[1] + SCROLL_MARGINS[3]
        h_bar = 12
        total_h = self.title_label.sizeHint().height() + (self.pane.height() or (FS_ROW + 2 + LIST_HEIGHT)) + margins_tb + 6 + h_bar
        total_h = max(160, min(1400, total_h))
        self.setFixedHeight(total_h)
        self._in_layout = False

    def _gap_key_for_index(self, idx):
        if ALIGN.lower() == "right":
            return f"before::{self.pane.titles[idx]}"
        else:
            return f"after::{self.pane.titles[idx]}"

    def _on_gap_delta_for_index(self, col_idx, dx, persist=False):
        n = len(self.pane.cols)
        if ALIGN.lower() == "right":
            gap_idx = col_idx
        else:
            gap_idx = col_idx - 1
        if 0 <= gap_idx < len(self.pane.gaps) and dx != 0:
            self.pane.gaps[gap_idx] = max(COL_GAP_MIN, min(COL_GAP_MAX, self.pane.gaps[gap_idx] + int(dx)))
            key = self._gap_key_for_index(gap_idx if ALIGN.lower() == "right" else gap_idx)
            self.gaps_map[key] = int(self.pane.gaps[gap_idx])
            self.pane._relayout()
        if persist:
            self._persist_gaps()
        self._apply_height_only()

    def _persist_gaps(self):
        save_state({"col_gaps": {k: int(v) for k, v in self.gaps_map.items()}})

    # ---------- age + file watch ----------
    def _update_age_from_mtime(self):
        if CSV_PATH.exists():
            try:
                mtime = int(CSV_PATH.stat().st_mtime)
                self.last_mtime = mtime
                self.age.setText(f"updated {fmt_mmss(int(time.time()) - mtime)} ago")
            except Exception: pass

    def _tick(self):
        mtime = None
        if CSV_PATH.exists():
            try: mtime = int(CSV_PATH.stat().st_mtime)
            except Exception: pass
        if mtime is not None:
            if self.last_mtime is None or mtime != self.last_mtime:
                self.last_mtime = mtime
                self.sources_order, self.data_by_source = read_csv_grouped(CSV_PATH)
                if ALIGN.lower() == "right":
                    for i in range(1, len(self.sources_order)):
                        key = f"before::{self.sources_order[i]}"
                        if key not in self.gaps_map: self.gaps_map[key] = COL_GAP_INIT
                else:
                    for i in range(len(self.sources_order) - 1):
                        key = f"after::{self.sources_order[i]}"
                        if key not in self.gaps_map: self.gaps_map[key] = COL_GAP_INIT
                self._build_columns()
                self._apply_height_only()
            self.age.setText(f"updated {fmt_mmss(int(time.time()) - mtime)} ago")
        else:
            self.age.setText("updated --:-- ago")

    # ---------- scraping ----------
    def _run_scraper(self):
        if not SCRAPER.exists(): return
        if getattr(self, "_scrape_proc", None) and self._scrape_proc.poll() is None: return
        try:
            self._scrape_proc = subprocess.Popen(
                [sys.executable, str(SCRAPER)], cwd=str(ROOT),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if getattr(self, "_scrape_poll", None): self._scrape_poll.stop()
            self._scrape_poll = QTimer(self); self._scrape_poll.timeout.connect(self._poll_scraper_done); self._scrape_poll.start(300)
        except Exception:
            self._scrape_proc = None

    def _poll_scraper_done(self):
        if not getattr(self, "_scrape_proc", None): self._scrape_poll.stop(); return
        if self._scrape_proc.poll() is not None:
            self._scrape_poll.stop(); self._force_reload_from_disk()

    def _force_reload_from_disk(self):
        try:
            if CSV_PATH.exists():
                self.last_mtime = int(CSV_PATH.stat().st_mtime)
                self.sources_order, self.data_by_source = read_csv_grouped(CSV_PATH)
                self._build_columns()
                self._apply_height_only()
                self.age.setText("updated 00:00 ago")
        except Exception: pass

    def _manual_refresh(self, _evt): self._run_scraper()

    # ---------- APP-LEVEL event filter: catches ALL mouse events for edge resize ----------
    def eventFilter(self, obj, ev):
        """
        Installed on QApplication so we intercept mouse events from ANY child widget.
        This guarantees the right-edge resize works no matter what widget the cursor is over.
        """
        if not self.isVisible():
            return super().eventFilter(obj, ev)

        t = ev.type()

        if t == QEvent.Type.MouseMove:
            try:
                gpos = ev.globalPosition().toPoint()
            except Exception:
                return super().eventFilter(obj, ev)

            if self.resizing:
                local = self.mapFromGlobal(gpos)
                g = self.geometry()
                g.setWidth(max(MIN_APP_WIDTH, local.x()))
                self.setGeometry(g); self._persist_size()
                return True

            # Update cursor when hovering near right edge
            if self._is_on_right_edge(gpos):
                self.setCursor(Qt.CursorShape.SplitHCursor)
            elif not self.dragging and not self._drag_pending:
                self.setCursor(Qt.CursorShape.SizeAllCursor)

        elif t == QEvent.Type.MouseButtonPress:
            try:
                if ev.button() != Qt.MouseButton.LeftButton:
                    return super().eventFilter(obj, ev)
                gpos = ev.globalPosition().toPoint()
            except Exception:
                return super().eventFilter(obj, ev)

            if self._is_on_right_edge(gpos):
                self.resizing = True
                return True  # consume so nothing else gets it

        elif t == QEvent.Type.MouseButtonRelease:
            if self.resizing:
                self.resizing = False
                self._persist_size()
                return True

        return super().eventFilter(obj, ev)

    # ---------- context / drag / resize ----------
    def _ctx_menu(self, pos):
        m = QMenu(self)
        m.setStyleSheet(CONTEXT_MENU_STYLE)
        a_close = QAction("Close", self); a_close.triggered.connect(self.close); m.addAction(a_close)
        m.exec(self.mapToGlobal(pos))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            pt = e.position().toPoint()
            if not self.resizing:
                self._drag_pending = True
                self._drag_origin = e.globalPosition().toPoint()
                self.drag_off = pt
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        pt = e.position().toPoint()
        gpt = e.globalPosition().toPoint()

        if self._drag_pending and not self.dragging:
            delta = gpt - self._drag_origin
            if abs(delta.x()) >= self._drag_threshold or abs(delta.y()) >= self._drag_threshold:
                self.dragging = True
                self._drag_pending = False

        if self.dragging:
            self.move(gpt - self.drag_off)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.dragging:
            self._persist_pos()
        self.dragging = False; self.resizing = False
        self._drag_pending = False
        super().mouseReleaseEvent(e)

    def moveEvent(self, _e):
        if self.dragging:
            self._persist_pos()
        super().moveEvent(_e)

    def resizeEvent(self, _e):
        self._persist_size()
        super().resizeEvent(_e)

    def _persist_pos(self):
        tl = self.frameGeometry().topLeft()
        save_state({"x": int(tl.x()), "y": int(tl.y())})

    def _persist_size(self):
        save_state({
            "w": int(self.width()), "h": int(self.height()),
            "col_gaps": {k: int(v) for k, v in self.gaps_map.items()},
        })

# =================== RUN ===================
def main():
    app = QApplication(sys.argv)
    w = TrendingReader()
    if not w.restore_pos:
        scr = app.primaryScreen().availableGeometry()
        w.move(scr.left() + 120, scr.top() + 120)
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()