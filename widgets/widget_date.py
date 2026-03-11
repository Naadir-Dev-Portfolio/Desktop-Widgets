import sys
import json
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QSizePolicy, QMenu
)
from PyQt6.QtGui import QFont, QAction, QMoveEvent
from PyQt6.QtCore import Qt, QTimer, QDate, QPoint, QRect, QEvent

if __package__:
    from .widget_core import hide_from_taskbar_later
else:
    from widget_core import hide_from_taskbar_later


class PositionStore:
    def __init__(self, app_id: str):
        p = Path(__file__).resolve()
        self.path = p.parent / "widget_positions" / f"{p.stem}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.app_id = app_id

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

class DateWidget(QWidget):
    TEXT_TRANSPARENCY = 100
    RIGHT_OFFSET_PX = 24
    APP_ID = "DateWidget"

    def __init__(self, sidebar_position):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnBottomHint |
            Qt.WindowType.Window
        )
        
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Long Date")
        self.sidebar_position = sidebar_position

        self.pos_store = PositionStore(self.APP_ID)

        # --- Position Locking System ---
        self._locked_pos = None       # The last known-good position (QPoint)
        self._is_dragging = False     # True only while the user is actively dragging
        self._drag_occurred = False   # True if mouse actually moved during a drag
        self._drag_offset = None      # Offset from mouse cursor to window top-left (QPoint)
        self._screen_change_connected = False  # Guard for one-time screenChanged connection
        self._drag_grace_period = False  # Brief grace period after drag ends

        # anchoring: True = keep right-edge aligned; False = respect user/saved position
        self._anchored = True

        self.setStyleSheet("""
            QMenu {
                background-color: #2b2b2b;
                border: 1px solid #3a3a3a;
                border-radius: 10px;
                padding: 6px;
                color: #f0f0f0;
            }
            QMenu::item { padding: 6px 12px; border-radius: 6px; background: transparent; }
            QMenu::item:selected { background-color: #3a3a3a; }
        """)

        self.initUI()
        self.update_date()

        timer = QTimer(self)
        timer.timeout.connect(self.update_date)
        timer.start(60000)

        self._restore_or_position()
        self.installEventFilter(self)
        hide_from_taskbar_later(self)

    def eventFilter(self, source, event):
        if event.type() == QEvent.Type.Resize and self._anchored:
            # Only auto-reanchor while anchored
            self.set_position()
        return super().eventFilter(source, event)

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

    def _restore_or_position(self):
        saved = self.pos_store.load()
        if saved and self._is_position_visible(*saved):
            self.move(*saved)
            self._locked_pos = QPoint(saved[0], saved[1])
            self._anchored = False
        else:
            self._anchored = True
            self.set_position()
            self._locked_pos = QPoint(self.pos())

    def set_position(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x_pos = screen.right() - self.RIGHT_OFFSET_PX - self.width()
        y_pos = self.sidebar_position.y() - 1
        self.move(x_pos, y_pos)

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(0)

        self.date_label = QLabel(self)
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.date_label.setFont(QFont('Arial', 25))
        self.date_label.setStyleSheet(f"color: rgba(255, 255, 255, {self.TEXT_TRANSPARENCY})")
        self.date_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        main_layout.addWidget(self.date_label)
        self.setLayout(main_layout)

    def _resize_to_text(self):
        fm = self.date_label.fontMetrics()
        text_w = fm.horizontalAdvance(self.date_label.text())
        text_h = fm.height()
        m = self.layout().contentsMargins()
        total_w = text_w + m.left() + m.right()
        total_h = text_h + m.top() + m.bottom()
        self.setFixedSize(total_w, total_h)

    def update_date(self):
        # 1. Capture the current visual right-hand edge (x + width)
        # We do this BEFORE changing text or size so we know where to stick.
        current_right_edge = self.x() + self.width()

        current_date = QDate.currentDate()
        day_name = current_date.toString('dddd')
        day = current_date.day()
        month_year = current_date.toString(' MMMM yyyy')
        day_suffix = self.get_day_suffix(day)
        formatted_date = f"{day_name} {day}{day_suffix}{month_year}"
        self.date_label.setText(formatted_date)

        # 2. Resize the widget based on new text length
        self._resize_to_text()

        # 3. Adjust position
        if self._anchored:
            # While anchored (default mode), keep the right edge fixed to screen offset
            self.set_position()
            self._locked_pos = QPoint(self.pos())
        else:
            # If user has moved it, we want the Right Edge to stay where the USER put it.
            # Since the width just changed, we must update X to compensate.
            # New X = Old Right Edge - New Width
            new_x = current_right_edge - self.width()
            self.move(new_x, self.y())
            self._locked_pos = QPoint(new_x, self.y())

    def get_day_suffix(self, day):
        if 4 <= day <= 20 or 24 <= day <= 30:
            return "th"
        else:
            return ["st", "nd", "rd"][day % 10 - 1]

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
                self.pos_store.save(current.x(), current.y())

        # Brief grace period: moveEvents can arrive slightly after mouseRelease
        # (especially during cross-monitor drags). Treat them as part of the drag.
        if was_dragging:
            self._drag_grace_period = True
            QTimer.singleShot(150, self._clear_grace_period)

    def _clear_grace_period(self):
        self._drag_grace_period = False

    # --- Context Menu + Mouse Events ---

    def show_context_menu(self, event):
        menu = QMenu(self)
        close_action = QAction("Close", self)
        close_action.triggered.connect(self.close)
        menu.addAction(close_action)
        menu.exec(event.globalPosition().toPoint())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.show_context_menu(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_drag(event.globalPosition().toPoint())
            self._anchored = False  # user is taking control → stop auto-reanchoring
            event.accept()

    def mouseMoveEvent(self, event):
        if self._is_dragging:
            self._do_drag(event.globalPosition().toPoint())
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._end_drag()
            event.accept()

    # --- Glitch Protection: moveEvent ---

    def moveEvent(self, event: QMoveEvent):
        """
        Intercept ALL move events. Only allow moves caused by user dragging.
        Snap back to _locked_pos if the OS glitches the position.
        """
        # If we don't have a locked position yet, accept whatever we get
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

        # Negligible jitter (≤2px) — allow it, not worth fighting
        if manhattan <= 2:
            super().moveEvent(event)
            return

        # Ghost Title Bar Fix: small upward shift of ~15-80px with minimal X change
        if 15 <= diff_y_signed <= 80 and diff_x <= 5:
            QTimer.singleShot(0, lambda pos=QPoint(locked): self.move(pos))
            return

        # Massive Jump Fix: coordinate space re-index (negative/huge coords)
        if manhattan > 100:
            QTimer.singleShot(0, lambda pos=QPoint(locked): self.move(pos))
            return

        # Any other unexpected OS-initiated shift — snap back
        QTimer.singleShot(0, lambda pos=QPoint(locked): self.move(pos))
        return

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

    # --- showEvent: connect screenChanged ---

    def showEvent(self, event):
        super().showEvent(event)

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

    def closeEvent(self, event):
        # Save the locked position on close (not the possibly-glitched self.pos())
        if self._locked_pos is not None:
            self.pos_store.save(self._locked_pos.x(), self._locked_pos.y())
        super().closeEvent(event)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    sidebar_position = QRect(1920 - 200, 0, 200, 1080)
    widget = DateWidget(sidebar_position)
    widget.show()
    sys.exit(app.exec())