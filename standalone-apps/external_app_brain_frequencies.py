# tone_player_codefile_theme.py
# Theme copied from Code File Generator. Bottom-most, draggable, position memory in same folder.

import sys, os, json, math, platform, ctypes
from pathlib import Path
import sounddevice as sd
from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QAction, QCursor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QMenu, QFrame, QLabel, QSlider
)

if __package__:
    from .widget_core import hide_from_taskbar_later
else:
    from widget_core import hide_from_taskbar_later

# -------------------------
# Constants
# -------------------------
TRANSPARENCY_LEVEL = 230
APP_ID = "TonePlayer"

# -------------------------
# Theme (copied and minimally extended)
# -------------------------
def build_theme_qss():
    return f"""
#CodeFileGeneratorRoot {{ background: transparent; }}

/* App background: vertical gradient, per-corner radii */
#TopContainer {{
    border: none;
    border-top-left-radius: 20px;
    border-top-right-radius: 20px;
    border-bottom-left-radius: 20px;
    border-bottom-right-radius: 6px;
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0   #252525,
        stop:1   #2e2e2e
    );
}}

/* Inner cards if you add any */
QFrame#Card {{
    background: rgba(0,0,0,0.08);
    border: 1px solid #2f2f2f;
    border-radius: 14px;
}}
QFrame#Card:hover {{ border-color: #3a3a3a; }}

/* Labels default */
#CodeFileGeneratorRoot QLabel {{ color: #f0f0f0; background: transparent; }}

/* Buttons */
#CodeFileGeneratorRoot QPushButton {{
    color: #FFFFFF;
    font-size: 14px;
    font-weight: 500;
    border: none;
    border-radius: 6px;
    padding: 6px 12px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #343434,
                                stop:0.5 #262626,
                                stop:1 #1A1A1A);
}}
#CodeFileGeneratorRoot QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #424242,
                                stop:0.5 #323232,
                                stop:1 #232323);
}}
#CodeFileGeneratorRoot QPushButton:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #272727,
                                stop:0.5 #1B1B1B,
                                stop:1 #101010);
}}

/* Inputs */
#CodeFileGeneratorRoot QLineEdit {{
    background-color: #2b2b2b;
    border: 1px solid #444;
    border-radius: 6px;
    padding: 6px 8px;
    color: #f0f0f0;
}}
#CodeFileGeneratorRoot QLineEdit:focus {{ border-color: #5a5a5a; }}

/* Added: ComboBox & Slider to match input style */
#CodeFileGeneratorRoot QComboBox {{
    background-color: #2b2b2b;
    border: 1px solid #444;
    border-radius: 6px;
    padding: 4px 8px;
    color: #f0f0f0;
    min-height: 26px;
}}
#CodeFileGeneratorRoot QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid #3a3a3a;
}}
#CodeFileGeneratorRoot QComboBox QAbstractItemView {{
    background:#2f2f2f; color:#f0f0f0; selection-background-color:#444;
    border:1px solid #3a3a3a; border-radius:6px;
}}

#CodeFileGeneratorRoot QSlider::groove:horizontal {{
    height: 6px; background: #3c3c3c; margin: 2px 0; border-radius: 3px;
}}
#CodeFileGeneratorRoot QSlider::handle:horizontal {{
    background: #888; border: 1px solid #bdbdbd;
    width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
}}

/* Context menu */
QMenu {{
    background-color: #2b2b2b;
    border: 1px solid #3a3a3a;
    border-radius: 10px;
    padding: 6px;
    color: #f0f0f0;
}}
QMenu::item {{ padding: 6px 12px; border-radius: 6px; background: transparent; }}
QMenu::item:selected {{ background-color: #3a3a3a; }}
QMenu::separator {{ height: 1px; background: #3a3a3a; margin: 6px 4px; }}
"""

# -------------------------
# Position store (JSON in same folder)
# -------------------------
class PositionStore:
    def __init__(self, app_id: str):
        self.app_id = app_id
        self.path = Path(__file__).resolve().parent / "widget_positions.json"

    def load(self):
        try:
            if self.path.exists():
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

# -------------------------
# Audio engine
# -------------------------
class FrequencyPlayer:
    def __init__(self, init_frequency=852, sample_rate=44100):
        self.sample_rate = sample_rate
        self.frequency = init_frequency
        self.is_paused = True
        self.phase = 0.0

        self.current_volume = 0.0
        self.target_volume = 0.3
        self.volume_ramp_step = 0.0005

        self.use_isochronic = False
        self.modulation_frequency = 6.0
        self.mod_phase = 0.0

        self.stream = None

    def audio_callback(self, outdata, frames, time, status):
        if status:
            print(f"Status: {status}")

        if self.is_paused or self.frequency <= 0:
            outdata[:] = 0
            return

        c_inc = (math.tau * self.frequency) / self.sample_rate
        m_inc = (math.tau * self.modulation_frequency) / self.sample_rate

        for i in range(frames):
            diff = self.target_volume - self.current_volume
            if abs(diff) > self.volume_ramp_step:
                self.current_volume += self.volume_ramp_step if diff > 0 else -self.volume_ramp_step
            else:
                self.current_volume = self.target_volume

            sample = math.sin(self.phase) * self.current_volume
            self.phase += c_inc
            if self.phase > math.tau:
                self.phase -= math.tau

            if self.use_isochronic:
                self.mod_phase += m_inc
                if self.mod_phase > math.tau:
                    self.mod_phase -= math.tau
                envelope = 0.5 * (1 + math.sin(self.mod_phase))
                sample *= envelope

            outdata[i] = sample

    def start(self):
        if self.stream is not None:
            self.stop()
        self.stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=1,
            callback=self.audio_callback
        )
        self.stream.start()

    def stop(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.phase = 0.0

    def set_frequency(self, freq):
        self.frequency = freq
        self.phase = 0.0

    def set_volume(self, vol):
        self.target_volume = vol

    def pause(self, pause_state=True):
        self.is_paused = pause_state

# -------------------------
# Main window
# -------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setObjectName("brainFrequencies")
        self.setWindowTitle("Brain Frequencies")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnBottomHint |
            Qt.WindowType.Window
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(TRANSPARENCY_LEVEL / 255.0)

        self.pos_store = PositionStore(APP_ID)
        self._save_debounce = QTimer(self)
        self._save_debounce.setInterval(250)
        self._save_debounce.setSingleShot(True)
        self._save_debounce.timeout.connect(self._save_position_now)

        self.old_pos: QPoint | None = None
        self.has_started = False

        self.frequencies = [396, 432, 528, 639, 741, 852, 963]
        self.frequency_info = {
            396: ("Fear & Guilt Release", "396 Hz removes fear and guilt, aiding in breaking free from addiction loops."),
            432: ("Natural Tuning", "432 Hz is believed to be in tune with nature and the human body, promoting relaxation and harmony."),
            528: ("Love Frequency", "528 Hz is known as the Miracle Tone, fostering healing, transformation, and positive energy."),
            639: ("Relationship Frequency", "639 Hz is associated with reconnecting and balancing relationships, enhancing communication."),
            741: ("Awakening Intuition", "741 Hz may help in problem-solving and awakening intuition, supporting mental clarity."),
            852: ("Spiritual Order", "852 Hz is used to return to spiritual order, elevating consciousness and inner peace."),
            963: ("Divine Connection", "963 Hz opens higher consciousness and enhances spiritual insight.")
        }

        self.player = FrequencyPlayer(init_frequency=852)

        # Container with rounded gradient like Code File Generator
        root = QWidget()
        root.setObjectName("CodeFileGeneratorRoot")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame(root)
        self.container.setObjectName("TopContainer")
        outer.addWidget(self.container)

        main = QVBoxLayout(self.container)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(10)

        # Controls row
        control_bar = QHBoxLayout()
        self.freq_combo = QComboBox()
        for f in self.frequencies:
            self.freq_combo.addItem(f"{f} Hz", f)
        self.freq_combo.setCurrentIndex(self.frequencies.index(852))
        self.freq_combo.currentIndexChanged.connect(self.change_frequency)

        self.btn_pause_play = QPushButton("Play")
        self.btn_pause_play.clicked.connect(self.toggle_play_pause)

        self.toggle_modulation_btn = QPushButton("Isochronic: Off")
        self.toggle_modulation_btn.clicked.connect(self.toggle_modulation)

        control_bar.addWidget(self.freq_combo)
        control_bar.addWidget(self.btn_pause_play)
        control_bar.addWidget(self.toggle_modulation_btn)
        main.addLayout(control_bar)

        # Info
        self.lbl_frequency_info = QLabel()
        self.lbl_frequency_info.setWordWrap(True)
        self.lbl_frequency_info.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        main.addWidget(self.lbl_frequency_info)
        self.update_frequency_info()

        # Volume
        vol_row = QHBoxLayout()
        vol_label = QLabel("Volume:")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(30)
        self.volume_slider.valueChanged.connect(self.change_volume)
        vol_row.addWidget(vol_label)
        vol_row.addWidget(self.volume_slider)
        main.addLayout(vol_row)

        self.setCentralWidget(root)

        # Context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_menu)

        # Apply theme
        self.setStyleSheet(build_theme_qss())

        self.resize(520, 220)
        self._restore_position()
        hide_from_taskbar_later(self)

    # ---- actions ----
    def change_frequency(self):
        self.player.set_frequency(self.freq_combo.currentData())
        self.update_frequency_info()

    def update_frequency_info(self):
        f = self.freq_combo.currentData()
        name, desc = self.frequency_info.get(f, ("Unknown Frequency", "No information available."))
        self.lbl_frequency_info.setText(f"<b>{name}</b> ({f} Hz): {desc}")

    def change_volume(self):
        self.player.set_volume(self.volume_slider.value() / 100.0)

    def toggle_play_pause(self):
        if not self.has_started:
            self.player.start()
            self.player.pause(False)
            self.has_started = True
            self.btn_pause_play.setText("Pause")
        else:
            if self.player.is_paused:
                self.player.pause(False)
                self.btn_pause_play.setText("Pause")
            else:
                self.player.pause(True)
                self.btn_pause_play.setText("Play")

    def toggle_modulation(self):
        self.player.use_isochronic = not self.player.use_isochronic
        self.toggle_modulation_btn.setText("Isochronic: On" if self.player.use_isochronic else "Isochronic: Off")

    # ---- context menu ----
    def context_menu(self, _pos):
        m = QMenu(self)
        close_action = QAction("Close", self)
        close_action.triggered.connect(self.close)
        m.addAction(close_action)
        m.exec(QCursor.pos())

    # ---- drag window ----
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.old_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self.old_pos is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self.old_pos)
            self._request_save_pos()
            e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.old_pos = None
            self._request_save_pos()
            e.accept()

    # ---- bottom-most on Windows ----
    def showEvent(self, e):
        super().showEvent(e)
        if platform.system().lower().startswith("win"):
            try:
                hwnd = int(self.winId())
                SWP_NOSIZE=0x0001; SWP_NOMOVE=0x0002; SWP_NOACTIVATE=0x0010; SWP_NOSENDCHANGING=0x0400
                HWND_BOTTOM = 1
                ctypes.windll.user32.SetWindowPos(hwnd, HWND_BOTTOM, 0,0,0,0,
                                                  SWP_NOSIZE|SWP_NOMOVE|SWP_NOACTIVATE|SWP_NOSENDCHANGING)
            except Exception:
                pass

    # ---- position memory ----
    def moveEvent(self, _e):
        self._request_save_pos()

    def _restore_position(self):
        saved = self.pos_store.load()
        if saved:
            self.move(*saved)
        else:
            scr = QApplication.primaryScreen().availableGeometry()
            self.move(scr.center().x() - self.width()//2, scr.center().y() - self.height()//2)

    def _request_save_pos(self):
        self._save_debounce.start()

    def _save_position_now(self):
        tl = self.frameGeometry().topLeft()
        self.pos_store.save(tl.x(), tl.y())

    # ---- close ----
    def closeEvent(self, event):
        self.player.stop()
        self._save_position_now()
        super().closeEvent(event)

# -------------------------
# Entry
# -------------------------
def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
