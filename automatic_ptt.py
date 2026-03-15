import sys
import sounddevice as sd
import numpy as np
import time
import threading

from pynput.keyboard import Controller, KeyCode

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QSlider, QTabWidget, QTextEdit
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QColor, QPen


keyboard = Controller()

running = False
key_held = False
last_voice_time = 0
max_volume_seen = 0.01
current_volume = 0
smoothed_volume = 0
stream = None
smoothing_factor = 0.35

last_ptt_key = "v"


# ---------------- MIC DETECTION ----------------

def is_working_mic(index):
    try:
        with sd.InputStream(device=index, channels=1, samplerate=44100) as s:
            data, _ = s.read(1024)
            volume = np.sqrt(np.mean(data ** 2))
            return volume >= 0
    except Exception:
        return False


def get_valid_mics():
    devices = sd.query_devices()
    seen = set()
    valid = []

    for i, d in enumerate(devices):
        name = d["name"]

        if d["max_input_channels"] > 0:
            if name not in seen and all(x not in name for x in [
                "Stereo Mix", "Primary Sound Capture", "Microsoft Sound Mapper"
            ]):
                seen.add(name)

                if is_working_mic(i):
                    valid.append((i, name))

    return valid


# ---------------- AUDIO CALLBACK ----------------

def audio_callback(indata, frames, time_info, status):
    global current_volume, max_volume_seen

    volume = np.sqrt(np.mean(indata ** 2))

    # track loudest level we've seen
    if volume > max_volume_seen:
        max_volume_seen = volume

    # normalize against that level
    normalized = volume / max_volume_seen

    current_volume = min(normalized, 1.0)


# ---------------- MIC LOOP ----------------

def mic_loop(window):
    global key_held, last_voice_time, smoothed_volume

    MIN_HOLD = 0.1

    while running:

        volume = current_volume

        threshold_value = window.threshold_slider.value() / 1000
        release_delay = window.delay_slider.value() / 1000

        try:
            key_obj = KeyCode.from_char(window.ptt_key)
        except:
            key_obj = KeyCode.from_char("v")

        smoothed_volume = (
            smoothing_factor * volume +
            (1 - smoothing_factor) * smoothed_volume
        )

        if smoothed_volume > threshold_value:
            last_voice_time = time.time()

            if not key_held:
                keyboard.press(key_obj)
                key_held = True

        else:
            if key_held and (
                time.time() - last_voice_time > release_delay
                and time.time() - last_voice_time > MIN_HOLD
            ):
                keyboard.release(key_obj)
                key_held = False

        time.sleep(0.01)


# ---------------- MAIN WINDOW ----------------

class MicMeter(QWidget):

    def __init__(self):
        super().__init__()

        self.level = 0
        self.threshold = 0.2
        self.active = False

        self.history = [0] * 120  # waveform history

        self.setMinimumHeight(32)

    def setLevel(self, level):
        level = max(0, min(level, 1))
        self.level = level

        self.history.append(level)
        
        if len(self.history) > 120:
            self.history.pop(0)

        self.update()

    def setThreshold(self, threshold):
        self.threshold = threshold
        self.update()

    def setActive(self, active):
        self.active = active
        self.update()

    def paintEvent(self, event):

        painter = QPainter(self)

        w = self.width()
        h = self.height()

        # background
        painter.setBrush(QColor("#2b2d31"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, w, h, 10, 10)

        step = w / len(self.history)

        baseline = h

        for i, v in enumerate(self.history):

            x = i * step
            amplitude = v * (h * 0.95)

            # color zones
            if v < 0.2:
                color = QColor("#2ecc71")   # green (quiet)
            elif v < 0.6:
                color = QColor("#3498db")   # blue (normal speech)
            else:
                color = QColor("#e74c3c")   # red (loud)

            painter.setPen(QPen(color, 3))

            painter.drawLine(
                int(x),
                int(baseline),
                int(x),
                int(baseline - amplitude)
            )

        # horizontal threshold line
        threshold_y = int(h * (1 - self.threshold))

        pen = QPen(QColor("#ffffff"))
        pen.setWidth(2)

        painter.setPen(pen)

        painter.drawLine(0, threshold_y, w, threshold_y)

class MainWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Mic → Push-To-Talk")
        self.setMinimumSize(420, 420)

        self.ptt_key = "v"

        layout = QVBoxLayout()

        tabs = QTabWidget()

        self.main_tab = QWidget()
        self.dev_tab = QWidget()

        tabs.addTab(self.main_tab, "Main")
        tabs.addTab(self.dev_tab, "Dev")

        layout.addWidget(tabs)

        self.setLayout(layout)

        self.build_main_tab()
        self.build_dev_tab()

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_status)
        self.update_timer.start(50)

        self.debug_timer = QTimer()
        self.debug_timer.timeout.connect(self.update_debug)
        self.debug_timer.start(100)

    # -------- MAIN TAB --------

    def build_main_tab(self):

        layout = QVBoxLayout()

        # mic dropdown
        layout.addWidget(QLabel("Microphone"))

        self.mic_dropdown = QComboBox()
        layout.addWidget(self.mic_dropdown)

        self.refresh_mics()

        refresh_btn = QPushButton("Refresh Mics")
        refresh_btn.clicked.connect(self.refresh_mics)
        layout.addWidget(refresh_btn)

        # PTT key
        layout.addWidget(QLabel("PTT Key"))

        self.ptt_label = QLabel(self.ptt_key)
        layout.addWidget(self.ptt_label)

        change_key_btn = QPushButton("Change Key")
        change_key_btn.clicked.connect(self.capture_key)
        layout.addWidget(change_key_btn)

        # threshold slider
        layout.addWidget(QLabel("Mic Threshold"))

        self.threshold_slider = QSlider(Qt.Horizontal)
        self.threshold_slider.setRange(1, 100)
        self.threshold_slider.setValue(20)
        layout.addWidget(self.threshold_slider)

        # delay slider
        layout.addWidget(QLabel("Release Delay (ms)"))

        self.delay_slider = QSlider(Qt.Horizontal)
        self.delay_slider.setRange(0, 1000)
        self.delay_slider.setValue(300)
        layout.addWidget(self.delay_slider)

        # mic meter
        layout.addWidget(QLabel("Mic Level"))
        self.mic_meter = MicMeter()
        layout.addWidget(self.mic_meter)
        self.mic_meter.setFixedHeight(80)

        layout.setSpacing(14)
        layout.setContentsMargins(18,18,18,18)

        # status
        self.status_label = QLabel("Stopped")
        self.status_label.setStyleSheet("""
        font-size: 16px;
        font-weight: 600;
        color: #bbbbbb;
        """)
        layout.addWidget(self.status_label)

        # start stop buttons
        btn_layout = QHBoxLayout()

        start_btn = QPushButton("Start")
        start_btn.setStyleSheet("background-color:#27ae60;")
        start_btn.clicked.connect(self.start_script)

        stop_btn = QPushButton("Stop")
        stop_btn.setStyleSheet("background-color:#e74c3c;")
        stop_btn.clicked.connect(self.stop_script)

        btn_layout.addWidget(start_btn)
        btn_layout.addWidget(stop_btn)

        layout.addLayout(btn_layout)

        self.main_tab.setLayout(layout)

    # -------- DEV TAB --------

    def build_dev_tab(self):

        layout = QVBoxLayout()

        self.debug_text = QTextEdit()
        self.debug_text.setReadOnly(True)

        layout.addWidget(self.debug_text)

        self.dev_tab.setLayout(layout)

    # -------- FUNCTIONS --------

    def refresh_mics(self):

        self.mic_devices = get_valid_mics()

        self.mic_dropdown.clear()

        for i, name in self.mic_devices:
            self.mic_dropdown.addItem(name)

    def capture_key(self):
        self.status_label.setText("Press a key...")

        self.grabKeyboard()

    def keyPressEvent(self, event):
        key = event.text()

        if key:
            self.ptt_key = key.lower()
            self.ptt_label.setText(self.ptt_key)

        self.releaseKeyboard()
        self.status_label.setText("Listening" if running else "Stopped")

    def start_script(self):

        global running, stream

        if running:
            return

        if not self.mic_devices:
            self.status_label.setText("No working mic")
            return

        index = self.mic_devices[self.mic_dropdown.currentIndex()][0]

        try:
            stream = sd.InputStream(
                device=index,
                channels=1,
                samplerate=44100,
                callback=audio_callback
            )

            stream.start()

        except Exception as e:
            self.status_label.setText(f"Mic error: {e}")
            return

        running = True

        threading.Thread(target=mic_loop, args=(self,), daemon=True).start()

    def stop_script(self):

        global running, stream, key_held

        running = False

        if stream:
            stream.stop()
            stream.close()

        if key_held:
            keyboard.release(KeyCode.from_char(self.ptt_key))
            key_held = False

    def update_status(self):
        
        if not running:
            text = "Stopped"
        elif key_held:
            text = "PTT ACTIVE"
        else:
            text = "Listening"

        self.mic_meter.setLevel(smoothed_volume)
        self.mic_meter.setThreshold(self.threshold_slider.value() / 100)
        self.mic_meter.setActive(key_held)
        self.status_label.setText(text)

    def update_debug(self):

        text = f"""
Version: 1.5.0
Current Volume: {current_volume:.3f}
Smoothed Volume: {smoothed_volume:.3f}
PTT Held: {key_held}
Threshold: {self.threshold_slider.value()}
Release Delay: {self.delay_slider.value()}
Status: {"Listening" if running else "Stopped"}
"""

        self.debug_text.setText(text)


# ---------------- APP ----------------

app = QApplication(sys.argv)

app.setStyleSheet("""
QWidget {
    background-color: #1e1f22;
    color: #e6e6e6;
    font-size: 14px;
}

QTabWidget::pane {
    border: 1px solid #2b2d31;
    border-radius: 8px;
}

QTabBar::tab {
    background: #2b2d31;
    padding: 6px 14px;
    border-radius: 6px;
}

QTabBar::tab:selected {
    background: #3a3d42;
}

QLabel {
    font-weight: 500;
}

QComboBox {
    background: #2b2d31;
    border: 1px solid #3a3d42;
    padding: 6px;
    border-radius: 6px;
}

QPushButton {
    background-color: #3a86ff;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #559cff;
}

QPushButton:pressed {
    background-color: #2f6fd1;
}

QSlider::groove:horizontal {
    height: 6px;
    background: #2b2d31;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #3a86ff;
    width: 14px;
    margin: -4px 0;
    border-radius: 7px;
}
""")

window = MainWindow()
window.show()

sys.exit(app.exec())
