"""
Audio playback and sound event handling
"""
import threading
import time
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QSlider, QComboBox, QPushButton, QCheckBox
from PySide6.QtCore import Qt

from app.config import AUDIO_EVENTS, BEEP_TYPES, DEFAULT_AUDIO_SETTINGS, current_profile, log_lock
from app.utils.helpers import log


def play_custom_beep(pitch, duration, beep_type, volume):
    """
    Play a customized beep sound
    
    Args:
        pitch: Frequency in Hz (e.g., 800, 1200)
        duration: Duration in milliseconds (e.g., 100, 150)
        beep_type: "single", "short", "long", "double", "triple"
        volume: Volume 0-100
    """
    try:
        import winsound
        
        # Calculate adjusted duration based on type
        if beep_type == "short":
            beep_duration = max(50, duration // 2)
        elif beep_type == "long":
            beep_duration = duration * 2
        else:  # single, double, triple
            beep_duration = duration
        
        # Build pattern: list of (is_beep, duration_ms) tuples
        if beep_type == "single":
            pattern = [(True, beep_duration)]
        elif beep_type == "double":
            pattern = [(True, beep_duration), (False, 100), (True, beep_duration)]
        elif beep_type == "triple":
            pattern = [
                (True, beep_duration),
                (False, 100),
                (True, beep_duration),
                (False, 100),
                (True, beep_duration),
            ]
        else:
            pattern = [(True, beep_duration)]
        
        # Play pattern
        for is_beep, dur in pattern:
            if is_beep:
                winsound.Beep(int(pitch), int(dur))
            else:
                time.sleep(dur / 1000.0)
                
    except Exception as e:
        log(f"Error playing beep: {e}", "ERROR")


def play_event_sound(event_name, profile_name=None):
    """
    Play all configured sounds for a specific event
    
    Args:
        event_name: Event type (e.g., "mute_on", "ptt_off")
        profile_name: Profile to use (defaults to current_profile)
    """
    global current_profile
    
    if profile_name is None:
        profile_name = current_profile
    
    if not profile_name:
        return  # No profile loaded
    
    try:
        # Get audio settings for profile
        audio_settings = load_profile_audio_settings(profile_name)
        
        if not audio_settings.get("enabled", True):
            return  # Audio disabled
        
        master_volume = audio_settings.get("master_volume", 100) / 100.0
        
        # Find all listeners for this event
        for listener in audio_settings.get("event_listeners", []):
            if event_name in listener.get("events", []):
                # Play this listener's sound in background
                pitch = listener.get("pitch", 1000)
                duration = listener.get("duration", 100)
                beep_type = listener.get("beep_type", "single")
                volume = listener.get("volume", 80)
                
                # Apply master volume
                effective_volume = volume * master_volume
                
                # Play in background thread
                threading.Thread(
                    target=play_custom_beep,
                    args=(pitch, duration, beep_type, effective_volume),
                    daemon=True,
                ).start()
    except Exception as e:
        log(f"Error playing event sound: {e}", "ERROR")


def load_profile_audio_settings(profile_name):
    """Load audio settings for a profile"""
    from core.profiles import all_profiles
    
    if profile_name in all_profiles:
        return all_profiles[profile_name].get("audio_settings", DEFAULT_AUDIO_SETTINGS.copy())
    
    return DEFAULT_AUDIO_SETTINGS.copy()


def save_profile_audio_settings(profile_name, audio_settings):
    """Save audio settings for a profile"""
    from core.profiles import all_profiles, save_profiles
    
    if profile_name in all_profiles:
        all_profiles[profile_name]["audio_settings"] = audio_settings
        save_profiles()


def reset_profile_audio_to_default(profile_name):
    """Reset a profile's audio settings to defaults"""
    save_profile_audio_settings(profile_name, DEFAULT_AUDIO_SETTINGS.copy())


# ============= AUDIO EVENT LISTENER WIDGET =============

class AudioEventListenerWidget(QWidget):
    """Widget for configuring a single audio event listener"""
    
    def __init__(self, listener_id, initial_data=None):
        super().__init__()
        self.listener_id = listener_id
        self.data = initial_data or {
            "id": listener_id,
            "events": ["mute_on"],
            "pitch": 1000,
            "duration": 100,
            "beep_type": "single",
            "volume": 80,
        }
        self.setup_ui()
    
    def setup_ui(self):
        """Setup listener widget UI"""
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Header with ID and delete button
        header_layout = QHBoxLayout()
        id_label = QLabel(f"Listener: {self.listener_id}")
        id_label.setStyleSheet("font-weight: bold; color: #58a6ff; font-size: 11px;")
        header_layout.addWidget(id_label)
        header_layout.addStretch()
        
        delete_btn = QPushButton("Delete")
        delete_btn.setMaximumWidth(60)
        delete_btn.setMaximumHeight(24)
        delete_btn.clicked.connect(self.deleteLater)
        header_layout.addWidget(delete_btn)
        layout.addLayout(header_layout)
        
        # Events selection (multi-select checkboxes)
        events_label = QLabel("Trigger Events:")
        events_label.setStyleSheet("color: #b0b0c0; font-size: 11px;")
        layout.addWidget(events_label)
        
        self.event_checkboxes = {}
        for event in AUDIO_EVENTS:
            cb = QCheckBox(event)
            cb.setChecked(event in self.data.get("events", []))
            self.event_checkboxes[event] = cb
            layout.addWidget(cb)
        
        layout.addSpacing(8)
        
        # Pitch
        pitch_layout = QHBoxLayout()
        pitch_layout.addWidget(QLabel("Pitch (Hz):"))
        self.pitch_spinbox = QSpinBox()
        self.pitch_spinbox.setRange(100, 4000)
        self.pitch_spinbox.setValue(self.data.get("pitch", 1000))
        pitch_layout.addWidget(self.pitch_spinbox)
        pitch_layout.addStretch()
        layout.addLayout(pitch_layout)
        
        # Duration
        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("Duration (ms):"))
        self.duration_spinbox = QSpinBox()
        self.duration_spinbox.setRange(10, 1000)
        self.duration_spinbox.setValue(self.data.get("duration", 100))
        duration_layout.addWidget(self.duration_spinbox)
        duration_layout.addStretch()
        layout.addLayout(duration_layout)
        
        # Beep Type
        beep_type_layout = QHBoxLayout()
        beep_type_layout.addWidget(QLabel("Beep Type:"))
        self.beep_type_combo = QComboBox()
        self.beep_type_combo.addItems(BEEP_TYPES)
        self.beep_type_combo.setCurrentText(self.data.get("beep_type", "single"))
        beep_type_layout.addWidget(self.beep_type_combo)
        beep_type_layout.addStretch()
        layout.addLayout(beep_type_layout)
        
        # Volume
        volume_layout = QHBoxLayout()
        volume_layout.addWidget(QLabel("Volume:"))
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.data.get("volume", 80))
        volume_layout.addWidget(self.volume_slider)
        self.volume_label = QLabel(f"{self.data.get('volume', 80)}%")
        self.volume_label.setMaximumWidth(40)
        self.volume_slider.valueChanged.connect(
            lambda v: self.volume_label.setText(f"{v}%")
        )
        volume_layout.addWidget(self.volume_label)
        layout.addLayout(volume_layout)
        
        # Test button
        test_btn = QPushButton("Test Sound")
        test_btn.setMaximumWidth(100)
        test_btn.clicked.connect(self.test_sound)
        layout.addWidget(test_btn)
        
        layout.addStretch()
        
        self.setLayout(layout)
    
    def test_sound(self):
        """Test the configured sound"""
        play_custom_beep(
            self.pitch_spinbox.value(),
            self.duration_spinbox.value(),
            self.beep_type_combo.currentText(),
            self.volume_slider.value(),
        )
    
    def get_data(self):
        """Get current listener configuration"""
        return {
            "id": self.listener_id,
            "events": [e for e, cb in self.event_checkboxes.items() if cb.isChecked()],
            "pitch": self.pitch_spinbox.value(),
            "duration": self.duration_spinbox.value(),
            "beep_type": self.beep_type_combo.currentText(),
            "volume": self.volume_slider.value(),
        }
