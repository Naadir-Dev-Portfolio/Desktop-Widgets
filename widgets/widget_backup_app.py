import sys
import os
import json
import shutil
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QProgressBar,
    QMenu, QPlainTextEdit, QScrollArea
)
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot, Qt, QPoint, QTimer, QUrl
from PyQt6.QtGui import QMouseEvent, QAction, QCursor, QMoveEvent, QDesktopServices

if __package__:
    from .widget_core import hide_from_taskbar_later
else:
    from widget_core import hide_from_taskbar_later

# ==========================
# Constants for Configuration
# ==========================

APP_HEIGHT = 230
APP_WIDTH = 284
BOTTOM_OFFSET = 365
RIGHT_OFFSET = 435
TRANSPARENCY = 130 

SCROLLBAR_STYLE = """
    QScrollBar:vertical {
        border: none;
        background: transparent;
        width: 10px;
        margin: 0px 0px 0px 0px;
    }
    QScrollBar::handle:vertical {
        background: #555555;
        min-height: 20px;
        border-radius: 5px;
    }
    QScrollBar::handle:vertical:hover {
        background: #777777;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {
        background: none;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: none;
    }
"""

# ==========================
# Position persistence
# ==========================

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
                return QPoint(int(v["x"]), int(v["y"]))
        except Exception:
            pass
        return None

    def save(self, point: QPoint):
        try:
            data = {}
            if self.path.exists():
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        data = {}
                except Exception:
                    data = {}
            data[self.app_id] = {"x": point.x(), "y": point.y()}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

# ==========================
# Backup Thread
# ==========================

class BackupThread(QThread):
    update_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    total_files_signal = pyqtSignal(int)
    finished_signal = pyqtSignal()

    sources = [
        "D:/Libraries/Videos/Marvel Cinematic Universe",
        "F:/Music/Binaural beats"
    ]
    destination = "H:/test backup"

    def __init__(self):
        super().__init__()
        self._is_running = True

    def run(self):
        try:
            total_files = self.count_files(self.sources)
            self.total_files_signal.emit(total_files if total_files > 0 else 1)
            
            processed_files = 0
            self.update_signal.emit("Starting backup...\n")
            
            for source in self.sources:
                if not self._is_running:
                    break
                if not os.path.exists(source):
                    self.update_signal.emit(f"Source directory does not exist: {source}\n")
                    continue
                self.update_signal.emit(f"Backing up {source}...\n")
                processed_files = self.backup_directory(
                    source,
                    os.path.join(self.destination, os.path.basename(source)),
                    processed_files,
                    total_files
                )
            if self._is_running:
                self.update_signal.emit("Backup completed successfully.\n")
                self.progress_signal.emit(total_files if total_files > 0 else 1)
            else:
                self.update_signal.emit("Backup stopped by user.\n")
            self.finished_signal.emit()
        except Exception as e:
            self.update_signal.emit(f"An error occurred: {str(e)}\n")
            self.finished_signal.emit()

    def should_copy(self, source_file, dest_file):
        if not os.path.exists(dest_file):
            return True
        return os.path.getmtime(source_file) > os.path.getmtime(dest_file)

    def backup_directory(self, source, destination, processed_files, total_files):
        try:
            if not os.path.exists(destination):
                os.makedirs(destination)

            for item in os.listdir(source):
                if not self._is_running:
                    break
                source_item = os.path.join(source, item)
                destination_item = os.path.join(destination, item)

                if os.path.isdir(source_item):
                    processed_files = self.backup_directory(
                        source_item,
                        destination_item,
                        processed_files,
                        total_files
                    )
                elif self.should_copy(source_item, destination_item):
                    try:
                        shutil.copy2(source_item, destination_item)
                    except Exception as e:
                        self.update_signal.emit(f"Failed to copy {source_item}: {str(e)}\n")
                
                processed_files += 1
                self.progress_signal.emit(processed_files)

        except Exception as e:
            self.update_signal.emit(f"Error accessing {source}: {str(e)}\n")
        return processed_files

    def count_files(self, sources):
        total_files = 0
        for source in sources:
            if not os.path.exists(source):
                self.update_signal.emit(f"Source directory does not exist: {source}\n")
                continue
            for _, _, files in os.walk(source):
                total_files += len(files)
        return total_files

    def stop(self):
        self._is_running = False

# ==========================
# Main Application Window
# ==========================

class App(QWidget):
    APP_ID = "BackupApp"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Standalone Backup App")

        self.pos_store = PositionStore(self.APP_ID)
        
        # Position Lock Logic
        self._locked_pos = None
        self._is_dragging = False
        self._drag_occurred = False
        self._drag_offset = None

        self.initUI()
        self._restore_or_fallback()

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

        self.setStyleSheet("""
            QPushButton {
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 5px 10px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #343434, stop:1 #1A1A1A);
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #424242, stop:1 #232323);
            }
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

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(10)
        self.setLayout(self.layout)

        self.backup_btn = QPushButton('Start Backup', self)
        self.backup_btn.clicked.connect(self.toggle_backup)
        self.backup_btn.setFixedHeight(30)
        self.backup_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.layout.addWidget(self.backup_btn)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 3px;
                background-color: #2A2A2A;
                color: transparent;
                text-align: center;
                min-height: 6px;
                max-height: 6px;
            }
            QProgressBar::chunk {
                border-radius: 3px;
                background-color: #666666;
            }
        """)
        self.progress_bar.setFixedHeight(6) 
        self.layout.addWidget(self.progress_bar)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(
            SCROLLBAR_STYLE +
            "QScrollArea { background: transparent; } "
            "QScrollArea > QWidget { background: transparent; }"
        )
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll_area.viewport().setStyleSheet("background: transparent;")

        self.log_area = QPlainTextEdit(self)
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet(
                    SCROLLBAR_STYLE +
                    """
                    QPlainTextEdit {
                        background-color: rgba(30, 30, 30, 0.95);
                        color: white;
                        border: none;
                        border-radius: 12px;
                        padding: 6px;
                        font-size: 10pt;
                    }
                    QPlainTextEdit::viewport {
                        background: transparent;
                        border-radius: 12px;
                    }
                    """
                )
        self.log_area.setCursor(Qt.CursorShape.IBeamCursor)

        self.scroll_area.setWidget(self.log_area)
        self.scroll_area.setFixedHeight(75)
        self.layout.addWidget(self.scroll_area)
        self.layout.addStretch()
        hide_from_taskbar_later(self)

    # ---- Positioning Lock System ----

    def showEvent(self, event):
        super().showEvent(event)
        # Safely connect screen change signal after window creation
        if self.windowHandle():
            try:
                self.windowHandle().screenChanged.connect(self._on_screen_changed, Qt.ConnectionType.UniqueConnection)
            except:
                pass

    def _restore_or_fallback(self):
        saved = self.pos_store.load()
        if saved:
            x, y = saved.x(), saved.y()
        else:
            x, y = self._fallback_position()
            x, y = self._clamp_to_any_screen(x, y)
        
        # Initial lock
        p = QPoint(x, y)
        self.move(p)
        self._locked_pos = p

    def _fallback_position(self):
        screen = QApplication.primaryScreen()
        g = screen.availableGeometry()
        x = g.width() - APP_WIDTH - RIGHT_OFFSET
        y = g.height() - self.height() - BOTTOM_OFFSET
        return x, y

    def _clamp_to_any_screen(self, px: int, py: int) -> tuple[int, int]:
        point = QPoint(px, py)
        for s in QApplication.screens():
            geo = s.availableGeometry()
            if geo.adjusted(-APP_WIDTH + 1, -APP_HEIGHT + 1, 0, 0).contains(point):
                return px, py
        pri = QApplication.primaryScreen().availableGeometry()
        return pri.left() + 20, pri.top() + 20

    # ---- Dragging Logic (Centralized) ----

    def _start_drag(self, global_pos):
        self._is_dragging = True
        self._drag_occurred = False
        self._drag_offset = global_pos - self.pos()

    def _do_drag(self, new_top_left):
        if self._is_dragging:
            self._drag_occurred = True
            self.move(new_top_left)
            self._locked_pos = new_top_left

    def _end_drag(self):
        is_drag = self._is_dragging and self._drag_occurred
        if is_drag:
            if self._locked_pos:
                self.pos_store.save(self._locked_pos)
        self._is_dragging = False
        return is_drag

    # ---- OS Glitch Protection ----

    def moveEvent(self, event: QMoveEvent):
        # 1. User Drag: Always allow
        if self._is_dragging:
            super().moveEvent(event)
            return

        # 2. OS/Glitch Movement Detection
        if self._locked_pos:
            current_pos = self.pos()
            
            # --- FIX FOR UPWARD SHIFT ---
            # The OS tries to account for a title bar that doesn't exist, moving the app UP.
            # Up means Y decreases. So Locked_Y - Current_Y should be positive (~37px).
            # We widen the range (15 to 80) to account for different DPI scalings.
            diff_y = self._locked_pos.y() - current_pos.y()
            
            if 15 < diff_y < 80:
                # Detected the ghost title bar glitch. Snap back immediately.
                QTimer.singleShot(0, lambda: self.move(self._locked_pos))
                return

            # --- FIX FOR SMALL JITTERS ---
            # If the window moves a tiny amount (e.g. 1-15px) without the user dragging,
            # it is likely an OS rounding error or snap-to-grid artifact. Revert it.
            dist = (current_pos - self._locked_pos).manhattanLength()
            if 0 < dist < 15:
                QTimer.singleShot(0, lambda: self.move(self._locked_pos))
                return

            # --- FIX FOR NEGATIVE/MASSIVE JUMPS ---
            # If the window jumps > 100px instantly (e.g. to -709 coordinates),
            # we assume the monitor layout is freaking out.
            # We do NOT save this new position. We rely on _on_screen_changed to fix it.
            if dist > 100:
                return 

        super().moveEvent(event)

    def _on_screen_changed(self, screen):
        # When monitors extend/change, force the window back to the locked position
        # This overwrites the "-709" or shifted coordinates with the saved "correct" ones.
        if self._locked_pos:
            QTimer.singleShot(100, lambda: self.move(self._locked_pos))

    # ---- Mouse Overrides (User Interaction) ----

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            self.show_context_menu(event)
        elif event.button() == Qt.MouseButton.LeftButton:
            widget = self.childAt(event.position().toPoint())
            # Maintain check to avoid dragging when clicking buttons/text
            if not isinstance(widget, QPushButton) and not isinstance(widget, QPlainTextEdit):
                self._start_drag(event.globalPosition().toPoint())
                event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging and self._drag_offset:
            new_pos = event.globalPosition().toPoint() - self._drag_offset
            self._do_drag(new_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._end_drag()
            event.accept()

    # ---- Backup Logic ----

    def toggle_backup(self):
        if not hasattr(self, 'backup_thread') or not self.backup_thread.isRunning():
            self.start_backup()
        else:
            self.stop_backup()

    def start_backup(self):
        self.log_area.clear()
        self.progress_bar.setValue(0)
        self.backup_thread = BackupThread()
        self.backup_thread.update_signal.connect(self.update_status)
        self.backup_thread.progress_signal.connect(self.update_progress)
        self.backup_thread.total_files_signal.connect(self.set_total_files)
        self.backup_thread.finished_signal.connect(self.backup_completed)
        self.backup_thread.start()
        self.backup_btn.setText("Stop Backup")

    def stop_backup(self):
        if hasattr(self, 'backup_thread'):
            self.backup_thread.stop()
            self.backup_thread.wait()
        self.backup_btn.setText("Start Backup")
        self.update_status("Backup stopped by user.\n")

    def backup_completed(self):
        if self.backup_thread._is_running:
            self.update_status("Backup completed successfully.\n")
        self.backup_btn.setText("Start Backup")

    @pyqtSlot(str)
    def update_status(self, message):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.log_area.appendPlainText(f"{timestamp}: {message}")
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())

    @pyqtSlot(int)
    def update_progress(self, value):
        self.progress_bar.setValue(value)

    @pyqtSlot(int)
    def set_total_files(self, total_files):
        if total_files <= 0:
            total_files = 1
        self.progress_bar.setMaximum(total_files)

    def show_context_menu(self, event):
        menu = QMenu(self)
        close_action = QAction("Close", self)
        close_action.triggered.connect(self.close)
        menu.addAction(close_action)
        menu.exec(event.globalPosition().toPoint())

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = App()
    ex.show()
    sys.exit(app.exec())