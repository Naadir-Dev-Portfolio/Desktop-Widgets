# widget_coinstats.py — CoinStats clean embed with safe WebEngine profile,
# correct context menus, bottom-tier stacking, and no app-wide quit.

import sys, time, json
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QPoint, QPointF, QUrl, QTimer, QPropertyAnimation, QEasingCurve,
    QRect, QSize, pyqtSignal
)
from PyQt6.QtGui import (
    QPainterPath, QRegion, QPainter, QColor, QCursor, QMouseEvent, QPen, QAction
)
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QGraphicsOpacityEffect, QMenu

from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage

if __package__:
    from .widget_core import hide_from_taskbar_later
else:
    from widget_core import hide_from_taskbar_later


# ------------------ TUNING ------------------
WIDTH, HEIGHT = 367, 520
SLIDE_GAP_Y   = 0

DOT_DIAM      = 10
DOT_SPACING   = 14
DOT_PAD_X     = 14
DOT_PAD_Y     = 14

HOVER_PAD_X   = 16
HOVER_PAD_Y   = 16

TRIGGER_PAD_Y = 60
TRIGGER_LEFT_X = 24
TRIGGER_GAP_LEFT_DRAG = 2

VIEW_MARGIN_Y = 28

ANIM_OUT_MS   = 340
ANIM_IN_MS    = 100
LOCK_MS       = 500

OPACITY       = 1
DOTS_ALPHA    = 100

SHOW_TRIGGER_DEBUG = False

START_URL = "xxx"

p = Path(__file__).resolve()
STATE_FILE = p.parent / "widget_positions" / f"{p.stem}.json"
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

APP_ID = "clean_embed_widget_dots"

APP_QSS = "QWidget { background: #161616; color:#FFFFFF; }"


# ------------------ PERSISTENCE ------------------
def _load_state():
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_state(d: dict):
    try:
        existing = {}
        if STATE_FILE.exists():
            try:
                existing = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if not isinstance(existing, dict):
                    existing = {}
            except Exception:
                existing = {}
        existing.update(d)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception:
        pass


# ------------------ DOT HANDLE ------------------
class DotHandle(QWidget):
    hovered = pyqtSignal()
    moved   = pyqtSignal(QRect)
    closeRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnBottomHint
        )
        self.setWindowTitle("Coinstats Portfolio")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        self._visual_w = DOT_PAD_X * 2 + DOT_DIAM * 4 + DOT_SPACING * 3
        self._visual_h = DOT_PAD_Y * 2 + DOT_DIAM
        self.setFixedSize(self._visual_w + 2 * HOVER_PAD_X, self._visual_h + 2 * HOVER_PAD_Y)

        self._eff = QGraphicsOpacityEffect(self)
        self._eff.setOpacity(OPACITY)
        self.setGraphicsEffect(self._eff)
        self._fade = None

        self._dragging = False
        self._drag_off = QPoint()

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_ctx)
        hide_from_taskbar_later(self)

    def _visual_rect_local(self) -> QRect:
        return QRect(HOVER_PAD_X, HOVER_PAD_Y, self._visual_w, self._visual_h)

    def _visual_rect_global(self) -> QRect:
        r = self._visual_rect_local()
        tl = self.mapToGlobal(r.topLeft())
        return QRect(tl, r.size())

    def _dot_center_x(self, idx: int) -> int:
        start = self._visual_rect_local().left() + DOT_PAD_X + DOT_DIAM // 2
        return start + idx * (DOT_DIAM + DOT_SPACING)

    def _dot_rect(self, idx: int, pad: int = 0) -> QRect:
        vr = self._visual_rect_local()
        cx = self._dot_center_x(idx)
        cy = vr.top() + vr.height() // 2
        r = DOT_DIAM // 2 + pad
        return QRect(cx - r, cy - r, 2 * r, 2 * r)

    def _trigger_rect_local(self) -> QRect:
        first3 = self._dot_rect(0).united(self._dot_rect(1)).united(self._dot_rect(2))
        drag_left = self._dot_rect(3).left()
        r = QRect(
            first3.left() - TRIGGER_LEFT_X,
            first3.top()  - TRIGGER_PAD_Y,
            (drag_left - TRIGGER_GAP_LEFT_DRAG) - (first3.left() - TRIGGER_LEFT_X),
            first3.height() + 2 * TRIGGER_PAD_Y
        )
        return r.intersected(self.rect())

    def _drag_rect_local(self) -> QRect:
        return self._dot_rect(3, pad=8)

    def fade_to(self, val: float, ms: int):
        if self._fade and self._fade.state() == QPropertyAnimation.State.Running:
            self._fade.stop()
        self._fade = QPropertyAnimation(self._eff, b"opacity", self)
        self._fade.setDuration(ms)
        self._fade.setStartValue(self._eff.opacity())
        self._fade.setEndValue(val)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._fade.start()

    def _maybe_trigger_hover(self, pos_local: QPoint | None = None):
        if self._dragging:
            return
        if pos_local is None:
            pos_local = self.mapFromGlobal(QCursor.pos())
        if self._trigger_rect_local().contains(pos_local):
            self.hovered.emit()

    def enterEvent(self, _):
        self._maybe_trigger_hover()

    def _clamp_by_visual_to_screen(self, new_pos: QPoint) -> QPoint:
        scr = QApplication.screenAt(new_pos) or QApplication.primaryScreen()
        g = scr.geometry()
        vr = self._visual_rect_local()
        left   = new_pos.x() + vr.left()
        right  = new_pos.x() + vr.right()
        top    = new_pos.y() + vr.top()
        bottom = new_pos.y() + vr.bottom()

        dx = 0
        if left < g.left():   dx = g.left() - left
        if right > g.right(): dx = g.right() - right if dx == 0 else dx
        dy = 0
        if top < g.top():     dy = g.top() - top
        if bottom > g.bottom(): dy = g.bottom() - bottom if dy == 0 else dy
        return QPoint(new_pos.x() + dx, new_pos.y() + dy)

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.RightButton:
            self._show_ctx(e.position().toPoint()); return
        if e.button() == Qt.MouseButton.LeftButton and self._drag_rect_local().contains(e.position().toPoint()):
            self._dragging = True
            self._drag_off = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e: QMouseEvent):
        lp = e.position().toPoint()
        self.setCursor(Qt.CursorShape.SizeAllCursor if self._drag_rect_local().contains(lp) else Qt.CursorShape.ArrowCursor)

        if self._dragging and (e.buttons() & Qt.MouseButton.LeftButton):
            raw_pos = e.globalPosition().toPoint() - self._drag_off
            new_pos = self._clamp_by_visual_to_screen(raw_pos)
            self.move(new_pos)
            self.moved.emit(self._visual_rect_global())
        else:
            self._maybe_trigger_hover(lp)

    def mouseReleaseEvent(self, _):
        if self._dragging:
            self._dragging = False
            self.moved.emit(self._visual_rect_global())

    def contextMenuEvent(self, e):
        self._show_ctx(e.position().toPoint())

    def _show_ctx(self, local_pos: QPoint):
        gp = self.mapToGlobal(local_pos)
        m = QMenu(self)
        act_close = QAction("Close", self)
        act_close.triggered.connect(self.closeRequested.emit)
        m.addAction(act_close)
        m.setStyleSheet("""
            QMenu { background-color:#2b2b2b; border:1px solid #3a3a3a; border-radius:10px; padding:6px; color:#f0f0f0; }
            QMenu::item { padding:6px 12px; border-radius:6px; }
            QMenu::item:selected { background:#3a3a3a; }
        """)
        m.exec(gp)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        vr = self._visual_rect_local()
        cy = vr.top() + vr.height() // 2

        c_main = QColor(208, 208, 208, DOTS_ALPHA)
        c_drag = QColor(176, 176, 176, DOTS_ALPHA)

        for i in range(4):
            p.setBrush(c_drag if i == 3 else c_main)
            cx = self._dot_center_x(i)
            p.drawEllipse(QPointF(cx, cy), DOT_DIAM / 2, DOT_DIAM / 2)

        if SHOW_TRIGGER_DEBUG:
            p.setBrush(QColor(255, 0, 0, 40))
            p.setPen(QPen(QColor(255, 0, 0, 120), 1))
            p.drawRect(self._trigger_rect_local())


# ------------------ CLEAN EMBED (WEB) ------------------
class CleanEmbedWidget(QWidget):
    closed = pyqtSignal()

    def __init__(self, url: str, parent=None):
        super().__init__(
            parent if parent is not None else None,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnBottomHint |
            Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.resize(WIDTH, HEIGHT)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.profile = QWebEngineProfile(self)
        if hasattr(self.profile, "setOffTheRecord"):
            self.profile.setOffTheRecord(True)  # type: ignore[attr-defined]
        else:
            try: self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
            except Exception: pass
            try: self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
            except Exception: pass
            try: self.profile.setPersistentStoragePath("")
            except Exception: pass
            try: self.profile.setCachePath("")
            except Exception: pass

        try:
            self.profile.downloadRequested.connect(lambda it: it.cancel())
        except Exception:
            pass

        self.page = QWebEnginePage(self.profile, self)

        self.view = QWebEngineView()
        self.view.setPage(self.page)

        self._view_opacity = QGraphicsOpacityEffect(self.view)
        self._view_opacity.setOpacity(1.0)
        self.view.setGraphicsEffect(self._view_opacity)

        lay.addWidget(self.view)

        self.view.loadFinished.connect(lambda ok: self._inject_cleanup())
        self.view.urlChanged.connect(lambda _u: self._inject_cleanup())
        self.view.load(QUrl(url))

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_ctx_here)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_ctx_on_view)
        hide_from_taskbar_later(self)

    def _show_ctx_here(self, local_pos: QPoint):
        self._build_menu().exec(self.mapToGlobal(local_pos))

    def _show_ctx_on_view(self, local_pos: QPoint):
        self._build_menu().exec(self.view.mapToGlobal(local_pos))

    def _build_menu(self) -> QMenu:
        m = QMenu(self)
        act_close = QAction("Close", self)
        act_close.triggered.connect(self._request_close_only_self)
        m.addAction(act_close)
        m.setStyleSheet("""
            QMenu { background-color:#2b2b2b; border:1px solid #3a3a3a; border-radius:10px; padding:6px; color:#f0f0f0; }
            QMenu::item { padding:6px 12px; border-radius:6px; }
            QMenu::item:selected { background:#3a3a3a; }
        """)
        return m

    def _request_close_only_self(self):
        self.closed.emit()

    def _apply_round_mask(self):
        r_tl, r_tr, r_br, r_bl = 8.0, 8.0, 18.0, 18.0
        w, h = float(self.width()), float(self.height())
        r_tl = min(r_tl, min(w, h) / 2)
        r_tr = min(r_tr, min(w, h) / 2)
        r_br = min(r_br, min(w, h) / 2)
        r_bl = min(r_bl, min(w, h) / 2)

        path = QPainterPath()
        x, y = 0.0, 0.0
        path.moveTo(x + r_tl, y)
        path.lineTo(x + w - r_tr, y)
        path.quadTo(x + w, y, x + w, y + r_tr)
        path.lineTo(x + w, y + h - r_br)
        path.quadTo(x + w, y + h, x + w - r_br, y + h)
        path.lineTo(x + r_bl, y + h)
        path.quadTo(x, y + h, x, y + h - r_bl)
        path.lineTo(x, y + r_tl)
        path.quadTo(x, y, x + r_tl, y)
        path.closeSubpath()
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_round_mask()

    def _inject_cleanup(self):
            CLEANUP_JS = r"""
            (() => {
            const BG="#2A2A2A";
            const injectCSS=()=>{if(document.getElementById("__custom_scroll_css"))return;
                const style=document.createElement("style");
                style.id="__custom_scroll_css";
                style.textContent=
                `::-webkit-scrollbar{width:12px;height:12px;background:rgba(60,60,60,0.95);}
                ::-webkit-scrollbar-thumb{background:rgba(40,40,40,0.95);border-radius:8px;}
                ::-webkit-scrollbar-corner{background:rgba(60,60,60,0.95);}
                html,body{color:#fff;}
                :root,html,body,#__next,#__next>main{background:${BG}!important;background-color:${BG}!important;}`;
                document.head.appendChild(style);};
            const removeAppPopup=()=>{
                document.querySelector('.MobileSwitchPopup_mobileSwitchWrapper__Vanrl')?.remove();
            };
            const run=()=>{injectCSS();removeAppPopup();};
            setTimeout(run,0);setTimeout(run,800);
            if(!window.__cleanupObserver){try{
                const obs=new MutationObserver(()=>run());
                obs.observe(document.documentElement,{childList:true,subtree:true});
                window.__cleanupObserver=obs;}catch{}}
            })();
            """
            try:
                self.view.page().runJavaScript(CLEANUP_JS)
                self.view.page().runJavaScript(f"setTimeout(()=>{{ {CLEANUP_JS} }}, 800);")
            except Exception:
                pass

    def fade_view_to(self, opacity: float, duration: int):
        if hasattr(self, '_view_fade') and self._view_fade.state() == QPropertyAnimation.State.Running:
            self._view_fade.stop()
        self._view_fade = QPropertyAnimation(self._view_opacity, b"opacity", self)
        self._view_fade.setDuration(duration)
        self._view_fade.setStartValue(self._view_opacity.opacity())
        self._view_fade.setEndValue(opacity)
        self._view_fade.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._view_fade.start()

    def closeEvent(self, e):
        try: self.view.loadFinished.disconnect()
        except Exception: pass
        try: self.view.urlChanged.disconnect()
        except Exception: pass
        super().closeEvent(e)


# ------------------ CONTROLLER ------------------
class DrawerController(QWidget):
    """
    Pass `stack_over=<your_ticker_widget>` when you want the drawer to always
    float above the ticker while both stay behind other apps.
    """
    def __init__(self, url: str, stack_over: QWidget | None = None):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

        # dots: remain on desktop layer
        self.dots = DotHandle(self)

        # drawer: owned by `stack_over` if provided -> guaranteed above it
        parent_for_drawer = stack_over if stack_over is not None else self
        self.drawer = CleanEmbedWidget(url, parent_for_drawer)

        self.anim = QPropertyAnimation(self.drawer, b"size", self)

        self._expanded = False
        self._anchor_visual = self.dots._visual_rect_global()
        self._lock_until = 0.0
        self._target_size = QSize(WIDTH, HEIGHT)

        self.dots.hovered.connect(self.expand)
        self.dots.moved.connect(self._on_dots_moved)
        self.dots.moved.connect(self._save_position_from_visual)
        self.dots.closeRequested.connect(self._teardown)
        self.drawer.closed.connect(self._teardown)

        self.dots.show()
        self.drawer.hide()

        self._restore_position()

        self._watch = QTimer(self)
        self._watch.setInterval(50)
        self._watch.timeout.connect(self._watch_mouse)
        self._watch.start()

        self.drawer.leaveEvent = self._view_leave
        self.drawer.view.leaveEvent = self._view_leave
        self.anim.finished.connect(self._set_lock_after_expand)

    def _set_drawer_topmost(self, on: bool):
        # switch between topmost and bottom-tier without stealing focus
        self.drawer.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.drawer.setWindowFlag(Qt.WindowType.WindowStaysOnBottomHint, not on)

    # Optional forwarding so hide()/show() always works
    def hideEvent(self, e):
        try: self.drawer.hide()
        except Exception: pass
        try: self.dots.hide()
        except Exception: pass
        e.accept()

    def showEvent(self, e):
        try: self.dots.show()
        except Exception: pass
        if self._expanded:
            try: self.drawer.show()
            except Exception: pass
        e.accept()

    def _screen_geom(self) -> QRect:
        scr = QApplication.screenAt(self.dots.frameGeometry().center()) or QApplication.primaryScreen()
        return scr.geometry()

    def _on_dots_moved(self, visual_global: QRect):
        self._anchor_visual = visual_global
        if not self._expanded:
            a = visual_global
            collapsed_pos = QPoint(
                a.center().x() - self.drawer.width() // 2,
                a.top() + DOT_PAD_Y - SLIDE_GAP_Y
            )
            self.drawer.move(collapsed_pos)
            self.drawer.resize(self._collapsed_size())

    def _collapsed_size(self) -> QSize:
        return QSize(self._target_size.width(), 0)

    def _widened_view_rect(self) -> QRect:
        r = self.drawer.frameGeometry()
        return r.adjusted(0, -VIEW_MARGIN_Y, 0, VIEW_MARGIN_Y)

    # REPLACE your expand() with this
    def expand(self):
        if self._expanded or self.anim.state() == QPropertyAnimation.State.Running:
            return
        self._expanded = True
        self._lock_until = 0.0

        self.dots.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.dots.fade_to(0.0, 120)

        a = self._anchor_visual
        fixed_bottom_y = a.top() + DOT_PAD_Y - SLIDE_GAP_Y
        x_pos = a.center().x() - self.drawer.width() // 2

        start_pos = QPoint(x_pos, fixed_bottom_y)
        end_pos   = QPoint(x_pos, fixed_bottom_y - self._target_size.height())

        g = self._screen_geom()
        end_pos_clamped = QPoint(
            max(g.left(), min(x_pos, g.right() - self.drawer.width() + 1)),
            max(g.top(),  min(end_pos.y(), g.bottom() - self.drawer.height() + 1))
        )

        self.drawer.move(start_pos)
        self.drawer.resize(self._collapsed_size())

        # ← make the WebEngine drawer temporarily topmost while expanded
        self._set_drawer_topmost(True)

        self.drawer.show()
        self.drawer.raise_()

        self.anim.stop()
        self.anim.setDuration(ANIM_OUT_MS)
        self.anim.setEasingCurve(QEasingCurve.Type.OutQuint)

        self.pos_anim = QPropertyAnimation(self.drawer, b"pos", self)
        self.pos_anim.setDuration(ANIM_OUT_MS)
        self.pos_anim.setEasingCurve(QEasingCurve.Type.OutQuint)
        self.pos_anim.setStartValue(start_pos)
        self.pos_anim.setEndValue(end_pos_clamped)

        self.anim.setStartValue(self._collapsed_size())
        self.anim.setEndValue(self._target_size)
        self.anim.start()
        self.pos_anim.start()

        self.drawer.fade_view_to(0.0, 1)
        QTimer.singleShot(ANIM_OUT_MS // 3, lambda: self.drawer.fade_view_to(1.0, ANIM_OUT_MS // 2))


    def _set_lock_after_expand(self):
        if self._expanded:
            self._lock_until = time.monotonic() + LOCK_MS / 1000.0

    def collapse(self):
        if not self._expanded:
            return
        self._expanded = False
        self.dots.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.dots.fade_to(OPACITY, 120)

        a = self._anchor_visual
        fixed_bottom_y = a.top() + DOT_PAD_Y - SLIDE_GAP_Y
        x_pos = a.center().x() - self.drawer.width() // 2
        end_pos = QPoint(x_pos, fixed_bottom_y)

        self.anim.stop()
        if hasattr(self, 'pos_anim'):
            self.pos_anim.stop()

        self.anim.setDuration(ANIM_IN_MS)
        self.anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self.anim.setStartValue(self.drawer.size())
        self.anim.setEndValue(self._collapsed_size())

        self.pos_anim = QPropertyAnimation(self.drawer, b"pos", self)
        self.pos_anim.setDuration(ANIM_IN_MS)
        self.pos_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self.pos_anim.setStartValue(self.drawer.pos())
        self.pos_anim.setEndValue(end_pos)

        self.drawer.fade_view_to(0.0, ANIM_IN_MS // 2)

        self.anim.start()
        self.pos_anim.start()

        def _finish():
            # back to bottom-tier after hiding
            self.drawer.hide()
            self._set_drawer_topmost(False)

        QTimer.singleShot(ANIM_IN_MS, _finish)

    def _watch_mouse(self):
        if not self._expanded:
            return
        if time.monotonic() < self._lock_until:
            return
        if self.anim.state() == QPropertyAnimation.State.Running:
            return
        if not self._widened_view_rect().contains(QCursor.pos()):
            self.collapse()

    def _view_leave(self, e):
        self._watch_mouse()
        e.accept()

    def _restore_position(self):
        data = _load_state()
        pos = data.get(APP_ID)
        if isinstance(pos, dict) and "x" in pos and "y" in pos:
            saved = QPoint(int(pos["x"]), int(pos["y"]))
            clamped = self.dots._clamp_by_visual_to_screen(saved)
            self.dots.move(clamped)
        else:
            g = self._screen_geom()
            self.dots.move(g.center().x() - self.dots.width() // 2, g.center().y() - self.dots.height() // 2)
        self._on_dots_moved(self.dots._visual_rect_global())
        self._save_position_from_visual(self.dots._visual_rect_global())

    def _save_position_from_visual(self, visual_global: QRect):
        win_tl = QPoint(visual_global.left() - HOVER_PAD_X, visual_global.top() - HOVER_PAD_Y)
        _save_state({APP_ID: {"x": int(win_tl.x()), "y": int(win_tl.y())}})

    def _teardown(self):
        try: self._watch.stop()
        except Exception: pass
        try:
            if self._expanded:
                self.collapse()
        except Exception: pass
        try: self.drawer.close()
        except Exception: pass
        try: self.dots.close()
        except Exception: pass


# --------------- entry (standalone) ----------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)
    # Standalone: no anchor
    ctrl = DrawerController(START_URL)
    sys.exit(app.exec())
