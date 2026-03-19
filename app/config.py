"""
Configuration, constants, and default settings
"""
import os
import logging
from threading import Lock

# ============= LOGGING SETUP =============

logger = logging.getLogger("ptt_app")

def setup_logging():
    """Initialize logging system"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


# ============= THREAD SAFETY =============

lock = Lock()
log_lock = Lock()


# ============= GLOBAL STATE =============

# Audio state
current_volume = 0.0
smoothed_volume = 0.0
max_volume_seen = 0.0
last_real_audio_time = 0.0

# PTT/Activation state
ptt_key = "v"
activation_mode = "ptt"
key_held = False
toggle_active = False
last_voice_time = 0.0

# Mute state
mute_key = "m"
mute_mode = "push"
mute_held = False
mute_toggled = False

# System mute state
system_mute_key = None
system_mute_mode = "push"
system_mute_held = False
system_mute_enabled = False

# Profile state
current_profile = None
default_profile = None
selected_targets = []

# Audio settings (loaded from current profile)
audio_settings = {}

# Microphone selection (sounddevice device index)
selected_mic_device_id = None

# Application state
running = False
stream = None
pycaw_available = False

# Log buffer
log_buffer = []


# ============= THEME COLORS =============

DEFAULT_THEME = {
    "bg_dark": "#0d1117",
    "bg_light": "#161b22",
    "waveform_cyan": "#00d9ff",
    "waveform_blue": "#58a6ff",
    "waveform_pink": "#f85149",
    "threshold_color": "#3fb950",
    "border_color": "#30363d",
    "accent_cyan": "#00d9ff",
    "accent_pink": "#f85149",
}


# ============= AUDIO SETTINGS =============

AUDIO_EVENTS = [
    "mute_on",
    "mute_off",
    "ptt_on",
    "ptt_off",
    "voice_active",
    "voice_inactive",
]

BEEP_TYPES = ["single", "short", "long", "double", "triple"]

DEFAULT_AUDIO_SETTINGS = {
    "enabled": True,
    "master_volume": 100,
    "event_listeners": [
        {
            "id": "default_mute_on",
            "events": ["mute_on"],
            "pitch": 1200,
            "duration": 100,
            "beep_type": "single",
            "volume": 80,
        },
        {
            "id": "default_mute_off",
            "events": ["mute_off"],
            "pitch": 800,
            "duration": 150,
            "beep_type": "single",
            "volume": 80,
        },
    ],
}


# ============= PATHS =============

def get_appdata_path():
    """Get the application data directory"""
    base = os.getenv("LOCALAPPDATA")
    if not base:
        # Fallback for non-Windows systems
        base = os.path.expanduser("~/.automatic_ptt")
    folder = os.path.join(base, "automatic_ptt")
    os.makedirs(folder, exist_ok=True)
    return folder


def get_config_path():
    """Get the config file path"""
    folder = get_appdata_path()
    return os.path.join(folder, "config.json")


def get_profiles_path():
    """Get the profiles file path"""
    folder = get_appdata_path()
    return os.path.join(folder, "profiles.json")


def get_modules_path():
    """Get the modules directory path"""
    folder = get_appdata_path()
    modules_folder = os.path.join(folder, "modules")
    os.makedirs(modules_folder, exist_ok=True)
    return modules_folder


def get_exports_path():
    """Get the exports directory path for profile exports"""
    folder = get_appdata_path()
    exports_folder = os.path.join(folder, "exports")
    os.makedirs(exports_folder, exist_ok=True)
    return exports_folder


# ============= DEFAULTS =============

DEFAULT_PROFILE_DATA = {
    "ptt_key": "v",
    "activation_mode": "ptt",
    "mute_key": "m",
    "mute_mode": "push",
    "threshold": 45,
    "release_delay": 500,
    "mic_device_id": None,
    "system_mute_key": None,
    "system_mute_mode": "push",
    "audio_settings": DEFAULT_AUDIO_SETTINGS.copy(),
    "targets": ["Focused Window"],
}

# ============= SLIDER STATE =============
# These are synced from UI sliders but stored here for background access

threshold = 45  # 0-100
release_delay = 500  # milliseconds
