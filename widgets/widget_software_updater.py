import sys
import json
import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import pyautogui
import re
import os
import shutil
from functools import partial
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
    QMessageBox, QScrollArea, QMenu, QTextEdit, QLabel, QSizePolicy
)
from PyQt6.QtCore import Qt, QPoint, QThread, pyqtSignal, QSize, QTimer, QRect
from PyQt6.QtGui import QMouseEvent, QMoveEvent, QIcon, QAction
from datetime import datetime

if __package__:
    from .widget_core import hide_from_taskbar_later
else:
    from widget_core import hide_from_taskbar_later

# ==========================
# Constants for Configuration
# ==========================

APP_HEIGHT = 490
APP_WIDTH  = 284

ANCHOR_HORIZONTAL = 'right'
ANCHOR_VERTICAL   = 'bottom'

H_OFFSET = 700
V_OFFSET = 226

FINE_TUNE_LEFT = 45
FINE_TUNE_UP   = 24

TRANSPARENCY = 130
FONT_SIZE = 9
CMD_BUTTON_WIDTH = max(30, int(APP_WIDTH * 0.10))  # Dynamic: always ~10% of width, min 30px

# ==========================
# CRITICAL: HIT-TEST BACKGROUND (LOW, NON-ZERO ALPHA)
# ==========================
HITTEST_BG = "rgba(0, 0, 0, 2)"   # visually invisible, still intercepts mouse wheel / clicks in gaps
ROOT_BG    = "rgba(0, 0, 0, 2)"   # root surface must NOT be alpha=0

# ==========================
# Relative icon paths
# ==========================
_EXT_DIR = Path(__file__).resolve().parent
_GUI_DIR = _EXT_DIR.parent
_ICON_DIR = _GUI_DIR / "resources" / "icons"
_REFRESH_ICON = str(_ICON_DIR / "refresh.png")
_CMD_ICON = str(_ICON_DIR / "cmd.png")

# ==========================
# Helper: Find Winget
# ==========================
def get_winget_path():
    path = shutil.which("winget")
    if path:
        return path
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        winget_path = Path(local_app_data) / "Microsoft" / "WindowsApps" / "winget.exe"
        if winget_path.exists():
            return str(winget_path)
    return "winget"

WINGET_EXE = get_winget_path()

# ==========================
# Styles (Matched to Backup & YouTube Apps)
# ==========================

SCROLLBAR_STYLE = """
    QScrollBar:vertical {
        border: none;
        background: transparent;
        width: 7px;
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

BUTTON_STYLE = f"""
    QPushButton {{
        color: #FFFFFF;
        border: none;
        border-radius: 6px;
        padding: 5px 10px;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 #343434, stop:1 #1A1A1A);
        font-weight: bold;
        font-size: {FONT_SIZE}pt;
        text-align: center;
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 #424242, stop:1 #232323);
    }}
    QPushButton:pressed {{
        background: #000000;
    }}
    QPushButton:focus {{
        outline: none;
    }}
    QPushButton:disabled {{
        background: transparent;
        color: #555555;
        border: none;
    }}
"""


MAINTENANCE_BUTTON_STYLE = """
    QPushButton {
        color: #dddddd;
        border: none;
        border-radius: 6px;
        padding: 4px 10px;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 #343434, stop:1 #1A1A1A);
        font-weight: normal;
        font-size: 8pt;
        text-align: left;
        padding-left: 10px;
    }
    QPushButton:hover {
        color: #ffffff;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 #424242, stop:1 #232323);
    }
    QPushButton:pressed {
        background: #000000;
    }
"""

UPDATE_LIST_STYLE = """
    QPushButton {
        color: #dddddd;
        border: none;
        border-radius: 6px;
        padding: 4px 10px;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 #343434, stop:1 #1A1A1A);
        font-weight: normal;
        font-size: 8pt;
        text-align: left;
        padding-left: 8px;
    }
    QPushButton:hover {
        color: #ffffff;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 #424242, stop:1 #232323);
    }
    QPushButton:pressed {
        background: #000000;
    }
    QPushButton:focus {
        outline: none;
    }
    QPushButton:disabled {
        background: transparent;
        color: #555555;
        border: none;
    }
"""


TOOLTIP_STYLE = """
    QToolTip {
        background-color: #1a1a1a;
        color: #e0e0e0;
        border: 1px solid #3a3a3a;
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 8pt;
    }
"""

TERMINAL_STYLE = f"""
    QTextEdit {{
        background: rgba(30, 30, 30, 0.95);
        color: white;
        border: none;
        border-radius: 6px;
        padding: 6px;
        font-size: {FONT_SIZE}pt;
    }}
""" + SCROLLBAR_STYLE

CONTEXT_MENU_STYLE = """
    QMenu {
        background-color: #2b2b2b;
        border: 1px solid #3a3a3a;
        border-radius: 10px;
        padding: 6px;
        color: #f0f0f0;
    }
    QMenu::item { padding: 6px 12px; border-radius: 6px; background: transparent; }
    QMenu::item:selected { background-color: #3a3a3a; }
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

# ==========================
# Command Thread
# ==========================

class CommandThread(QThread):
    output_signal = pyqtSignal(str)

    def __init__(self, command_list):
        super().__init__()
        self.command_list = command_list

    def run(self):
        process = subprocess.Popen(
            self.command_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=True,
            encoding="utf-8",
            errors="replace",
        )
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                self.output_signal.emit(output.strip())
        err_output = process.stderr.read()
        if err_output:
            self.output_signal.emit(err_output.strip())

# ==========================
# Main Application Window
# ==========================

class WingetUpdater(QWidget):
    APP_ID = "WingetUpdater_V2_HitTest"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Standalone Software Updater")
        self.placeholders_shown = False

        self.pos_store = PositionStore(self.APP_ID)

        # --- Position Locking System ---
        self._locked_pos = None       # The last known-good position (QPoint)
        self._is_dragging = False     # True only while the user is actively dragging
        self._drag_occurred = False   # True if mouse actually moved during a drag
        self._drag_offset = None      # Offset from mouse cursor to window top-left (QPoint)
        self._screen_change_connected = False  # Guard for one-time screenChanged connection
        self._drag_grace_period = False  # Brief grace period after drag ends

        self.initUI()
        self._restore_or_anchor()
        QTimer.singleShot(0, self.show_placeholders)

    def initUI(self):
        # ==========================
        # CRITICAL: FRAMELESS + TRANSLUCENT
        # ==========================
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnBottomHint |
            Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(TRANSPARENCY / 255)
        self.setFixedSize(APP_WIDTH, APP_HEIGHT)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        # Apply tooltip style at QApplication level
        QApplication.instance().setStyleSheet(TOOLTIP_STYLE)

        # ==========================
        # CRITICAL: ROOT HIT-TEST SURFACE (NO alpha=0)
        # ==========================
        self.setStyleSheet(f"""
            QWidget {{
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

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(6)
        self.setLayout(self.layout)

        # --- Refresh Button ---
        self.refresh_button = QPushButton('Refresh List')
        self.refresh_button.setFixedHeight(32)
        self.refresh_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.refresh_button.setStyleSheet(BUTTON_STYLE)
        self.refresh_button.setCursor(Qt.CursorShape.ArrowCursor)
        self.refresh_button.setIcon(QIcon(_REFRESH_ICON))
        self.refresh_button.setIconSize(QSize(14, 14))
        self.refresh_button.clicked.connect(self.refresh_list)
        self.layout.addWidget(self.refresh_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        # --- Updates Label ---
        self.updates_label = QLabel("Updates Available:")
        self.updates_label.setStyleSheet(
            f"padding: 0px; font-size: {FONT_SIZE}pt; color: #cccccc; background-color: transparent;"
        )
        self.updates_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.updates_label.setVisible(False)
        self.layout.addWidget(self.updates_label)

        # --- Scroll Area ---
        SCROLL_HEIGHT = 36 * 3

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll_area.setFixedHeight(SCROLL_HEIGHT)
        self.scroll_area.setStyleSheet(SCROLLBAR_STYLE + f"""
            QScrollArea {{ background-color: {HITTEST_BG}; border: none; }}
            QWidget#qt_scrollarea_viewport {{ background-color: {HITTEST_BG}; }}
        """)

        # Redundant + robust: ensure viewport surface is non-zero alpha
        self.scroll_area.viewport().setStyleSheet(f"background-color: {HITTEST_BG};")

        self.scroll_content = QWidget()
        self.scroll_content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.scroll_content.setStyleSheet(f"background-color: {HITTEST_BG};")

        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(6)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll_area.setWidget(self.scroll_content)
        self.layout.addWidget(self.scroll_area)

        self.layout.addSpacing(6)

        # --- Utility Buttons ---
        self.maintenance_container = QWidget()
        self.maintenance_container.setStyleSheet("background: transparent;")
        self.maintenance_layout = QVBoxLayout(self.maintenance_container)
        self.maintenance_layout.setContentsMargins(0, 6, 0, 0)
        self.maintenance_layout.setSpacing(4)

        self.layout.addWidget(self.maintenance_container)
        self.create_maintenance_buttons()

        # --- Status Label ---
        self.status_label = QLabel("Status:")
        self.status_label.setStyleSheet(
            f"padding-top: 6px; font-size: {FONT_SIZE}pt; color: #aaaaaa; background-color: transparent;"
        )
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.layout.addWidget(self.status_label)

        # --- Terminal Output ---
        self.terminal_output = QTextEdit(self)
        self.terminal_output.setFixedHeight(64)
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.terminal_output.setStyleSheet(TERMINAL_STYLE)
        self.terminal_output.setCursor(Qt.CursorShape.IBeamCursor)
        self.layout.addWidget(self.terminal_output)

        self.layout.addStretch(1)

        hide_from_taskbar_later(self)

    def create_maintenance_buttons(self):
        maintenance_buttons = [
            ('Check Windows Updates', self.run_windows_update),
            ('Run SFC Scan', self.run_sfc_scan),
            ('Run DISM Tool', self.run_dism_tool),
            ('Open Malwarebytes', self.open_malwarebytes),
            ('Open Windows Firewall', self.open_windows_firewall)
        ]

        for text, method in maintenance_buttons:
            button = QPushButton(text)
            button.setFixedHeight(28)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setCursor(Qt.CursorShape.ArrowCursor)
            button.setStyleSheet(MAINTENANCE_BUTTON_STYLE)
            button.setIcon(QIcon(_REFRESH_ICON))
            button.setIconSize(QSize(14, 14))
            button.clicked.connect(method)
            self.maintenance_layout.addWidget(button)

    # ---------- placeholders on first load ----------
    def show_placeholders(self):
        if self.placeholders_shown:
            return
        self.clear_layout(self.scroll_layout)
        self.updates_label.setVisible(True)

        for _ in range(5):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)

            ph = QPushButton("Not yet checked")
            ph.setFixedHeight(30)
            ph.setMinimumWidth(0)
            ph.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            ph.setEnabled(False)
            ph.setStyleSheet(UPDATE_LIST_STYLE)
            row.addWidget(ph, 1)

            ghost = QPushButton()
            ghost.setFixedHeight(30)
            ghost.setFixedWidth(CMD_BUTTON_WIDTH)
            ghost.setEnabled(False)
            ghost.setStyleSheet(BUTTON_STYLE)
            row.addWidget(ghost, 0)

            self.scroll_layout.addLayout(row)

        self.placeholders_shown = True

    def refresh_list(self):
        self.refresh_button.setEnabled(False)
        self.updates_label.setVisible(False)
        self.clear_layout(self.scroll_layout)
        self.fetch_updatable_software()

    def fetch_updatable_software(self):
        try:
            result = subprocess.run(
                [WINGET_EXE, 'list', '--upgrade-available'],
                capture_output=True,
                text=True,
                shell=True,
                encoding='utf-8',
                errors='ignore',
            )
            if result.returncode == 0:
                self.update_software_list(result.stdout)
            else:
                self.show_error('Failed to get the list of updatable software.\n' + result.stderr)
        except Exception as e:
            self.show_error(f'An error occurred: {e}')
        finally:
            self.refresh_button.setEnabled(True)

    def update_software_list(self, software_list):
        self.clear_layout(self.scroll_layout)

        lines = software_list.splitlines()
        if len(lines) >= 2:
            lines = lines[2:]

        rows = []
        for raw in lines:
            line = raw.strip()
            if not line or not any(ch.isalnum() for ch in line):
                continue
            if set(line) <= set("-=─┈┄┅┉━│┃┆┇┊┋·• "):
                continue

            parts = re.split(r"\s{2,}", line)
            if len(parts) < 5:
                continue

            name, app_id = parts[0], parts[1]
            if name.lower() == "name" or app_id.lower() == "id":
                continue

            rows.append((name, app_id))

        if not rows:
            no_software_label = QLabel("No software found.")
            no_software_label.setStyleSheet(
                f"padding: 10px; font-size: {FONT_SIZE}pt; color: white; background-color: transparent;"
            )
            no_software_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.scroll_layout.addWidget(no_software_label)
            self.updates_label.setVisible(False)
            return

        rows.sort(key=lambda x: x[0].lower(), reverse=True)
        self.updates_label.setVisible(True)

        for name, app_id in rows:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)

            update_button = QPushButton(name)
            update_button.setFixedHeight(30)
            update_button.setMinimumWidth(0)
            update_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            update_button.setCursor(Qt.CursorShape.PointingHandCursor)
            update_button.setStyleSheet(UPDATE_LIST_STYLE)
            update_button.setToolTip(name)
            update_button.clicked.connect(partial(self.update_software, app_id, name))

            cmd_button = QPushButton()
            cmd_button.setFixedHeight(30)
            cmd_button.setFixedWidth(CMD_BUTTON_WIDTH)
            cmd_button.setCursor(Qt.CursorShape.PointingHandCursor)
            cmd_button.setIcon(QIcon(_CMD_ICON))
            cmd_button.setIconSize(QSize(14, 14))
            cmd_button.setStyleSheet(BUTTON_STYLE)
            cmd_button.clicked.connect(partial(self.manual_update_software, app_id))
            cmd_button.setToolTip(f"Manually update {name}")

            row.addWidget(update_button, 1)
            row.addWidget(cmd_button, 0)
            self.scroll_layout.addLayout(row)

    def update_software(self, app_id, name):
        command = [WINGET_EXE, 'upgrade', '--id', app_id]
        self.command_thread = CommandThread(command)
        self.command_thread.output_signal.connect(self.update_terminal_output)
        self.command_thread.start()

    def update_terminal_output(self, output):
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.terminal_output.append(f"[{timestamp}] {output}")
        self.terminal_output.verticalScrollBar().setValue(self.terminal_output.verticalScrollBar().maximum())

    def manual_update_software(self, app_id):
        command = f'winget upgrade --id {app_id}'
        try:
            subprocess.Popen("start cmd", shell=True)
            pyautogui.sleep(1)
            pyautogui.typewrite(command)
            pyautogui.press("enter")
        except Exception as e:
            self.show_error(f"An error occurred while manually updating: {e}")

    def run_windows_update(self):
        try:
            command = (
                "Install-Module -Name PSWindowsUpdate -Force -AllowClobber; "
                "Import-Module PSWindowsUpdate; "
                "Get-WindowsUpdate -Install -AcceptAll -AutoReboot"
            )
            subprocess.Popen(
                ['powershell', '-Command',
                 f'Start-Process powershell -ArgumentList "-NoExit -Command {command}" -Verb RunAs'],
                shell=True
            )
        except Exception as e:
            self.show_error(f"An error occurred while running Windows Update: {e}")

    def run_sfc_scan(self):
        command = 'sfc /scannow'
        try:
            subprocess.Popen(['powershell', '-Command', f'Start-Process cmd -ArgumentList "/c {command}" -Verb RunAs'],
                             shell=True)
        except Exception as e:
            self.show_error(f"An error occurred while running SFC scan: {e}")

    def run_dism_tool(self):
        command = 'DISM /Online /Cleanup-Image /RestoreHealth'
        try:
            subprocess.Popen(['powershell', '-Command', f'Start-Process cmd -ArgumentList "/c {command}" -Verb RunAs'],
                             shell=True)
        except Exception as e:
            self.show_error(f"An error occurred while running DISM tool: {e}")

    def open_malwarebytes(self):
        try:
            subprocess.Popen("start mbam", shell=True)
        except Exception as e:
            self.show_error(f"An error occurred while opening Malwarebytes: {e}")

    def open_windows_firewall(self):
        try:
            subprocess.Popen("control firewall.cpl", shell=True)
        except Exception as e:
            self.show_error(f"An error occurred while opening Windows Firewall: {e}")

    def show_message(self, message):
        QMessageBox.information(self, 'Success', message)

    def show_error(self, message):
        QMessageBox.critical(self, 'Error', message)

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            l = item.layout()
            if w is not None:
                w.deleteLater()
            elif l is not None:
                self.clear_layout(l)

    # --- Context Menu ---
    def show_context_menu(self, event):
        context_menu = QMenu(self)
        context_menu.setStyleSheet(CONTEXT_MENU_STYLE)
        close_action = QAction("Close", self)
        close_action.triggered.connect(self.close)
        context_menu.addAction(close_action)
        context_menu.exec(event.globalPosition().toPoint())

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

    # --- Mouse Events (delegate to drag helpers) ---

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            self.show_context_menu(event)
        elif event.button() == Qt.MouseButton.LeftButton:
            widget = self.childAt(event.position().toPoint())
            if not isinstance(widget, (QPushButton, QTextEdit)):
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
        Only snap back if the user is NOT dragging — if they are dragging across
        monitors, let the drag proceed without interference.
        """
        if self._locked_pos is not None and not self._is_dragging:
            locked = QPoint(self._locked_pos)
            # Use lambdas that re-check _is_dragging at fire time,
            # in case a drag started between scheduling and firing.
            QTimer.singleShot(100, lambda: self.move(locked) if not self._is_dragging else None)
            QTimer.singleShot(300, lambda: self.move(locked) if not self._is_dragging else None)

    # ----- Positioning / Persistence -----
    def _calc_position(self, screen_geometry):
        if ANCHOR_HORIZONTAL.lower() == 'right':
            x = (screen_geometry.width() - self.width() - H_OFFSET - max(0, FINE_TUNE_LEFT) + min(0, FINE_TUNE_LEFT))
        else:
            x = max(0, H_OFFSET) + max(0, FINE_TUNE_LEFT)
        if ANCHOR_VERTICAL.lower() == 'bottom':
            y = (screen_geometry.height() - self.height() - V_OFFSET - max(0, FINE_TUNE_UP) + min(0, FINE_TUNE_UP))
        else:
            y = max(0, V_OFFSET) + max(0, FINE_TUNE_UP)
        return x, y

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

    def _restore_or_anchor(self):
        saved = self.pos_store.load()
        if saved and self._is_position_visible(*saved):
            self.move(*saved)
            self._locked_pos = QPoint(saved[0], saved[1])
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            x, y = self._calc_position(screen)
            self.move(x, y)
            self._locked_pos = QPoint(x, y)

    # --- showEvent: stay behind + connect screenChanged ---

    def showEvent(self, event):
        super().showEvent(event)

        # Keep behind all windows
        HWND_BOTTOM = 1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        SetWindowPos = ctypes.windll.user32.SetWindowPos
        SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_uint
        ]
        SetWindowPos.restype = wintypes.BOOL
        hwnd = int(self.winId())
        SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

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
                    pass  # Already connected or handle not ready

    def closeEvent(self, event):
        # Save current locked position on close (not the possibly-glitched self.pos())
        if self._locked_pos is not None:
            self.pos_store.save(self._locked_pos.x(), self._locked_pos.y())
        event.accept()

# ==========================
# Main Execution
# ==========================

if __name__ == '__main__':
    app = QApplication(sys.argv)
    updater = WingetUpdater()
    updater.show()
    sys.exit(app.exec())