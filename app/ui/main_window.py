"""
Main window UI with all tabs and controls
"""
import os
import json
import time
import threading
import math
from PySide6.QtCore import Qt, QTimer, QRect, QPointF, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QSlider, QTabWidget, QTextEdit,
    QSplitter, QInputDialog, QListWidget, QListWidgetItem,
    QColorDialog, QSpinBox, QSizePolicy, QScrollArea, QApplication,
    QMessageBox, QFileDialog
)
from PySide6.QtGui import (
    QIcon, QPixmap, QLinearGradient, QPainter, QColor,
    QPen, QKeySequence, QFont, QPolygonF, QPalette
)

import app.config as config
from app.utils.helpers import log
from app.audio.sounds import AudioEventListenerWidget
from app.ui.widgets import create_studio_mic_icon
from app.core.profiles import (
    get_all_profile_names, profile_exists, get_profile, create_profile,
    delete_profile, load_profile, save_profile, rename_profile,
    duplicate_profile, set_default_profile, get_default_profile,
    export_profile, import_profile, get_profile_summary, save_profiles, validate_profile
)

class ModernMicMeter(QWidget):
    """Modern waveform visualization with smooth animation"""

    def __init__(self, theme):
        super().__init__()
        self.level = 0
        self.threshold = 0.2
        self.active = False
        self.history = [0] * 120
        self.animation_counter = 0
        self.theme = theme
        self.idle_mode = False
        self.setMinimumHeight(50)
        
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.animate)
        self.animation_timer.start(22)

    def set_theme(self, theme):
        """Update theme colors"""
        self.theme = theme
        self.update()

    def animate(self):
        """Continuously update for animation"""
        self.animation_counter = (self.animation_counter + 1) % 100
        self.update()

    def setLevel(self, level):
        with config.lock:
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

    def setIdle(self, idle: bool):
        """Toggle idle animation mode (draw waveform downward)."""
        self.idle_mode = idle
        self.update()

    def paintEvent(self, event):
        import numpy as np
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        from PySide6.QtGui import QPainterPath
        clip_path = QPainterPath()
        clip_path.addRoundedRect(0, 0, w, h, 12, 12)
        painter.setClipPath(clip_path)

        bg_gradient = QLinearGradient(0, 0, w, h)
        bg_gradient.setColorAt(0.0, QColor(self.theme.get("bg_dark", "#1a1a2e")))
        bg_gradient.setColorAt(1.0, QColor(self.theme.get("bg_light", "#16213e")))
        painter.setBrush(bg_gradient)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, w, h, 12, 12)

        border_color = QColor(self.theme.get("border_color", "#30363d"))
        border_color.setAlpha(200)
        painter.setPen(QPen(border_color, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(1, 1, w-2, h-2, 11, 11)

        step = (w - 4) / len(self.history)
        baseline = h * 0.7
        
        for i, v in enumerate(self.history):
            x = 2 + i * step
            display_v = max(0, min(v, 1.0))
            amplitude = display_v * (h * 0.5)
            
            if display_v < 0.15:
                color = QColor(self.theme.get("waveform_cyan", "#00d9ff"))
                alpha = int(150 + display_v / 0.15 * 50)
            elif display_v < 0.4:
                color = QColor(self.theme.get("waveform_blue", "#6a94ff"))
                alpha = int(200 + (display_v - 0.15) / 0.25 * 55)
            else:
                color = QColor(self.theme.get("waveform_pink", "#ff006e"))
                alpha = 255
            
            color.setAlpha(alpha)
            painter.setPen(QPen(color, 2.5))

            if self.idle_mode:
                y1 = int(baseline)
                y2 = int(min(h - 2, baseline + amplitude))
            else:
                y1 = int(baseline)
                y2 = int(max(0, baseline - amplitude))

            painter.drawLine(int(x), y1, int(x), y2)

        threshold_y = int(baseline - self.threshold * h * 0.5)
        glow_intensity = (np.sin(self.animation_counter / 12.0) * 0.5 + 0.5)
        
        threshold_color = QColor(self.theme.get("threshold_color", "#58a6ff"))
        
        for glow in range(3, 0, -1):
            glow_alpha = int(30 * glow * glow_intensity)
            glow_col = QColor(threshold_color)
            glow_col.setAlpha(glow_alpha)
            glow_pen = QPen(glow_col)
            glow_pen.setWidth(4 + glow)
            painter.setPen(glow_pen)
            painter.drawLine(2, threshold_y, w-2, threshold_y)
        
        threshold_alpha = int(100 + glow_intensity * 155)
        threshold_col = QColor(threshold_color)
        threshold_col.setAlpha(threshold_alpha)
        painter.setPen(QPen(threshold_col, 2))
        painter.drawLine(2, threshold_y, w-2, threshold_y)
        
        painter.setPen(QPen(threshold_col, 1))
        painter.setFont(QFont("Arial", 9))
        threshold_text = f"{int(self.threshold * 100)}%"
        painter.drawText(7, threshold_y - 5, threshold_text)


class MainWindow(QWidget):
    """Main application window"""

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        
        self.last_log_index = 0
        self._last_status_text = None
        self._last_ptt_active = None

        self.setWindowTitle("Mic → Push-To-Talk (Multi-Mode)")
        self.setMinimumSize(1200, 700)

        self.ptt_key = "v"
        self.activation_mode = "ptt"
        self.current_theme = config.DEFAULT_THEME.copy()
        self.color_previews = {}
        self.mic_devices = []

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        profile_layout = QHBoxLayout()
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.addWidget(QLabel("Current Profile:"))
        self.profile_label = QLabel("None")
        self.profile_label.setStyleSheet("font-weight: bold; color: #58a6ff;")
        profile_layout.addWidget(self.profile_label)
        profile_layout.addStretch()
        layout.addLayout(profile_layout)

        tabs = QTabWidget()
        tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.main_tab = QWidget()
        self.profiles_tab = QWidget()
        self.theme_tab = QWidget()
        self.targets_tab = QWidget()
        self.dev_tab = QWidget()

        tabs.addTab(self.main_tab, "Main")
        tabs.addTab(self.profiles_tab, "Profiles")
        tabs.addTab(self.targets_tab, "Targets")
        tabs.addTab(self.theme_tab, "Theme")
        tabs.addTab(self.dev_tab, "Dev")

        layout.addWidget(tabs, 1)
        self.setLayout(layout)

        self.build_main_tab()
        self.build_profiles_tab()
        self.build_targets_tab()
        self.build_theme_tab()
        self.build_dev_tab()
        
        # Delay slightly to ensure all widgets are created
        QTimer.singleShot(500, self.initialize_microphone_ui)
        
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_status)
        self.update_timer.start(100)

        self.debug_timer = QTimer()
        self.debug_timer.timeout.connect(self.update_debug)
        self.debug_timer.start(500)

    def build_main_tab(self):
        """Build main tab with controls"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # LEFT: Settings
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 12, 0)
        left_layout.setSpacing(12)
        
        # Mode selection
        mode_label = QLabel("Activation Mode")
        mode_label.setStyleSheet("font-weight: bold; color: #b0b0c0; font-size: 11px;")
        left_layout.addWidget(mode_label)
        
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["ptt", "tap", "voice_only", "always_on"])
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)
        left_layout.addWidget(self.mode_combo)
        
        self.mode_description = QLabel()
        self.mode_description.setWordWrap(True)
        self.mode_description.setStyleSheet("color: #808090; font-size: 10px;")
        left_layout.addWidget(self.mode_description)
        
        left_layout.addSpacing(12)
        
        # PTT Key
        ptt_label = QLabel("Activation Key")
        ptt_label.setStyleSheet("color: #b0b0c0; font-size: 11px;")
        left_layout.addWidget(ptt_label)
        
        ptt_layout = QHBoxLayout()
        self.ptt_label = QLabel("V")
        self.ptt_label.setStyleSheet("font-weight: bold; color: #58a6ff;")
        ptt_layout.addWidget(self.ptt_label)
        
        capture_ptt_btn = QPushButton("Change")
        capture_ptt_btn.setMaximumWidth(80)
        capture_ptt_btn.clicked.connect(self.capture_key)
        ptt_layout.addWidget(capture_ptt_btn)
        ptt_layout.addStretch()
        left_layout.addLayout(ptt_layout)
        
        # Mute Key
        mute_label_header = QLabel("Mute Key")
        mute_label_header.setStyleSheet("color: #b0b0c0; font-size: 11px;")
        left_layout.addWidget(mute_label_header)
        
        mute_layout = QHBoxLayout()
        self.mute_label = QLabel("M")
        self.mute_label.setStyleSheet("font-weight: bold; color: #58a6ff;")
        mute_layout.addWidget(self.mute_label)
        
        capture_mute_btn = QPushButton("Change")
        capture_mute_btn.setMaximumWidth(80)
        capture_mute_btn.clicked.connect(self.capture_mute_key)
        mute_layout.addWidget(capture_mute_btn)
        mute_layout.addStretch()
        left_layout.addLayout(mute_layout)
        
        # Mute Mode
        mute_mode_label = QLabel("Mute Mode")
        mute_mode_label.setStyleSheet("color: #b0b0c0; font-size: 11px;")
        left_layout.addWidget(mute_mode_label)
        
        self.mute_mode_combo = QComboBox()
        self.mute_mode_combo.addItems(["push", "toggle"])
        left_layout.addWidget(self.mute_mode_combo)
        
        left_layout.addSpacing(12)
        
        # System Mute Key (Optional - Windows only)
        system_mute_label_header = QLabel("System Mute Key (Optional)")
        system_mute_label_header.setStyleSheet("color: #b0b0c0; font-size: 11px;")
        left_layout.addWidget(system_mute_label_header)
        
        system_mute_layout = QHBoxLayout()
        self.system_mute_label = QLabel("NONE")
        self.system_mute_label.setStyleSheet("font-weight: bold; color: #888888;")
        self.system_mute_label.setMinimumWidth(100)
        system_mute_layout.addWidget(self.system_mute_label)
        
        capture_system_mute_btn = QPushButton("Set Key")
        capture_system_mute_btn.setMaximumWidth(80)
        capture_system_mute_btn.setToolTip("Press button, then press key to mute system microphone")
        capture_system_mute_btn.clicked.connect(self.capture_system_mute_key)
        system_mute_layout.addWidget(capture_system_mute_btn)
        
        clear_system_mute_btn = QPushButton("Clear")
        clear_system_mute_btn.setMaximumWidth(60)
        clear_system_mute_btn.setToolTip("Remove system mute key assignment")
        clear_system_mute_btn.clicked.connect(self.clear_system_mute_key)
        system_mute_layout.addWidget(clear_system_mute_btn)
        
        system_mute_layout.addStretch()
        left_layout.addLayout(system_mute_layout)
        
        # System Mute Mode
        system_mute_mode_label = QLabel("System Mute Mode")
        system_mute_mode_label.setStyleSheet("color: #b0b0c0; font-size: 11px;")
        left_layout.addWidget(system_mute_mode_label)
        
        self.system_mute_mode_combo = QComboBox()
        self.system_mute_mode_combo.addItems(["push", "toggle"])
        self.system_mute_mode_combo.setToolTip("push: Hold key to mute\ntoggle: Press to toggle mute")
        self.system_mute_mode_combo.currentTextChanged.connect(self.on_system_mute_mode_changed)
        self.system_mute_mode_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.system_mute_mode_combo.setMinimumWidth(120)
        left_layout.addWidget(self.system_mute_mode_combo)
        
        left_layout.addSpacing(12)
        
        # Threshold
        threshold_label = QLabel("Voice Threshold (0-100)")
        threshold_label.setStyleSheet("color: #b0b0c0; font-size: 11px;")
        left_layout.addWidget(threshold_label)
        
        threshold_layout = QHBoxLayout()
        self.threshold_slider = QSlider(Qt.Horizontal)
        self.threshold_slider.setRange(0, 100)
        self.threshold_slider.setValue(45)
        threshold_layout.addWidget(self.threshold_slider)
        
        self.threshold_spinbox = QSpinBox()
        self.threshold_spinbox.setRange(0, 100)
        self.threshold_spinbox.setValue(45)
        self.threshold_spinbox.setMaximumWidth(80)
        threshold_layout.addWidget(self.threshold_spinbox)
        
        self.threshold_slider.valueChanged.connect(self.on_threshold_changed)
        self.threshold_spinbox.valueChanged.connect(self.threshold_slider.setValue)
        left_layout.addLayout(threshold_layout)
        
        # Release Delay
        delay_sublabel = QLabel("Release Delay (ms)")
        delay_sublabel.setStyleSheet("color: #808090; font-size: 11px; margin-top: 12px;")
        left_layout.addWidget(delay_sublabel)
        
        delay_layout = QHBoxLayout()
        self.delay_slider = QSlider(Qt.Horizontal)
        self.delay_slider.setRange(0, 2000)
        self.delay_slider.setValue(500)
        delay_layout.addWidget(self.delay_slider)
        
        self.delay_spinbox = QSpinBox()
        self.delay_spinbox.setRange(0, 2000)
        self.delay_spinbox.setValue(500)
        self.delay_spinbox.setMaximumWidth(80)
        delay_layout.addWidget(self.delay_spinbox)
        
        self.delay_slider.valueChanged.connect(self.on_delay_changed)
        self.delay_spinbox.valueChanged.connect(self.delay_slider.setValue)
        left_layout.addLayout(delay_layout)

        fps_sublabel = QLabel("Animation FPS (20-60)")
        fps_sublabel.setStyleSheet("color: #808090; font-size: 11px; margin-top: 12px;")
        left_layout.addWidget(fps_sublabel)
        
        fps_layout = QHBoxLayout()
        self.fps_slider = QSlider(Qt.Horizontal)
        self.fps_slider.setRange(20, 60)
        self.fps_slider.setValue(45)
        fps_layout.addWidget(self.fps_slider)
        
        self.fps_spinbox = QSpinBox()
        self.fps_spinbox.setRange(20, 60)
        self.fps_spinbox.setValue(45)
        self.fps_spinbox.setMaximumWidth(80)
        fps_layout.addWidget(self.fps_spinbox)
        
        self.fps_slider.valueChanged.connect(self.fps_spinbox.setValue)
        self.fps_spinbox.valueChanged.connect(self.fps_slider.setValue)
        self.fps_slider.valueChanged.connect(self.on_fps_changed)
        left_layout.addLayout(fps_layout)

        left_layout.addStretch()

        # RIGHT: Waveform and Controls
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(12, 0, 0, 0)
        right_layout.setSpacing(12)
        
        waveform_label = QLabel("Microphone Level")
        waveform_label.setStyleSheet("font-weight: bold; color: #b0b0c0;")
        right_layout.addWidget(waveform_label)
        
        self.mic_meter = ModernMicMeter(self.current_theme)
        self.mic_meter.setFixedHeight(90)
        right_layout.addWidget(self.mic_meter)
        
        # Microphone selection
        mic_select_layout = QHBoxLayout()
        mic_select_layout.addWidget(QLabel("Microphone:"))
        self.mic_dropdown = QComboBox()
        self.mic_dropdown.currentIndexChanged.connect(self.on_mic_selected)
        mic_select_layout.addWidget(self.mic_dropdown)
        
        refresh_mics_btn = QPushButton("Refresh")
        refresh_mics_btn.setMaximumWidth(80)
        refresh_mics_btn.clicked.connect(self.refresh_mics)
        mic_select_layout.addWidget(refresh_mics_btn)
        right_layout.addLayout(mic_select_layout)
        
        # Status
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("Status:"))
        self.status_label = QLabel("Stopped")
        self.status_label.setStyleSheet("font-weight: bold; color: #f85149;")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        right_layout.addLayout(status_layout)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start_script)
        button_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_script)
        button_layout.addWidget(self.stop_btn)
        
        right_layout.addLayout(button_layout)
        right_layout.addStretch()
        
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 1)
        
        scroll_layout.addLayout(main_layout)
        scroll.setWidget(scroll_widget)
        
        tab_layout = QVBoxLayout()
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)
        self.main_tab.setLayout(tab_layout)
        
    def initialize_microphone_ui(self):
        """
        Initialize microphone selection on app startup.
        Auto-detects best mic on first run, uses stored selection on subsequent runs.
        """
        try:
            from app.core.controller import initialize_microphone
            
            log("Initializing microphone...", "INFO")
            
            success = initialize_microphone()
            if success:
                # Refresh the dropdown to show selected mic
                self.refresh_mics()
                log("Microphone initialized successfully", "INFO")
            else:
                log("Failed to initialize microphone", "ERROR")
                self.status_label.setText("⚠️ No microphones found")
        except Exception as e:
            log(f"Error initializing microphone: {e}", "ERROR")
            self.status_label.setText(f"⚠️ Mic initialization error")

    def build_profiles_tab(self):
        """Build profiles management tab"""
        layout = QVBoxLayout()
        layout.setSpacing(12)
        
        # Profile list
        list_label = QLabel("Saved Profiles")
        list_label.setStyleSheet("font-weight: bold; color: #b0b0c0;")
        layout.addWidget(list_label)
        
        self.profile_list = QListWidget()
        self.profile_list.itemSelectionChanged.connect(self.on_profile_selected)
        layout.addWidget(self.profile_list, 1)
        
        # Profile summary
        summary_label = QLabel("Profile Details")
        summary_label.setStyleSheet("font-weight: bold; color: #b0b0c0; margin-top: 12px;")
        layout.addWidget(summary_label)
        
        self.profile_summary = QTextEdit()
        self.profile_summary.setReadOnly(True)
        self.profile_summary.setMaximumHeight(100)
        layout.addWidget(self.profile_summary)
        
        # Action buttons
        button_layout = QVBoxLayout()
        button_layout.setSpacing(8)
        
        # Row 1: Create and Duplicate
        row1_layout = QHBoxLayout()
        
        new_profile_btn = QPushButton("New Profile")
        new_profile_btn.clicked.connect(self.create_new_profile)
        row1_layout.addWidget(new_profile_btn)
        
        duplicate_btn = QPushButton("Duplicate Selected")
        duplicate_btn.clicked.connect(self.duplicate_selected_profile)
        row1_layout.addWidget(duplicate_btn)
        
        button_layout.addLayout(row1_layout)
        
        # Row 2: Load and Save
        row2_layout = QHBoxLayout()
        
        load_profile_btn = QPushButton("Load Profile")
        load_profile_btn.setStyleSheet("background-color: #238636;")
        load_profile_btn.clicked.connect(self.load_selected_profile)
        row2_layout.addWidget(load_profile_btn)
        
        save_profile_btn = QPushButton("Save as Profile")
        save_profile_btn.clicked.connect(self.save_current_as_profile)
        row2_layout.addWidget(save_profile_btn)
        
        button_layout.addLayout(row2_layout)
        
        # Row 3: Rename and Set Default
        row3_layout = QHBoxLayout()
        
        rename_btn = QPushButton("Rename Selected")
        rename_btn.clicked.connect(self.rename_selected_profile)
        row3_layout.addWidget(rename_btn)
        
        set_default_btn = QPushButton("Set as Default")
        set_default_btn.clicked.connect(self.set_selected_as_default)
        row3_layout.addWidget(set_default_btn)
        
        button_layout.addLayout(row3_layout)
        
        # Row 4: Export and Delete
        row4_layout = QHBoxLayout()
        
        export_btn = QPushButton("Export")
        export_btn.clicked.connect(self.export_selected_profile)
        row4_layout.addWidget(export_btn)
        
        import_btn = QPushButton("Import")
        import_btn.clicked.connect(self.import_profile)
        row4_layout.addWidget(import_btn)
        
        button_layout.addLayout(row4_layout)
        
        # Row 5: Delete
        delete_profile_btn = QPushButton("Delete Selected")
        delete_profile_btn.setStyleSheet("background-color: #f85149;")
        delete_profile_btn.clicked.connect(self.delete_selected_profile)
        button_layout.addWidget(delete_profile_btn)
        
        layout.addLayout(button_layout)
        layout.addStretch()
        
        self.profiles_tab.setLayout(layout)
        
        # Refresh profile list on creation
        self.refresh_profile_list()

    def build_targets_tab(self):
        """Build targets tab"""
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Keypress Destinations"))
        
        self.targets_list = QListWidget()
        layout.addWidget(self.targets_list)
        
        add_layout = QHBoxLayout()
        self.target_dropdown = QComboBox()
        self.target_dropdown.setEditable(True)
        self.target_dropdown.setPlaceholderText("Type a process name (e.g. discord.exe) or pick one…")
        add_layout.addWidget(self.target_dropdown)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_target_dropdown)
        add_layout.addWidget(refresh_btn)
        
        add_target_btn = QPushButton("Add Target")
        add_target_btn.clicked.connect(self.add_target)
        add_layout.addWidget(add_target_btn)
        layout.addLayout(add_layout)
        
        remove_btn = QPushButton("Remove Selected")
        remove_btn.setStyleSheet("background-color: #f85149;")
        remove_btn.clicked.connect(self.remove_selected_target)
        layout.addWidget(remove_btn)
        
        layout.addStretch()
        self.targets_tab.setLayout(layout)

        # Initial population
        self.refresh_target_dropdown()
        self.refresh_targets_list()

    def build_theme_tab(self):
        """Build theme tab"""
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Theme Colors"))
        
        colors = [
            ("Background Dark", "bg_dark"),
            ("Background Light", "bg_light"),
            ("Waveform Cyan", "waveform_cyan"),
            ("Waveform Blue", "waveform_blue"),
            ("Waveform Pink", "waveform_pink"),
            ("Threshold Color", "threshold_color"),
            ("Border Color", "border_color"),
        ]
        
        for label, key in colors:
            btn_layout = QHBoxLayout()
            btn_layout.addWidget(QLabel(label))
            btn_layout.addStretch()
            
            color_btn = QPushButton("Pick Color")
            color_btn.clicked.connect(lambda checked, k=key: self.pick_color(k))
            btn_layout.addWidget(color_btn)
            
            self.color_previews[key] = QLabel()
            self.color_previews[key].setFixedSize(30, 30)
            self.update_color_preview(key)
            btn_layout.addWidget(self.color_previews[key])
            
            layout.addLayout(btn_layout)
        
        layout.addLayout(QHBoxLayout())
        
        reset_btn = QPushButton("Reset to Default Theme")
        reset_btn.clicked.connect(self.reset_theme)
        layout.addWidget(reset_btn)
        
        layout.addStretch()
        
        self.theme_tab.setLayout(layout)

    def build_dev_tab(self):
        """Build dev/debug tab with auto-loading logs and JSON"""
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Dev Console"))
    
        self.dev_tabs = QTabWidget()
    
        # ---- Logs tab ----
        logs_tab = QWidget()
        logs_layout = QVBoxLayout(logs_tab)
    
        splitter = QSplitter(Qt.Vertical)
        splitter.setSizes([200, 300])  # Initial sizes: debug 200px, logs 300px
        splitter.setCollapsible(0, False)  # Prevent collapse
        splitter.setCollapsible(1, False)
    
        # Debug info (top)
        self.debug_info = QTextEdit()
        self.debug_info.setReadOnly(True)
        self.debug_info.setMinimumHeight(80)
        self.debug_info.setMaximumHeight(250)
        self.debug_info.setStyleSheet("""
            QTextEdit {
                background-color: #0d1117;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
                font-size: 9pt;
                padding: 8px;
            }
        """)
    
        # Log console (bottom)
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setMinimumHeight(100)
        self.log_console.setStyleSheet("""
            QTextEdit {
                background-color: #0d1117;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
                font-size: 9pt;
                padding: 8px;
            }
        """)
    
        splitter.addWidget(self.debug_info)
        splitter.addWidget(self.log_console)
        logs_layout.addWidget(splitter, 1)
    
        # Control buttons
        logs_controls = QHBoxLayout()
        logs_controls.setSpacing(8)
        
        self.pause_logs_btn = QPushButton("Pause Logs")
        self.pause_logs_btn.setCheckable(True)
        self.pause_logs_btn.setMaximumWidth(100)
        self.pause_logs_btn.setToolTip("Pause live log updates")
        self.pause_logs_btn.toggled.connect(self.on_pause_logs_toggled)
        logs_controls.addWidget(self.pause_logs_btn)
    
        clear_btn = QPushButton("Clear")
        clear_btn.setMaximumWidth(80)
        clear_btn.setToolTip("Clear log buffer and display")
        clear_btn.clicked.connect(self.clear_logs)
        logs_controls.addWidget(clear_btn)
        
        scroll_to_bottom_btn = QPushButton("Scroll to Bottom")
        scroll_to_bottom_btn.setMaximumWidth(140)
        scroll_to_bottom_btn.clicked.connect(self.scroll_logs_to_bottom)
        logs_controls.addWidget(scroll_to_bottom_btn)
        
        logs_controls.addStretch()
        
        # Info label
        log_count_label = QLabel()
        log_count_label.setStyleSheet("color: #808090; font-size: 9px;")
        logs_controls.addWidget(log_count_label)
        self.log_count_label = log_count_label
        
        logs_layout.addLayout(logs_controls)
    
        self.dev_tabs.addTab(logs_tab, "Logs")
    
        # ---- Profile JSON tab ----
        profile_tab = QWidget()
        profile_layout = QVBoxLayout(profile_tab)
    
        # Top controls
        top = QHBoxLayout()
        top.setSpacing(8)
        
        top.addWidget(QLabel("Profile:"))
        
        self.dev_profile_combo = QComboBox()
        self.dev_profile_combo.addItems(get_all_profile_names())
        self.dev_profile_combo.currentTextChanged.connect(self.on_dev_profile_changed)
        top.addWidget(self.dev_profile_combo, 1)
    
        refresh_profiles_btn = QPushButton("Refresh List")
        refresh_profiles_btn.setMaximumWidth(100)
        refresh_profiles_btn.clicked.connect(self.refresh_dev_profile_list)
        top.addWidget(refresh_profiles_btn)
        
        load_current_btn = QPushButton("Load Current")
        load_current_btn.setMaximumWidth(130)
        load_current_btn.setToolTip("Load the currently active profile")
        load_current_btn.clicked.connect(self.load_current_profile_json)
        top.addWidget(load_current_btn)
    
        profile_layout.addLayout(top)
    
        # JSON editor
        self.profile_json_editor = QTextEdit()
        self.profile_json_editor.setPlaceholderText("Profile JSON will appear here...")
        self.profile_json_editor.setStyleSheet("""
            QTextEdit {
                background-color: #0d1117;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
                font-size: 9pt;
                padding: 8px;
            }
        """)
        profile_layout.addWidget(self.profile_json_editor, 1)
    
        # Bottom controls
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        
        validate_btn = QPushButton("Validate")
        validate_btn.setMaximumWidth(80)
        validate_btn.setToolTip("Validate JSON syntax")
        validate_btn.clicked.connect(self.validate_profile_json)
        bottom.addWidget(validate_btn)
    
        save_btn = QPushButton("Save to Disk")
        save_btn.setMaximumWidth(140)
        save_btn.clicked.connect(self.save_profile_json)
        bottom.addWidget(save_btn)
    
        apply_btn = QPushButton("Save & Apply")
        apply_btn.setMaximumWidth(150)
        apply_btn.setStyleSheet("background-color: #238636;")
        apply_btn.setToolTip("Save to disk and apply as active profile")
        apply_btn.clicked.connect(self.save_and_apply_profile_json)
        bottom.addWidget(apply_btn)
    
        bottom.addStretch()
        profile_layout.addLayout(bottom)
    
        self.dev_tabs.addTab(profile_tab, "Profile JSON")
    
        layout.addWidget(self.dev_tabs, 1)
        self.dev_tab.setLayout(layout)
        
        # Auto-populate on creation
        self.populate_dev_tab_initial_data()
    
    
    def populate_dev_tab_initial_data(self):
        """Populate logs and JSON on dev tab creation"""
        # Pre-fill log console with existing logs
        with config.log_lock:
            all_logs = config.log_buffer.copy()
        
        for log_line in all_logs:
            self.log_console.append(log_line)
        
        # Update log count
        self.update_log_count_label()
        
        # Auto-load current profile JSON
        if config.current_profile:
            self.dev_profile_combo.setCurrentText(config.current_profile)
            self.load_current_profile_json()
        else:
            # Load first profile if available
            profiles = get_all_profile_names()
            if profiles:
                self.dev_profile_combo.setCurrentText(profiles[0])
                self.load_selected_profile_json()
    
    
    def on_dev_profile_changed(self, profile_name):
        """Auto-load JSON when profile dropdown changes"""
        if profile_name:
            self.load_selected_profile_json()
    
    
    def update_log_count_label(self):
        """Update the log count display"""
        with config.log_lock:
            count = len(config.log_buffer)
        self.log_count_label.setText(f"Total logs: {count}")
    
    
    def scroll_logs_to_bottom(self):
        """Scroll log console to the bottom"""
        scrollbar = self.log_console.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def update_debug_improved(self):
        """Update debug console (improved version)"""
        with config.lock:
            is_running = config.running
            current_mode = config.activation_mode
            current_vol = config.current_volume
            smoothed_vol = config.smoothed_volume
            max_vol = config.max_volume_seen
        
        text = f"""
    === Mic → Push-To-Talk Debug Console ===
    
    STATUS: {"Listening" if is_running else "Stopped"}
    Mode: {current_mode}
    Volume: {current_vol:.3f}
    Smoothed: {smoothed_vol:.3f}
    Max Seen: {max_vol:.3f}
    
    Threshold: {self.threshold_slider.value()}
    Release Delay: {self.delay_slider.value()}ms
    Animation FPS: {self.fps_slider.value()}
    """
        self.debug_info.setText(text)
    
        # Skip log updates if paused
        if getattr(self, "pause_logs_btn", None) is not None and self.pause_logs_btn.isChecked():
            return
    
        # Check if we should scroll to bottom
        scrollbar = self.log_console.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 20
    
        # Get new logs
        with config.log_lock:
            new_logs = config.log_buffer[self.last_log_index:]
            self.last_log_index = len(config.log_buffer)
    
        # Append new logs
        for line in new_logs:
            self.log_console.append(line)
        
        # Update log count label
        self.update_log_count_label()
    
        # Auto-scroll to bottom if we were already there
        if at_bottom and new_logs:
            scrollbar.setValue(scrollbar.maximum())

    # -------- PROFILE METHODS --------

    def refresh_profile_list(self):
        """Refresh the profile list display"""
        self.profile_list.clear()
        for profile_name in get_all_profile_names():
            is_default = (profile_name == get_default_profile())
            item = QListWidgetItem(profile_name)
            if is_default:
                item.setData(Qt.UserRole, True)
            self.profile_list.addItem(item)

        for row in range(self.profile_list.count()):
            item = self.profile_list.item(row)
            prefix = "☆ " if (item.data(Qt.UserRole) is True) else "  "
            item.setText(prefix + item.text())

        # Global style for cyan/glow
        self.profile_list.setStyleSheet(
            """
            QListWidget::item {
                color: #c9d1d9;
            }
            QListWidget::item:selected {
                background: rgba(88, 166, 255, 0.2);
            }
            """
        )

    def _profile_name_from_list_item(self, item_text: str) -> str:
        # Strip our visual prefix (e.g. "☆ " or spaces) and return plain name
        text = (item_text or "").lstrip("☆ ").strip()
        return text

    def on_profile_selected(self):
        """Handle profile selection"""
        if self.profile_list.currentItem():
            profile_name = self._profile_name_from_list_item(self.profile_list.currentItem().text())
            summary = get_profile_summary(profile_name)
            if summary:
                self.profile_summary.setText(summary)

    def create_new_profile(self):
        """Create a new profile"""
        name, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if ok and name:
            if profile_exists(name):
                QMessageBox.warning(self, "Error", f"Profile '{name}' already exists")
                return
            
            if create_profile(name):
                self.refresh_profile_list()
                log(f"Created profile: {name}", "INFO")
            else:
                QMessageBox.warning(self, "Error", f"Failed to create profile '{name}'")

    def load_selected_profile(self):
        """Load the selected profile"""
        if self.profile_list.currentItem():
            profile_name = self._profile_name_from_list_item(self.profile_list.currentItem().text())
            if load_profile(profile_name):
                config.current_profile = profile_name
                self.profile_label.setText(profile_name)
                self.update_ui_from_profile()
                log(f"Loaded profile: {profile_name}", "INFO")
            else:
                QMessageBox.warning(self, "Error", f"Failed to load profile '{profile_name}'")

    def save_current_as_profile(self):
        """Save current settings as a new profile"""
        name, ok = QInputDialog.getText(self, "Save Profile", "Profile name:")
        if ok and name:
            # Ask if we should overwrite if it exists
            overwrite = True
            if profile_exists(name):
                reply = QMessageBox.question(
                    self, "Profile Exists", 
                    f"Profile '{name}' already exists. Overwrite?",
                    QMessageBox.Yes | QMessageBox.No
                )
                overwrite = (reply == QMessageBox.Yes)
            
            if save_profile(name, overwrite=overwrite):
                self.refresh_profile_list()
                log(f"Saved profile: {name}", "INFO")
            else:
                QMessageBox.warning(self, "Error", f"Failed to save profile '{name}'")

    def delete_selected_profile(self):
        """Delete the selected profile"""
        if self.profile_list.currentItem():
            profile_name = self._profile_name_from_list_item(self.profile_list.currentItem().text())
            
            reply = QMessageBox.question(
                self, "Confirm Delete",
                f"Delete profile '{profile_name}'?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                if delete_profile(profile_name):
                    self.refresh_profile_list()
                    self.profile_summary.clear()
                    log(f"Deleted profile: {profile_name}", "INFO")
                else:
                    QMessageBox.warning(self, "Error", f"Failed to delete profile '{profile_name}'")

    def rename_selected_profile(self):
        """Rename the selected profile"""
        if self.profile_list.currentItem():
            old_name = self._profile_name_from_list_item(self.profile_list.currentItem().text())
            new_name, ok = QInputDialog.getText(self, "Rename Profile", "New name:", text=old_name)
            
            if ok and new_name and new_name != old_name:
                if rename_profile(old_name, new_name):
                    self.refresh_profile_list()
                    log(f"Renamed profile: {old_name} -> {new_name}", "INFO")
                else:
                    QMessageBox.warning(self, "Error", f"Failed to rename profile")

    def duplicate_selected_profile(self):
        """Duplicate the selected profile"""
        if self.profile_list.currentItem():
            source_name = self._profile_name_from_list_item(self.profile_list.currentItem().text())
            new_name, ok = QInputDialog.getText(self, "Duplicate Profile", "New name:", text=source_name + "_copy")
            
            if ok and new_name:
                if duplicate_profile(source_name, new_name):
                    self.refresh_profile_list()
                    log(f"Duplicated profile: {source_name} -> {new_name}", "INFO")
                else:
                    QMessageBox.warning(self, "Error", f"Failed to duplicate profile")

    def set_selected_as_default(self):
        """Set selected profile as default"""
        if self.profile_list.currentItem():
            profile_name = self._profile_name_from_list_item(self.profile_list.currentItem().text())
            if set_default_profile(profile_name):
                self.refresh_profile_list()
                log(f"Default profile set to: {profile_name}", "INFO")

    def export_selected_profile(self):
        """Export selected profile to file"""
        if self.profile_list.currentItem():
            profile_name = self._profile_name_from_list_item(self.profile_list.currentItem().text())
            
            file_path, _ = QFileDialog.getSaveFileName(
                self, "Export Profile", f"{profile_name}.json", "JSON Files (*.json)"
            )
            
            if file_path:
                if export_profile(profile_name, file_path):
                    QMessageBox.information(self, "Success", f"Profile exported to {file_path}")
                else:
                    QMessageBox.warning(self, "Error", "Failed to export profile")

    def import_profile(self):
        """Import profile from file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Profile", "", "JSON Files (*.json)"
        )
        
        if file_path:
            # Get the profile name from the file or ask user
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                original_name = data.get("profile_name", "imported_profile")
            except:
                original_name = "imported_profile"
            
            name, ok = QInputDialog.getText(
                self, "Import Profile", "Profile name:", text=original_name
            )
            
            if ok and name:
                if import_profile(file_path, name):
                    self.refresh_profile_list()
                    log(f"Imported profile: {name}", "INFO")
                else:
                    QMessageBox.warning(self, "Error", "Failed to import profile")

    def update_ui_from_profile(self):
        """Update all UI elements from current profile"""
        try:
            self.mode_combo.setCurrentText(config.activation_mode)
            self.ptt_label.setText(config.ptt_key.upper())
            self.mute_label.setText(config.mute_key.upper())
            self.mute_mode_combo.setCurrentText(config.mute_mode)
            
            # Update system mute key label
            if config.system_mute_key:
                self.system_mute_label.setText(config.system_mute_key.upper())
                self.system_mute_label.setStyleSheet("font-weight: bold; color: #58a6ff;")
            else:
                self.system_mute_label.setText("NONE")
                self.system_mute_label.setStyleSheet("font-weight: bold; color: #888888;")
            
            # Update system mute mode combo
            self.system_mute_mode_combo.setCurrentText(config.system_mute_mode)
            
            self.threshold_slider.setValue(config.threshold)
            self.delay_slider.setValue(config.release_delay)
            self.refresh_targets_list()
            # Ensure mic dropdown is populated and selection restored
            if hasattr(self, "mic_dropdown"):
                self.refresh_mics()
                
            # Auto-populate logs on first profile load
            if hasattr(self, "log_console") and self.log_console.document().blockCount() <= 1:
                # Only populate once (when doc is empty - has 1 block by default)
                with config.log_lock:
                    all_logs = config.log_buffer.copy()
                
                for log_line in all_logs:
                    self.log_console.append(log_line)
                
                # Update log count
                if hasattr(self, "log_count_label"):
                    self.log_count_label.setText(
                        f"{self.log_console.document().blockCount()} lines"
                    )
                
                # Auto-load current profile JSON
                if hasattr(self, "dev_profile_combo"):
                    if config.current_profile:
                        self.dev_profile_combo.setCurrentText(config.current_profile)
                        self.load_current_profile_json()
                
        except Exception as e:
            log(f"Error updating UI from profile: {e}", "ERROR")

    # -------- OTHER METHODS --------

    def capture_system_mute_key(self):
        """Capture system mute key press"""
        self.system_mute_label.setText("...")
        self.system_mute_label.setStyleSheet("font-weight: bold; color: #f85149;")
        
        # Show instructions
        QMessageBox.information(
            self,
            "Set System Mute Key",
            "Press any key to set as system mute key.\n"
            "The application will listen for this key.",
            QMessageBox.Ok
        )
        
        # Listen for next key press globally
        self.waiting_for_system_mute_key = True
        self.focus()
        
        # Create a temporary event filter to catch key press
        import app.config as config
        
        def on_key_press(event):
            if event.type() == 6:  # KeyPress event
                try:
                    char = chr(event.key()).lower() if event.key() < 256 else None
                    if char and char.isalnum():
                        with config.lock:
                            config.system_mute_key = char
                        self.system_mute_label.setText(char.upper())
                        self.system_mute_label.setStyleSheet("font-weight: bold; color: #58a6ff;")
                        log(f"System mute key set to: {char}", "INFO")
                        self.waiting_for_system_mute_key = False
                        return True
                except Exception as e:
                    log(f"Error capturing system mute key: {e}", "ERROR")
            return False
        
        # This is a simplified version - in production, use keylistener or similar
        QMessageBox.warning(
            self,
            "Note",
            "System mute key capture requires global hotkey listener.\n"
            "Manual entry coming soon.",
            QMessageBox.Ok
        )
    
    def clear_system_mute_key(self):
        """Clear system mute key"""
        with config.lock:
            config.system_mute_key = None
        self.system_mute_label.setText("NONE")
        self.system_mute_label.setStyleSheet("font-weight: bold; color: #888888;")
        log("System mute key cleared", "INFO")
    
    def on_system_mute_mode_changed(self, mode):
        """Handle system mute mode change"""
        with config.lock:
            config.system_mute_mode = mode
        log(f"System mute mode changed to: {mode}", "INFO")

    def on_mode_changed(self, mode):
        """Update mode description"""
        config.activation_mode = mode
        self.activation_mode = mode
        descriptions = {
            "ptt": "Hold the key to transmit. Release to stop.",
            "tap": "Press the key to toggle transmit ON/OFF.",
            "voice_only": "Transmit automatically when voice is detected.",
            "always_on": "Always transmitting. Useful for testing."
        }
        self.mode_description.setText(descriptions.get(mode, ""))

    def on_threshold_changed(self, value):
        """Update threshold value"""
        config.threshold = value

    def on_delay_changed(self, value):
        """Update release delay value"""
        config.release_delay = value

    def on_fps_changed(self, fps_value):
        """Update animation FPS"""
        interval_ms = max(1, 1000 // fps_value)
        self.mic_meter.animation_timer.setInterval(interval_ms)

    def refresh_mics(self):
        """Refresh microphone list - simple version"""
        from app.audio.mic_monitor import list_microphones
        
        log("Refreshing microphone list...", "INFO")
        
        # Get list of working mics (this tests each one!)
        self.mic_devices = list_microphones()
        
        # Clear and repopulate dropdown
        self.mic_dropdown.clear()
        
        if not self.mic_devices:
            self.mic_dropdown.addItem("No working microphones found")
            log("No working microphones found!", "WARNING")
            return
        
        # Add each mic to dropdown
        for device_id, name in self.mic_devices:
            self.mic_dropdown.addItem(name)
        
        log(f"Found {len(self.mic_devices)} working microphone(s)", "INFO")
        
        # Select first one
        if len(self.mic_devices) > 0:
            self.mic_dropdown.setCurrentIndex(0)
            log(f"Selected: {self.mic_devices[0][1]}", "INFO")

    def on_mic_selected(self, index: int):
        """Persist selected microphone device id."""
        try:
            if not hasattr(self, "mic_devices") or index < 0 or index >= len(self.mic_devices):
                return
            device_id, _name = self.mic_devices[index]
            with config.lock:
                config.selected_mic_device_id = device_id
            if config.current_profile:
                try:
                    save_profile(config.current_profile, overwrite=True)
                except Exception as e:
                    log(f"Failed to persist mic selection to profile: {e}", "ERROR")
        except Exception as e:
            log(f"Error selecting mic: {e}", "ERROR")

    def start_script(self):
        """Start PTT"""
        if hasattr(self, 'parent_app'):
            self.parent_app.start_ptt()

    def stop_script(self):
        """Stop PTT"""
        if hasattr(self, 'parent_app'):
            self.parent_app.stop_ptt()

    def add_target(self):
        """Add target"""
        target = (self.target_dropdown.currentText() or "").strip()
        if not target:
            return

        with config.lock:
            if not isinstance(config.selected_targets, list):
                config.selected_targets = []
            if target in config.selected_targets:
                return
            config.selected_targets.append(target)

        self.refresh_targets_list()

        # Persist to current profile if one is loaded
        if config.current_profile:
            try:
                save_profile(config.current_profile, overwrite=True)
            except Exception as e:
                log(f"Failed to persist targets to profile: {e}", "ERROR")

        log(f"Added target: {target}", "INFO")

    def remove_selected_target(self):
        """Remove selected targets"""
        selected_items = self.targets_list.selectedItems()
        if not selected_items:
            return

        to_remove = {item.text() for item in selected_items}
        with config.lock:
            if isinstance(config.selected_targets, list):
                config.selected_targets = [t for t in config.selected_targets if t not in to_remove]
            else:
                config.selected_targets = []

        self.refresh_targets_list()

        # Persist to current profile if one is loaded
        if config.current_profile:
            try:
                save_profile(config.current_profile, overwrite=True)
            except Exception as e:
                log(f"Failed to persist targets to profile: {e}", "ERROR")

        log("Removed targets", "INFO")

    def refresh_targets_list(self):
        """Refresh the list of selected targets from config"""
        if not hasattr(self, "targets_list"):
            return
        self.targets_list.clear()
        with config.lock:
            targets = list(config.selected_targets) if isinstance(config.selected_targets, list) else []
        for t in targets:
            self.targets_list.addItem(QListWidgetItem(str(t)))

    def refresh_target_dropdown(self):
        """Refresh available target suggestions (running processes)"""
        if not hasattr(self, "target_dropdown"):
            return

        current_text = self.target_dropdown.currentText()
        self.target_dropdown.blockSignals(True)
        try:
            self.target_dropdown.clear()
            suggestions = []
            try:
                import psutil  # type: ignore
                seen = set()
                for p in psutil.process_iter(["name"]):
                    name = (p.info.get("name") or "").strip()
                    if not name or name in seen:
                        continue
                    seen.add(name)
                    suggestions.append(name)
            except Exception as e:
                log(f"Target refresh: psutil unavailable or failed: {e}", "ERROR")

            suggestions.sort(key=lambda s: s.lower())
            self.target_dropdown.addItems(suggestions)
        finally:
            self.target_dropdown.blockSignals(False)
            # Restore whatever the user had typed
            if current_text:
                self.target_dropdown.setCurrentText(current_text)

    def pick_color(self, color_key):
        """Pick color"""
        current_color = QColor(self.current_theme.get(color_key, "#00d9ff"))
        new_color = QColorDialog.getColor(current_color, self, f"Choose {color_key}")
        if new_color.isValid():
            self.current_theme[color_key] = new_color.name()
            self.update_color_preview(color_key)

    def update_color_preview(self, key):
        """Update color preview"""
        if key not in self.color_previews:
            return
        color = QColor(self.current_theme.get(key, "#00d9ff"))
        self.color_previews[key].setStyleSheet(f"background-color: {color.name()}; border-radius: 4px;")

    def reset_theme(self):
        """Reset theme to default"""
        self.current_theme = config.DEFAULT_THEME.copy()
        for key in self.color_previews:
            self.update_color_preview(key)
        log("Theme reset to default", "INFO")

    def clear_logs(self):
        """Clear log buffer"""
        with config.log_lock:
            config.log_buffer.clear()
        self.log_console.clear()
        self.last_log_index = 0

    def on_pause_logs_toggled(self, checked: bool):
        """Pause/resume streaming logs into the UI."""
        self.pause_logs_btn.setText("Resume" if checked else "Pause")

    def refresh_dev_profile_list(self):
        """Refresh profile list dropdown in Dev tab."""
        if not hasattr(self, "dev_profile_combo"):
            return
        current = self.dev_profile_combo.currentText()
        self.dev_profile_combo.blockSignals(True)
        try:
            self.dev_profile_combo.clear()
            self.dev_profile_combo.addItems(get_all_profile_names())
        finally:
            self.dev_profile_combo.blockSignals(False)
        if current:
            self.dev_profile_combo.setCurrentText(current)

    def _get_selected_dev_profile_name(self):
        if not hasattr(self, "dev_profile_combo"):
            return None
        name = (self.dev_profile_combo.currentText() or "").strip()
        return name or None

    def load_selected_profile_json(self):
        """Load selected profile JSON into editor."""
        name = self._get_selected_dev_profile_name()
        if not name:
            return
        profile = get_profile(name)
        if not profile:
            QMessageBox.warning(self, "Error", f"Profile '{name}' not found")
            return
        self.profile_json_editor.setPlainText(json.dumps(profile, indent=2, sort_keys=True))

    def load_current_profile_json(self):
        """Load current profile JSON into editor."""
        if config.current_profile:
            self.dev_profile_combo.setCurrentText(config.current_profile)
            self.load_selected_profile_json()

    def validate_profile_json(self):
        """Validate JSON in editor."""
        try:
            data = json.loads(self.profile_json_editor.toPlainText() or "{}")
            if not isinstance(data, dict):
                raise ValueError("Root JSON value must be an object/dict")
            QMessageBox.information(self, "OK", "JSON is valid.")
        except Exception as e:
            QMessageBox.warning(self, "Invalid JSON", str(e))

    def _save_profile_json_internal(self, apply_after: bool):
        name = self._get_selected_dev_profile_name()
        if not name:
            return
        try:
            data = json.loads(self.profile_json_editor.toPlainText() or "{}")
            if not isinstance(data, dict):
                raise ValueError("Root JSON value must be an object/dict")
        except Exception as e:
            QMessageBox.warning(self, "Invalid JSON", str(e))
            return

        # Update in-memory profile store via module global dict
        try:
            import app.core.profiles as profiles_mod
            profiles_mod.all_profiles[name] = data
            validate_profile(name)
            if not save_profiles():
                raise RuntimeError("save_profiles() failed")
        except Exception as e:
            QMessageBox.warning(self, "Save Failed", str(e))
            return

        if apply_after:
            try:
                load_profile(name)
                config.current_profile = name
                self.profile_label.setText(name)
                self.update_ui_from_profile()
            except Exception as e:
                QMessageBox.warning(self, "Apply Failed", str(e))
                return

        QMessageBox.information(self, "Saved", f"Profile '{name}' saved.")

    def save_profile_json(self):
        """Save JSON to disk for selected profile."""
        self._save_profile_json_internal(apply_after=False)

    def save_and_apply_profile_json(self):
        """Save JSON and apply it as the active profile."""
        self._save_profile_json_internal(apply_after=True)

    def capture_key(self):
        """Capture PTT key"""
        self.status_label.setText("Press activation key...")
        self.grabKeyboard()
        self.capturing_ptt = True

    def capture_mute_key(self):
        """Capture mute key"""
        self.status_label.setText("Press mute key...")
        self.grabKeyboard()
        self.capturing_mute = True

    def keyPressEvent(self, event):
        """Handle key press during capture"""
        key = QKeySequence(event.key()).toString().lower()

        if key:
            if getattr(self, "capturing_mute", False):
                self.mute_label.setText(key)
                self.capturing_mute = False
                config.mute_key = key
                log(f"Mute key set to: {key}", "INFO")
                self.releaseKeyboard()
                self.status_label.setText("Stopped")
                
            elif getattr(self, "capturing_ptt", False):
                self.ptt_label.setText(key)
                self.ptt_key = key
                config.ptt_key = key
                self.capturing_ptt = False
                log(f"Activation key set to: {key}", "INFO")
                self.releaseKeyboard()
                self.status_label.setText("Stopped")

    def update_status(self):
        """Update UI status"""
        with config.lock:
            is_running = config.running
            is_muted = config.mute_held or config.mute_toggled
            is_ptt = config.key_held
            volume = config.smoothed_volume
            mode = config.activation_mode
        
        if not is_running:
            text = "Stopped"
            color = "#f85149"  # red
        elif is_muted:
            text = "MUTED"
            color = "#8b949e"  # gray
        elif is_ptt:
            text = "TRANSMITTING"
            color = "#58a6ff"  # blue
        else:
            text = "Listening"
            color = "#3fb950"  # green

        if config.smoothed_volume < 0.01:
            idle_value = (math.sin(time.time() * 3) * 0.5 + 0.5) * 0.08
            self.mic_meter.setIdle(True)
            self.mic_meter.setLevel(idle_value)
        else:
            self.mic_meter.setIdle(False)
            self.mic_meter.setLevel(volume)
        
        self.mic_meter.setThreshold(self.threshold_slider.value() / 100)
        self.mic_meter.setActive(is_ptt and not is_muted)
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"font-weight: bold; color: {color};")

    def update_debug(self):
        """Update debug console"""
        with config.lock:
            is_running = config.running
            current_mode = config.activation_mode
            current_vol = config.current_volume
            smoothed_vol = config.smoothed_volume
            max_vol = config.max_volume_seen
        
        text = f"""
=== Mic → Push-To-Talk Debug Console ===

STATUS: {"Listening" if is_running else "Stopped"}
Mode: {current_mode}
Volume: {current_vol:.3f}
Smoothed: {smoothed_vol:.3f}
Max Seen: {max_vol:.3f}

Threshold: {self.threshold_slider.value()}
Release Delay: {self.delay_slider.value()}ms
Animation FPS: {self.fps_slider.value()}
"""
        self.debug_info.setText(text)

        if getattr(self, "pause_logs_btn", None) is not None and self.pause_logs_btn.isChecked():
            return
        
        if self.log_console.document().blockCount() <= 1:
            # Console is empty, populate with all logs
            with config.log_lock:
                all_logs = config.log_buffer.copy()
            
            for log_line in all_logs:
                self.log_console.append(log_line)
            
            self.last_log_index = len(config.log_buffer)
            
            # Update count
            if hasattr(self, "log_count_label"):
                self.log_count_label.setText(
                    f"{self.log_console.document().blockCount()} lines"
                )

        scrollbar = self.log_console.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 10

        with config.log_lock:
            new_logs = config.log_buffer[self.last_log_index:]
            self.last_log_index = len(config.log_buffer)

        for line in new_logs:
            self.log_console.append(line)

        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())
