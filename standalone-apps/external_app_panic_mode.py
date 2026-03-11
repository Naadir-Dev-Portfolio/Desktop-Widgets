# Standalone_panic_mode.py
# Fixed: reliable position memory + centered circular close button + tasks wiring.

import sys, os, json, random, platform, ctypes
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer, QPoint, QUrl, QEvent
from PyQt6.QtGui import QFont, QAction, QColor
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QProgressBar, QTabWidget, QComboBox, QMenu,
    QFrame, QScrollArea, QGraphicsDropShadowEffect
)
from PyQt6.QtWebEngineWidgets import QWebEngineView

if __package__:
    from .widget_core import hide_from_taskbar_later
else:
    from widget_core import hide_from_taskbar_later

# ---------- Config ----------
OPACITY = 180
RADIUS_TL = 20; RADIUS_TR = 20; RADIUS_BL = 20; RADIUS_BR = 6
START_SIZE = (1000, 700)
STATE_FILE = os.path.join(os.path.expanduser("~"), "operation_steadfast_state.json")

SCROLLBAR_STYLE = """
QScrollBar:vertical { border:none; background:transparent; width:10px; margin:0; }
QScrollBar::handle:vertical { background:#555; min-height:20px; border-radius:5px; }
QScrollBar::handle:vertical:hover { background:#777; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:none; }

QScrollBar:horizontal { border:none; background:transparent; height:10px; margin:0; }
QScrollBar::handle:horizontal { background:#555; min-width:20px; border-radius:5px; }
QScrollBar::handle:horizontal:hover { background:#777; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:none; }
"""

def build_theme_qss():
    return f"""
#Root {{ background: transparent; }}

/* Rounded container */
#TopContainer {{
    border: none;
    border-top-left-radius: {RADIUS_TL}px;
    border-top-right-radius: {RADIUS_TR}px;
    border-bottom-left-radius: {RADIUS_BL}px;
    border-bottom-right-radius: {RADIUS_BR}px;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #252525, stop:1 #2e2e2e);
}}

QFrame#Card {{
    background: rgba(0,0,0,0.08);
    border: 1px solid #2f2f2f;
    border-radius: 14px;
}}
QFrame#Card:hover {{ border-color:#3a3a3a; }}

/* Tabs */
QTabWidget {{ background: transparent; }}
QTabWidget::pane {{ background: transparent; border: none; margin-top: 0; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #2f2f2f, stop:1 #232323);
    color: #f0f0f0;
    padding: 8px 14px;
    border: 1px solid #2f2f2f;
    border-bottom: none;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    margin: 0 4px;
    min-width: 120px;
}}
QTabBar::tab:selected {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #3a3a3a, stop:1 #2b2b2b);
    color: #ffffff;
    font-weight: 600;
    border: 1px solid #3a3a3a;
    border-bottom: none;
}}
QTabBar::tab:hover {{ background:#383838; }}

/* Labels default */
#TopContainer QLabel {{ color:#f0f0f0; background: transparent; }}

/* Buttons (general) */
#TopContainer QPushButton {{
    color:#FFFFFF;
    font-size: 14px;
    font-weight: 500;
    border: none;
    border-radius: 8px;
    padding: 8px 12px;
    text-align: left;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 #343434,
                                stop:0.5 #262626,
                                stop:1 #1A1A1A);
}}
#TopContainer QPushButton:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 #424242,
                                stop:0.5 #323232,
                                stop:1 #232323);
}}
#TopContainer QPushButton:pressed {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 #272727,
                                stop:0.5 #1B1B1B,
                                stop:1 #101010);
}}
#TopContainer QPushButton:disabled {{ background:#3a3a3a; color:#8a8a8a; }}

/* Inputs */
QComboBox, QLineEdit {{
    background-color:#2b2b2b;
    border:1px solid #444;
    border-radius:8px;
    padding:6px 10px;
    color:#f0f0f0;
}}
QComboBox::drop-down {{ border-left:1px solid #3a3a3a; width:18px; }}
QComboBox QAbstractItemView {{
    background:#2f2f2f; color:#f0f0f0; selection-background-color:#444;
    border:1px solid #3a3a3a; border-radius:8px;
}}

/* Progress */
QProgressBar {{
    background: #1f1f1f;
    border: 1px solid #2f2f2f;
    border-radius: 10px;
    height: 26px;
    color:#e6e6e6;
    text-align: center;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #5e5e5e, stop:1 #818181);
    border-radius: 10px;
}}

/* Context menu */
QMenu {{
    background-color: #2b2b2b;
    border: 1px solid #3a3a3a;
    border-radius: 10px;
    padding: 6px;
    color: #f0f0f0;
}}
QMenu::item {{ padding: 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background-color: #3a3a3a; }}
QMenu::separator {{ height:1px; background:#3a3a3a; margin:6px 4px; }}

/* Close button overrides */
QPushButton#CloseButton {{
    font: 600 18px 'Segoe UI';
    color: #dddddd;
    border: none;
    padding: 0px;
    min-width: 36px; min-height: 36px;
    max-width: 36px; max-height: 36px;
    border-radius: 18px;         /* perfect circle */
    text-align: center;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 #343434,
                                stop:1 #1A1A1A);
}}
QPushButton#CloseButton:hover {{
    color: #ffffff;
    background: #2a1b1b;
    border: 1px solid #3b2222;
}}
QPushButton#CloseButton:pressed {{
    background: #231414;
}}
"""

# ---------- Position store ----------
class PositionStore:
    def __init__(self, app_id: str):
        self.app_id = app_id
        self.path = Path(__file__).resolve().parent / "widget_positions.json"

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            v = data.get(self.app_id)
            if isinstance(v, dict) and "x" in v and "y" in v:
                return int(v["x"]), int(v["y"])
        except Exception:
            pass
        return None

    def save(self, x: int, y: int):
        try:
            data = {}
            if self.path.exists():
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        data = {}
                except Exception:
                    data = {}
            data[self.app_id] = {"x": int(x), "y": int(y)}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

# ---------- Data Models ----------
class BreathingTechnique:
    def __init__(self, name, instructions):
        self.name = name
        self.instructions = instructions  # list[(text, seconds)]

# ---------- Main Window ----------
class MainWindow(QWidget):
    APP_ID = "OperationSteadfast"

    def __init__(self):
        super().__init__()
        self.setObjectName("Root")
        self.setWindowTitle("Operation Steadfast")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnBottomHint |
            Qt.WindowType.Window
        )

        self.setWindowOpacity(OPACITY / 255.0)
        self.drag_pos: QPoint | None = None

        self.setFixedSize(*START_SIZE)

        self.pos_store = PositionStore(self.APP_ID)
        self._save_debounce = QTimer(self); self._save_debounce.setInterval(250)
        self._save_debounce.setSingleShot(True); self._save_debounce.timeout.connect(self._save_position_now)

        self.state = self._load_state()

        self._init_breathing()
        self._init_text_blocks()
        self.games = {}

        self.container = QFrame(self); self.container.setObjectName("TopContainer")
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.addWidget(self.container)

        self._build_ui()
        self.setStyleSheet(build_theme_qss())
        self._apply_scrollbars()
        self._restore_geometry()
        hide_from_taskbar_later(self)

    # ----- UI build -----
    def _build_ui(self):
        root = QVBoxLayout(self.container)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        title_card = QFrame(self.container); title_card.setObjectName("Card")
        tlay = QHBoxLayout(title_card); tlay.setContentsMargins(10, 8, 10, 8)

        title = QLabel("Operation Steadfast")
        f = QFont("Segoe UI", 18); f.setWeight(QFont.Weight.DemiBold)
        title.setFont(f)
        tlay.addWidget(title)
        tlay.addStretch(1)

        self.btn_close = QPushButton("×")
        self.btn_close.setObjectName("CloseButton")
        self.btn_close.setFixedSize(36, 36)
        self.btn_close.clicked.connect(self.close)
        self.btn_close.installEventFilter(self)
        tlay.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        root.addWidget(title_card)

        tabs_card = QFrame(self.container); tabs_card.setObjectName("Card")
        tabs_layout = QVBoxLayout(tabs_card); tabs_layout.setContentsMargins(10, 10, 10, 10)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.currentChanged.connect(self._save_state)

        # Motivation
        self.tab_mot = QWidget()
        mot_lay = QVBoxLayout(self.tab_mot); mot_lay.setContentsMargins(20, 20, 20, 20); mot_lay.setSpacing(18)
        self.encouragement_label = QLabel(""); self.encouragement_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.encouragement_label.setWordWrap(True); self.encouragement_label.setStyleSheet("font: 700 32px 'Segoe UI';")
        mot_lay.addStretch(1); mot_lay.addWidget(self.encouragement_label); mot_lay.addStretch(1)
        mot_btns = QHBoxLayout()
        self.btn_enc = QPushButton("Show Encouragement"); self.btn_enc.clicked.connect(self._show_encouragement)
        self.btn_cons = QPushButton("Show Consequences");  self.btn_cons.clicked.connect(self._show_consequence)
        mot_btns.addWidget(self.btn_enc); mot_btns.addWidget(self.btn_cons); mot_lay.addLayout(mot_btns)

        # Breathing
        self.tab_breath = QWidget()
        br_lay = QVBoxLayout(self.tab_breath); br_lay.setContentsMargins(20, 20, 20, 20); br_lay.setSpacing(16)
        row = QHBoxLayout()
        lbl = QLabel("Select Breathing Technique:")
        self.cbo = QComboBox(); [self.cbo.addItem(t.name) for t in self.breathing_techniques]
        self.cbo.currentIndexChanged.connect(self._change_breath)
        row.addWidget(lbl); row.addWidget(self.cbo); br_lay.addLayout(row)
        self.step_label = QLabel(""); self.step_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.step_label.setStyleSheet("font: 700 22px 'Segoe UI';")
        br_lay.addWidget(self.step_label)
        self.pb = QProgressBar(); self.pb.setTextVisible(True); self.pb.setFormat(""); br_lay.addWidget(self.pb)
        self.btn_breath = QPushButton("Start Breathing"); self.btn_breath.clicked.connect(self._toggle_breath)
        br_lay.addWidget(self.btn_breath)

        # Games
        self.tab_games = QWidget()
        g_lay = QVBoxLayout(self.tab_games); g_lay.setContentsMargins(20,20,20,20); g_lay.setSpacing(10)
        g_row = QHBoxLayout(); g_row.addWidget(QLabel("Select Relaxing Game:"))
        self.cbo_games = QComboBox(); self.cbo_games.currentIndexChanged.connect(self._change_game)
        g_row.addWidget(self.cbo_games); g_lay.addLayout(g_row)
        self.web = QWebEngineView(); g_lay.addWidget(self.web)

        # Tasks
        self.tab_tasks = QWidget()
        tk_lay = QVBoxLayout(self.tab_tasks); tk_lay.setContentsMargins(20,20,20,20); tk_lay.setSpacing(16)
        title_task = QLabel("Your Task:"); title_task.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_task.setStyleSheet("font: 700 28px 'Segoe UI';")
        tk_lay.addWidget(title_task)
        self.current_task = QLabel(""); self.current_task.setWordWrap(True)
        self.current_task.setAlignment(Qt.AlignmentFlag.AlignCenter); self.current_task.setStyleSheet("font: 700 22px 'Segoe UI';")
        tk_lay.addStretch(1); tk_lay.addWidget(self.current_task); tk_lay.addStretch(1)
        row_btn = QHBoxLayout()
        self.btn_get = QPushButton("Get a Task"); self.btn_get.clicked.connect(self._random_task)
        self.btn_done = QPushButton("Task Completed"); self.btn_done.setEnabled(False); self.btn_done.clicked.connect(self._complete_task)
        row_btn.addWidget(self.btn_get); row_btn.addWidget(self.btn_done); tk_lay.addLayout(row_btn)

        self.tabs.addTab(self.tab_mot, "Motivation")
        self.tabs.addTab(self.tab_breath, "Breathing")
        self.tabs.addTab(self.tab_games, "Relaxing Games")
        self.tabs.addTab(self.tab_tasks, "Tasks")

        tabs_layout.addWidget(self.tabs)
        root.addWidget(tabs_card)

        self.timer_breath = QTimer(self); self.timer_breath.timeout.connect(self._advance_breath)
        self.timer_count = QTimer(self); self.timer_count.timeout.connect(self._countdown)

        self._load_games()

    # ----- Hover glow for X -----
    def eventFilter(self, obj, ev):
        if obj is self.btn_close:
            if ev.type() == QEvent.Type.Enter:
                eff = QGraphicsDropShadowEffect(self.btn_close)
                eff.setBlurRadius(18); eff.setXOffset(0); eff.setYOffset(0)
                eff.setColor(QColor(150, 30, 30, 160))
                self.btn_close.setGraphicsEffect(eff)
            elif ev.type() == QEvent.Type.Leave:
                self.btn_close.setGraphicsEffect(None)
        return super().eventFilter(obj, ev)

    # ----- Scrollbars -----
    def _apply_scrollbars(self):
        for w in self.findChildren(QScrollArea):
            w.setStyleSheet("QScrollArea{background:transparent;border:none;}" + SCROLLBAR_STYLE)
            if w.verticalScrollBar(): w.verticalScrollBar().setStyleSheet(SCROLLBAR_STYLE)
            if w.horizontalScrollBar(): w.horizontalScrollBar().setStyleSheet(SCROLLBAR_STYLE)

    # ----- Data init -----
    def _init_breathing(self):
        self.breathing_techniques = [
            BreathingTechnique("4-7-8 Technique", [("Inhale deeply",4),("Hold your breath",7),("Exhale slowly",8)]),
            BreathingTechnique("Box Breathing", [("Inhale",4),("Hold",4),("Exhale",4),("Hold",4)]),
            BreathingTechnique("5-5-5 Technique", [("Inhale deeply",5),("Hold your breath",5),("Exhale slowly",5)]),
            BreathingTechnique("Diaphragmatic Breathing", [("Inhale through nose",3),("Hold breath",2),("Exhale through mouth",4)]),
            BreathingTechnique("Pursed-Lip Breathing", [("Inhale slowly through nose",2),("Exhale through pursed lips",4)]),
        ]
        self.breath_idx = 0; self.breath_step = 0; self.remaining = 0

    def _init_text_blocks(self):
        self.encouragements = [
            "You are stronger than this moment. Keep going!",
            "Every step forward counts, no matter how small.",
            "Breathe deeply. This urge will pass.",
            "Progress, not perfection.",
            "Your effort today builds a better tomorrow.",
            "Discipline is the bridge between goals and accomplishment.",
        ]
        self.consequences = [
            "If you give in, stress and anxiety increase.",
            "Giving in undermines your confidence and momentum.",
            "Short-term comfort, long-term regret—stay the course.",
        ]
        self.cons_idx = 0
        self.tasks = [
            "Organize a folder on your computer.",
            "Write down 3 things you're grateful for.",
            "Clean your workspace.",
            "Meditate for 5 minutes.",
            "Plan your schedule for the week.",
            "Read a few pages of a book.",
        ]

    # ----- Games -----
    def _games_dir(self):
        return os.path.join(os.path.dirname(__file__), "html", "games")

    def _load_games(self):
        self.games.clear()
        d = self._games_dir()
        if os.path.exists(d):
            for f in os.listdir(d):
                if f.lower().endswith(".html"):
                    name = os.path.splitext(f)[0].replace("_"," ").title()
                    self.games[name] = os.path.join(d, f)
        self.cbo_games.blockSignals(True); self.cbo_games.clear()
        self.cbo_games.addItems(list(self.games.keys()))
        self.cbo_games.blockSignals(False)
        gi = min(max(0, self.state.get("game_index", 0)), max(0, self.cbo_games.count()-1))
        self.cbo_games.setCurrentIndex(gi); self._change_game(gi)

    def _change_game(self, idx):
        self.state["game_index"] = idx; self._save_state()
        keys = list(self.games.keys())
        if 0 <= idx < len(keys):
            self.web.setUrl(QUrl.fromLocalFile(self.games[keys[idx]]))
        else:
            self.web.setHtml("<h1 style='color:#e6e6e6;font-family:Segoe UI'>No Games Available</h1>")

    # ----- Motivation -----
    def _show_encouragement(self):
        self.encouragement_label.setText(random.choice(self.encouragements))

    def _show_consequence(self):
        self.encouragement_label.setText(self.consequences[self.cons_idx])
        self.cons_idx = (self.cons_idx + 1) % len(self.consequences)

    # ----- Breathing -----
    def _change_breath(self, idx):
        self.breath_idx = idx
        if self.timer_breath.isActive() or self.timer_count.isActive():
            self._stop_breath()

    def _toggle_breath(self):
        if self.timer_breath.isActive() or self.timer_count.isActive():
            self._stop_breath()
        else:
            self._start_breath()

    def _start_breath(self):
        self.breath_step = 0
        self.btn_breath.setText("Stop Breathing")
        self.timer_breath.start(0)

    def _stop_breath(self):
        self.timer_breath.stop(); self.timer_count.stop()
        self.btn_breath.setText("Start Breathing")
        self.step_label.setText(""); self.pb.setValue(0); self.pb.setFormat("")

    def _advance_breath(self):
        t = self.breathing_techniques[self.breath_idx]
        if self.breath_step >= len(t.instructions): self.breath_step = 0
        txt, secs = t.instructions[self.breath_step]
        self.step_label.setText(txt)
        self.pb.setMaximum(secs); self.pb.setValue(0); self.pb.setFormat(f"{txt} - {secs}s")
        self.remaining = secs
        self.timer_breath.stop(); self.timer_count.start(1000)

    def _countdown(self):
        self.remaining -= 1
        if self.remaining >= 0:
            elapsed = self.pb.maximum() - self.remaining
            self.pb.setValue(elapsed)
            txt = self.breathing_techniques[self.breath_idx].instructions[self.breath_step][0]
            self.pb.setFormat(f"{txt} - {self.remaining}s")
        else:
            self.timer_count.stop(); self.breath_step += 1; self.timer_breath.start(0)

    # ----- Tasks -----
    def _random_task(self):
        self.current_task.setText(random.choice(self.tasks))
        self.btn_get.setEnabled(False)
        self.btn_done.setEnabled(True)

    def _complete_task(self):
        self.current_task.setText("Well done!")
        self.btn_done.setEnabled(False)
        self.btn_get.setEnabled(True)

    # ----- Persistence (indices only) -----
    def _load_state(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_state(self):
        try:
            self.state["tab_index"] = getattr(self, "tabs", None).currentIndex() if hasattr(self, "tabs") else 0
            self.state["breath_index"] = getattr(self, "cbo", None).currentIndex() if hasattr(self, "cbo") else 0
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception:
            pass

    # ----- Position restore/save -----
    def _restore_geometry(self):
        saved = self.pos_store.load()
        if not saved:
            legacy = self.state.get("pos")
            if isinstance(legacy, list) and len(legacy) == 2:
                saved = (int(legacy[0]), int(legacy[1]))
        if saved:
            self.move(*saved)
        else:
            scr = QApplication.primaryScreen().availableGeometry()
            self.move(scr.center().x() - START_SIZE[0]//2, scr.center().y() - START_SIZE[1]//2)

        if "tab_index" in self.state: self.tabs.setCurrentIndex(self.state["tab_index"])
        if "breath_index" in self.state: self.cbo.setCurrentIndex(self.state["breath_index"])

    def _request_save_pos(self):
        self._save_debounce.start()

    def _save_position_now(self):
        tl = self.frameGeometry().topLeft()
        self.pos_store.save(tl.x(), tl.y())

    # ----- Drag / Context -----
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()
        elif e.button() == Qt.MouseButton.RightButton:
            self._show_ctx(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self.drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self.drag_pos)
            self._request_save_pos()
            e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = None
            self._request_save_pos()

    def moveEvent(self, _e):
        self._request_save_pos()

    def _show_ctx(self, global_pos):
        m = QMenu(self)
        act_close = QAction("Close", self); act_close.triggered.connect(self.close)
        m.addAction(act_close)
        m.setStyleSheet("""
            QMenu { background-color:#2b2b2b; border:1px solid #3a3a3a; border-radius:10px; padding:6px; color:#f0f0f0; }
            QMenu::item { padding:6px 12px; border-radius:6px; }
            QMenu::item:selected { background:#3a3a3a; }
        """)
        m.exec(global_pos)

    def contextMenuEvent(self, _): pass

    def showEvent(self, e):
        super().showEvent(e)
        if platform.system().lower().startswith("win"):
            try:
                hwnd = int(self.winId())
                SWP_NOSIZE=0x0001; SWP_NOMOVE=0x0002; SWP_NOACTIVATE=0x0010; SWP_NOSENDCHANGING=0x0400
                HWND_BOTTOM = 1
                ctypes.windll.user32.SetWindowPos(hwnd, HWND_BOTTOM, 0,0,0,0, SWP_NOSIZE|SWP_NOMOVE|SWP_NOACTIVATE|SWP_NOSENDCHANGING)
            except Exception:
                pass

    def closeEvent(self, e):
        self.timer_breath.stop(); self.timer_count.stop()
        self._save_state()
        self._save_position_now()
        e.accept()

# ---------- Entry ----------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
