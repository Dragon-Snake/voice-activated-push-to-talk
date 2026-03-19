"""
Quick actions overlay - floating status panel
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from app.config import activation_mode, current_profile, mute_held, mute_toggled, smoothed_volume, lock


class QuickActionsOverlay(QWidget):
    """Floating overlay panel showing current status and quick actions"""
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setup_ui()
        self.setup_timers()
    
    def setup_ui(self):
        """Setup overlay UI"""
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Title
        title_layout = QHBoxLayout()
        title_label = QLabel("Quick Actions")
        title_label.setStyleSheet("font-weight: bold; font-size: 12px; color: #58a6ff;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        
        close_btn = QPushButton("×")
        close_btn.setMaximumWidth(24)
        close_btn.setMaximumHeight(24)
        close_btn.setStyleSheet("background: transparent; color: #c9d1d9; border: none;")
        close_btn.clicked.connect(self.hide)
        title_layout.addWidget(close_btn)
        layout.addLayout(title_layout)
        
        # Status labels
        self.mode_label = QLabel()
        self.mode_label.setStyleSheet("color: #c9d1d9; font-size: 11px;")
        layout.addWidget(self.mode_label)
        
        self.profile_label = QLabel()
        self.profile_label.setStyleSheet("color: #c9d1d9; font-size: 11px;")
        layout.addWidget(self.profile_label)
        
        self.mute_label = QLabel()
        self.mute_label.setStyleSheet("color: #c9d1d9; font-size: 11px;")
        layout.addWidget(self.mute_label)
        
        self.volume_label = QLabel()
        self.volume_label.setStyleSheet("color: #c9d1d9; font-size: 11px;")
        layout.addWidget(self.volume_label)
        
        layout.addStretch()
        
        self.setLayout(layout)
        self.setStyleSheet("""
            QWidget {
                background-color: #0d1117;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 8px;
            }
        """)
        self.setFixedSize(250, 150)
        
        # Position in top-right corner
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 270, 50)
    
    def setup_timers(self):
        """Setup update timers"""
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_status)
        self.update_timer.start(200)
    
    def update_status(self):
        """Update status indicators"""
        global activation_mode, current_profile, mute_held, mute_toggled, smoothed_volume
        
        with lock:
            mode = activation_mode
            prof = current_profile or "None"
            muted = mute_held or mute_toggled
            volume = smoothed_volume
        
        self.mode_label.setText(f"Mode: {mode.upper()}")
        self.profile_label.setText(f"Profile: {prof}")
        self.mute_label.setText(f"Muted: {'YES' if muted else 'NO'}")
        self.volume_label.setText(f"Level: {volume*100:.0f}%")
    
    def closeEvent(self, event):
        """Handle close"""
        self.update_timer.stop()
        event.accept()
