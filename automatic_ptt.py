import os
import json
import sys
import sounddevice as sd
import numpy as np
import time
import threading
import math
import subprocess

try:
    import pygetwindow as gw
except ImportError:
    gw = None

try:
    import psutil
except ImportError:
    psutil = None

try:
    from pycaw.pycaw import IAudioEndpointVolume
    pycaw_available = True
except ImportError:
    pycaw_available = False

from pynput.keyboard import Controller, KeyCode, Key
from pynput import keyboard as kb_listener

from PySide6.QtCore import (
    Qt, QTimer, QRect, QPointF
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QSlider, QTabWidget, QTextEdit,
    QSystemTrayIcon, QSplitter, QInputDialog, QListWidget, QListWidgetItem,
    QColorDialog, QSpinBox, QSizePolicy, QScrollArea
)
from PySide6.QtGui import (
    QIcon, QPixmap, QLinearGradient, QPainter, QColor,
    QPen, QKeySequence, QFont, QPolygonF, QPalette
)

lock = threading.Lock()

keyboard = Controller()

running = False
key_held = False
toggle_active = False  # For tap-to-talk mode
mute_toggled = False   # For toggle mute mode
last_voice_time = 0
max_volume_seen = 0.01
current_volume = 0
smoothed_volume = current_volume
stream = None
smoothing_factor = 0.2
last_real_audio_time = 0  # Track when we last received actual audio

mute_key = "m"
mute_held = False
mute_mode = "push"  # "push" or "toggle"
system_mute_key = None
system_mute_held = False
system_mute_mode = "push"
system_mute_enabled = False  # Whether system mute is actively being used
ppt_key = "v"
activation_mode = "ppt"
current_profile = None
default_profile = None  # The profile to auto-load on startup
selected_targets = []  # List of target window/process names to send keys to

# Default theme colors - Modern, sleek palette
DEFAULT_THEME = {
    "bg_dark": "#0d1117",
    "bg_light": "#161b22",
    "accent_cyan": "#58a6ff",
    "accent_pink": "#f85149",
    "waveform_cyan": "#58a6ff",
    "waveform_blue": "#79c0ff",
    "waveform_pink": "#f85149",
    "threshold_color": "#58a6ff",
    "border_color": "#3a3a4a"
}

current_theme = DEFAULT_THEME.copy()

# ============= DEBUG LOGGER ================

log_buffer = []
log_lock = threading.Lock()

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    
    with log_lock:
        log_buffer.append(line)
        
        if len(log_buffer) > 500:
            log_buffer.pop(0)

# ============= WINDOW/PROCESS ENUMERATION ================

def get_available_targets():
    """Get list of available windows and processes to target"""
    targets = ["Focused Window"]  # Always available
    
    # Get open windows
    if gw:
        try:
            windows = gw.getAllWindows()
            for window in windows:
                if window.title and len(window.title) > 0:
                    targets.append(f"[Window] {window.title[:50]}")
        except Exception as e:
            log(f"Error enumerating windows: {e}")
    
    # Get running processes
    if psutil:
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    # Filter for common applications (exe files)
                    if proc.name().endswith('.exe'):
                        targets.append(f"[Process] {proc.name()}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            log(f"Error enumerating processes: {e}")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_targets = []
    for target in targets:
        if target not in seen:
            seen.add(target)
            unique_targets.append(target)
    
    return unique_targets

def set_system_mic_mute(mute_state):
    """Attempt to mute/unmute system microphone using Windows audio APIs"""
    global system_mute_enabled
    
    if not pycaw_available:
        log("System mute requires pycaw library. Install with: pip install pycaw")
        return False
    
    try:
        from ctypes import cast, POINTER
        from comtypes import CoCreateInstance, CLSCTX_ALL
        from pycaw.pycaw import IAudioEndpointVolume, IMMDeviceEnumerator
        
        # Get the device enumerator
        device_enumerator = CoCreateInstance(
            IMMDeviceEnumerator,
            interface=IMMDeviceEnumerator,
            clsctx=CLSCTX_ALL
        )
        
        # Get the default capture device (microphone) - EDataFlow.eCapture (2)
        mic = device_enumerator.GetDefaultAudioEndpoint(2, 1)
        
        # Activate the audio interface
        audio_interface = mic.Activate(
            IAudioEndpointVolume._iid_,
            clsctx=CLSCTX_ALL
        )
        volume = cast(audio_interface, POINTER(IAudioEndpointVolume))
        
        # Set mute state (True = muted, False = unmuted)
        volume.SetMute(mute_state, None)
        system_mute_enabled = True
        log(f"System microphone mute: {'ON' if mute_state else 'OFF'}")
        return True
        
    except Exception as e:
        log(f"Error setting system mute: {e}")
        system_mute_enabled = False
        return False
    """Attempt to focus a specific window or process"""
    if target_name == "Focused Window":
        # Already focused, no need to do anything
        return True
    
    try:
        if target_name.startswith("[Window]"):
            # Window target
            window_title = target_name.replace("[Window] ", "")
            if gw:
                windows = gw.getWindowsWithTitle(window_title)
                if windows:
                    windows[0].activate()
                    return True
        
        elif target_name.startswith("[Process]"):
            # Process target
            process_name = target_name.replace("[Process] ", "")
            if psutil:
                for proc in psutil.process_iter(['pid', 'name']):
                    try:
                        if proc.name() == process_name:
                            # Found the process, try to focus it
                            # This is limited on Windows without additional APIs
                            return True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
    except Exception as e:
        log(f"Error focusing target {target_name}: {e}")
        return False
    
    return False

# ============= APP ICON ================

def create_studio_mic_icon():
    """Create a modern studio microphone icon for the tray"""
    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("transparent"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    # Mic body (upper rounded part)
    mic_head_x = size * 0.35
    mic_head_y = size * 0.15
    mic_head_w = size * 0.3
    mic_head_h = size * 0.4

    # Gradient for mic head - metallic look
    head_gradient = QLinearGradient(mic_head_x, mic_head_y, mic_head_x, mic_head_y + mic_head_h)
    head_gradient.setColorAt(0.0, QColor("#58a6ff"))      # Blue highlight
    head_gradient.setColorAt(0.5, QColor("#4a9eff"))      # Mid-tone blue
    head_gradient.setColorAt(1.0, QColor("#1f6feb"))      # Dark blue shadow

    painter.setBrush(head_gradient)
    painter.setPen(QPen(QColor("#30363d"), 1))
    painter.drawRoundedRect(
        int(mic_head_x), int(mic_head_y),
        int(mic_head_w), int(mic_head_h),
        int(mic_head_w * 0.25), int(mic_head_w * 0.25)
    )

    # Grille lines on microphone head - vertical
    grille_color = QColor("#0d1117")
    grille_color.setAlpha(180)
    grille_pen = QPen(grille_color, 2)
    painter.setPen(grille_pen)

    grille_spacing = mic_head_w / 5
    for i in range(1, 5):
        grille_x = mic_head_x + grille_spacing * i
        painter.drawLine(
            int(grille_x),
            int(mic_head_y + mic_head_h * 0.1),
            int(grille_x),
            int(mic_head_y + mic_head_h * 0.9)
        )

    # Grille lines - horizontal
    grille_h_spacing = mic_head_h / 8
    for i in range(1, 8):
        grille_y = mic_head_y + grille_h_spacing * i
        painter.drawLine(
            int(mic_head_x + mic_head_w * 0.1),
            int(grille_y),
            int(mic_head_x + mic_head_w * 0.9),
            int(grille_y)
        )

    # Mic stand connector (tapered neck)
    neck_top_w = mic_head_w * 0.4
    neck_bot_w = mic_head_w * 0.6
    neck_top_x = mic_head_x + (mic_head_w - neck_top_w) / 2
    neck_bot_x = mic_head_x + (mic_head_w - neck_bot_w) / 2
    neck_y = mic_head_y + mic_head_h
    neck_h = size * 0.15

    # Create polygon for tapered neck
    neck_points = [
        QPointF(neck_top_x, neck_y),
        QPointF(neck_top_x + neck_top_w, neck_y),
        QPointF(neck_bot_x + neck_bot_w, neck_y + neck_h),
        QPointF(neck_bot_x, neck_y + neck_h),
    ]
    neck_poly = QPolygonF(neck_points)

    neck_gradient = QLinearGradient(0, neck_y, 0, neck_y + neck_h)
    neck_gradient.setColorAt(0.0, QColor("#4a9eff"))
    neck_gradient.setColorAt(1.0, QColor("#1f6feb"))

    painter.setBrush(neck_gradient)
    painter.setPen(QPen(QColor("#30363d"), 1))
    painter.drawPolygon(neck_poly)

    # Mic stand/mount (lower rounded part)
    mount_x = size * 0.3
    mount_y = neck_y + neck_h
    mount_w = size * 0.4
    mount_h = size * 0.25

    mount_gradient = QLinearGradient(mount_x, mount_y, mount_x, mount_y + mount_h)
    mount_gradient.setColorAt(0.0, QColor("#1f6feb"))
    mount_gradient.setColorAt(0.5, QColor("#1a5fd9"))
    mount_gradient.setColorAt(1.0, QColor("#1546b3"))

    painter.setBrush(mount_gradient)
    painter.setPen(QPen(QColor("#30363d"), 1))
    painter.drawRoundedRect(
        int(mount_x), int(mount_y),
        int(mount_w), int(mount_h),
        int(mount_w * 0.15), int(mount_w * 0.15)
    )

    # Mount details - horizontal accent line
    line_y = mount_y + mount_h * 0.5
    accent_color = QColor("#58a6ff")
    accent_color.setAlpha(150)
    painter.setPen(QPen(accent_color, 2))
    painter.drawLine(
        int(mount_x + mount_w * 0.15),
        int(line_y),
        int(mount_x + mount_w * 0.85),
        int(line_y)
    )

    # Optional: Add a subtle glow effect around the whole mic
    glow_color = QColor("#58a6ff")
    glow_color.setAlpha(40)
    painter.setPen(QPen(glow_color, 3))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(
        int(size * 0.2), int(size * 0.1),
        int(size * 0.6), int(size * 0.8),
        15, 15
    )

    painter.end()
    return QIcon(pixmap)

# ============= PROFILES ================

def get_profiles_path():
    """Get profiles file path"""
    base = os.getenv("LOCALAPPDATA")
    folder = os.path.join(base, "automatic_ppt")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "profiles.json")

def load_all_profiles():
    """Load all profiles from file"""
    path = get_profiles_path()
    if not os.path.exists(path):
        return {}
    
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        log(f"Failed to load profiles: {e}")
        return {}

def save_all_profiles(profiles):
    """Save all profiles to file"""
    try:
        with open(get_profiles_path(), "w") as f:
            json.dump(profiles, f, indent=4)
    except Exception as e:
        log(f"Failed to save profiles: {e}")

def create_profile_from_window(window, profile_name):
    """Create a profile dict from current window settings"""
    return {
        "name": profile_name,
        "ppt_key": window.ppt_key,
        "mute_key": mute_key,
        "mute_mode": mute_mode,
        "system_mute_key": system_mute_key,
        "system_mute_mode": system_mute_mode,
        "threshold": window.threshold_slider.value(),
        "delay": window.delay_slider.value(),
        "fps": window.fps_slider.value(),
        "activation_mode": window.activation_mode,
        "mic_id": window.mic_devices[window.mic_dropdown.currentIndex()][0] if window.mic_devices and window.mic_dropdown.currentIndex() >= 0 else None,
        "theme": window.current_theme.copy(),
        "targets": list(selected_targets)
    }

def apply_profile_to_window(window, profile):
    """Apply a profile's settings to the window"""
    global mute_key, activation_mode, ppt_key, mute_mode, current_theme, selected_targets, system_mute_key, system_mute_mode
    
    ppt_key = profile.get("ppt_key", "v")
    window.ppt_key = ppt_key
    window.ppt_label.setText(window.ppt_key)
    
    mute_key = profile.get("mute_key", "m")
    window.mute_label.setText(mute_key)
    
    mute_mode = profile.get("mute_mode", "push")
    window.mute_mode_dropdown.setCurrentText(mute_mode)
    
    system_mute_key = profile.get("system_mute_key")
    system_mute_mode = profile.get("system_mute_mode", "push")
    if system_mute_key and hasattr(window, "system_mute_label"):
        window.system_mute_label.setText(system_mute_key)
        window.system_mute_mode_dropdown.setCurrentText(system_mute_mode)
    
    window.threshold_slider.setValue(profile.get("threshold", 20))
    window.delay_slider.setValue(profile.get("delay", 300))
    window.fps_slider.setValue(profile.get("fps", 45))
    
    activation_mode = profile.get("activation_mode", "ppt")
    window.activation_mode = activation_mode
    window.mode_dropdown.setCurrentText(activation_mode)
    
    # Apply theme
    theme = profile.get("theme", DEFAULT_THEME)
    current_theme = theme
    window.current_theme = theme.copy()
    window.apply_theme()
    
    # Apply targets
    selected_targets = profile.get("targets", [])
    if hasattr(window, "refresh_targets_list"):
        window.refresh_targets_list()
    
    saved_id = profile.get("mic_id")
    if saved_id and window.mic_devices:
        for i, (device_id, name) in enumerate(window.mic_devices):
            if device_id == saved_id:
                window.mic_dropdown.setCurrentIndex(i)
                break

# ============= JSON SETTINGS ================

def get_config_path():
    """Get setting file path"""
    base = os.getenv("LOCALAPPDATA")
    folder = os.path.join(base, "automatic_ppt")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "config.json")

def save_settings(window):
    """Save settings to JSON and update current profile if loaded"""
    global current_profile
    
    if window.mic_devices and window.mic_dropdown.currentIndex() >= 0:
        mic_id = window.mic_devices[window.mic_dropdown.currentIndex()][0]
    else:
        mic_id = None
    
    config = {
        "ppt_key": window.ppt_key,
        "mute_key": mute_key,
        "mute_mode": mute_mode,
        "system_mute_key": system_mute_key,
        "system_mute_mode": system_mute_mode,
        "threshold": window.threshold_slider.value(),
        "delay": window.delay_slider.value(),
        "fps": window.fps_slider.value(),
        "mic_id": mic_id,
        "activation_mode": window.activation_mode,
        "current_profile": current_profile,
        "default_profile": default_profile,
        "theme": window.current_theme.copy()
    }

    with open(get_config_path(), "w") as f:
        json.dump(config, f, indent=4)

    # Also update the current profile if one is loaded
    if current_profile:
        profiles = load_all_profiles()
        if current_profile in profiles:
            profiles[current_profile] = create_profile_from_window(window, current_profile)
            save_all_profiles(profiles)

def load_settings(window):
    """Load settings from JSON"""
    global mute_key, activation_mode, ppt_key, mute_mode, current_profile, current_theme, default_profile, system_mute_key, system_mute_mode
    
    path = get_config_path()

    if not os.path.exists(path):
        # Set first profile as default if it exists
        profiles = load_all_profiles()
        if profiles:
            default_profile = list(profiles.keys())[0]
        save_settings(window)
        window.update_config_view()
        return

    try:
        with open(path, "r") as f:
            config = json.load(f)

        ppt_key = config.get("ppt_key", "v")
        window.ppt_key = ppt_key
        window.ppt_label.setText(window.ppt_key)

        mute_key = config.get("mute_key", "m")
        window.mute_label.setText(mute_key)
        
        mute_mode = config.get("mute_mode", "push")
        window.mute_mode_dropdown.setCurrentText(mute_mode)

        system_mute_key = config.get("system_mute_key")
        system_mute_mode = config.get("system_mute_mode", "push")
        if hasattr(window, "system_mute_label") and system_mute_key:
            window.system_mute_label.setText(system_mute_key)
        if hasattr(window, "system_mute_mode_dropdown") and system_mute_mode:
            window.system_mute_mode_dropdown.setCurrentText(system_mute_mode)

        window.threshold_slider.setValue(config.get("threshold", 20))
        window.delay_slider.setValue(config.get("delay", 300))
        window.fps_slider.setValue(config.get("fps", 45))

        activation_mode = config.get("activation_mode", "ppt")
        window.activation_mode = activation_mode
        window.mode_dropdown.setCurrentText(activation_mode)
        
        current_profile = config.get("current_profile")
        default_profile = config.get("default_profile")
        
        # Set first profile as default if none set
        profiles = load_all_profiles()
        if not default_profile and profiles:
            default_profile = list(profiles.keys())[0]
        
        current_theme = config.get("theme", DEFAULT_THEME)
        window.current_theme = current_theme.copy()

        saved_id = config.get("mic_id", None)
        
        if saved_id is not None:
            for i, (device_id, name) in enumerate(window.mic_devices):
                if device_id == saved_id:
                    window.mic_dropdown.setCurrentIndex(i)
                    break

    except Exception as e:
        log(f"Failed to load config: {e}")

# ============= MIC DETECTION ================

def is_working_mic(index):
    """Check if a microphone is working"""
    try:
        with sd.InputStream(device=index, channels=1, samplerate=44100) as s:
            data, _ = s.read(1024)
            volume = np.sqrt(np.mean(data ** 2))
            return volume >= 0
    except Exception:
        return False


def get_valid_mics():
    """Get list of valid working microphones"""
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


# ============= AUDIO CALLBACK ================

def audio_callback(indata, frames, time_info, status):
    """Audio stream callback"""
    global current_volume, max_volume_seen, last_real_audio_time
    
    with lock:
        if mute_held:
            current_volume = 0
            return

    volume = np.sqrt(np.mean(indata ** 2))

    with lock:
        max_volume_seen = max(max_volume_seen * 0.995, volume, 0.01)
        current_volume = volume / max_volume_seen
        
        # Track when we last received real audio input
        if volume > 0.005:
            last_real_audio_time = time.time()
        
    if volume > 0.5:
        log(f"Loud input detected: {volume:.2f}")

# ============= ACTIVATION MODE HANDLERS ================

def on_press(key):
    """Handle key press - for PTT and Tap modes"""
    global key_held, toggle_active, activation_mode, mute_held, mute_toggled, mute_mode, ppt_key, system_mute_key, system_mute_held, system_mute_mode

    try:
        with lock:
            # Check for system mute key first
            if system_mute_key:
                if hasattr(key, "char") and key.char:
                    if key.char.lower() == system_mute_key:
                        if system_mute_mode == "toggle":
                            system_mute_held = not system_mute_held  # Toggle mute state
                        else:
                            system_mute_held = True  # Push to mute
                else:
                    key_str = str(key).replace("Key.", "")
                    if key_str == system_mute_key:
                        if system_mute_mode == "toggle":
                            system_mute_held = not system_mute_held
                        else:
                            system_mute_held = True
            
            # Check for regular mute key
            if hasattr(key, "char") and key.char:
                if key.char.lower() == mute_key:
                    if mute_mode == "toggle":
                        mute_toggled = not mute_toggled
                    else:
                        mute_held = True
                # Check for PTT key
                elif key.char.lower() == ppt_key:
                    if activation_mode == "ppt":
                        key_held = True
                    elif activation_mode == "tap":
                        toggle_active = not toggle_active
            else:
                key_str = str(key).replace("Key.", "")
                if key_str == mute_key:
                    if mute_mode == "toggle":
                        mute_toggled = not mute_toggled
                    else:
                        mute_held = True
                elif key_str == ppt_key:
                    if activation_mode == "ppt":
                        key_held = True
                    elif activation_mode == "tap":
                        toggle_active = not toggle_active
    except:
        pass


def on_release(key):
    """Handle key release - for PTT mode and push-to-mute"""
    global key_held, mute_held, activation_mode, ppt_key, system_mute_key, system_mute_held, system_mute_mode

    try:
        with lock:
            # Check for system mute key release (only for push mode)
            if system_mute_key and system_mute_mode == "push":
                if hasattr(key, "char") and key.char:
                    if key.char.lower() == system_mute_key:
                        system_mute_held = False
                else:
                    key_str = str(key).replace("Key.", "")
                    if key_str == system_mute_key:
                        system_mute_held = False
            
            # Check for regular mute key release (only for push mode)
            if hasattr(key, "char") and key.char:
                if key.char.lower() == mute_key and mute_mode == "push":
                    mute_held = False
                elif key.char.lower() == ppt_key and activation_mode == "ppt":
                    key_held = False
            else:
                key_str = str(key).replace("Key.", "")
                if key_str == mute_key and mute_mode == "push":
                    mute_held = False
                elif key_str == ppt_key and activation_mode == "ppt":
                    key_held = False
    except:
        pass


listener = kb_listener.Listener(on_press=on_press, on_release=on_release)
listener.start()

# ============= MIC LOOP ================

def get_key_obj(key_str):
    """Convert string to Key object"""
    try:
        if len(key_str) == 1:
            return KeyCode.from_char(key_str)
        
        key_map = {
            "shift": Key.shift,
            "ctrl": Key.ctrl_l,
            "control": Key.ctrl_l,
            "alt": Key.alt_l,
            "space": Key.space,
            "enter": Key.enter,
            "tab": Key.tab,
            "esc": Key.esc
        }

        return key_map.get(key_str, KeyCode.from_char("v"))

    except:
        return KeyCode.from_char("v")

def mic_loop(window):
    """Main microphone loop (runs in separate thread)"""
    global key_held, last_voice_time, smoothed_volume, toggle_active, activation_mode, mute_held, mute_toggled, system_mute_held, system_mute_mode

    smoothing_factor = 0.5
    current_system_mute_state = False  # Track system mute state to avoid repeated calls

    while running:
        with lock:
            volume = float(current_volume)
            is_muted = mute_held or mute_toggled
            mode = activation_mode
            tap_state = toggle_active
            sys_mute = system_mute_held

        # Handle system mute
        if system_mute_key:
            if system_mute_mode == "toggle":
                # For toggle mode, only apply once when sys_mute changes state
                desired_mute = sys_mute
            else:
                # For push mode, mute when key is held
                desired_mute = sys_mute
            
            if desired_mute != current_system_mute_state:
                set_system_mic_mute(desired_mute)
                current_system_mute_state = desired_mute

        smoothed_volume = smoothing_factor * volume + (1 - smoothing_factor) * smoothed_volume
        if smoothed_volume < 0.01:
            smoothed_volume = 0

        threshold_value = window.threshold_slider.value() / 100
        release_delay = window.delay_slider.value() / 1000

        if is_muted:
            if key_held:
                keyboard.release(get_key_obj(window.ppt_key))
                key_held = False
            smoothed_volume = 0
        
        elif mode == "ppt":
            if key_held and smoothed_volume > threshold_value:
                last_voice_time = time.time()
            elif key_held and (time.time() - last_voice_time > release_delay):
                keyboard.release(get_key_obj(window.ppt_key))
                key_held = False

        elif mode == "tap":
            if tap_state:
                if smoothed_volume > threshold_value:
                    last_voice_time = time.time()
                    if not key_held:
                        keyboard.press(get_key_obj(window.ppt_key))
                        key_held = True
                else:
                    if key_held and (time.time() - last_voice_time > release_delay):
                        keyboard.release(get_key_obj(window.ppt_key))
                        key_held = False
            else:
                if key_held:
                    keyboard.release(get_key_obj(window.ppt_key))
                    key_held = False

        elif mode == "voice_only":
            if smoothed_volume > threshold_value:
                last_voice_time = time.time()
                if not key_held:
                    keyboard.press(get_key_obj(window.ppt_key))
                    key_held = True
            else:
                if key_held and (time.time() - last_voice_time > release_delay):
                    keyboard.release(get_key_obj(window.ppt_key))
                    key_held = False

        elif mode == "always_on":
            if not key_held:
                keyboard.press(get_key_obj(window.ppt_key))
                key_held = True

        if running:
            state = "idle"
            if is_muted:
                state = "muted"
            elif key_held:
                state = "transmitting"
            elif smoothed_volume > 0.1:
                state = "voice_detected"
            
            log(f"[{mode.upper()}] {state}, vol={volume:.3f}, mute={is_muted}")

        time.sleep(0.01)


# ============= MAIN WINDOW ================

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
        self.setMinimumHeight(50)
        
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.animate)
        self.animation_timer.start(22)  # 45 FPS default (1000/45 ≈ 22ms)

    def set_theme(self, theme):
        """Update theme colors"""
        self.theme = theme
        self.update()

    def animate(self):
        """Continuously update for animation"""
        self.animation_counter = (self.animation_counter + 1) % 100
        self.update()

    def setLevel(self, level):
        with lock:
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
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        # Create a rounded rect path for clipping
        from PySide6.QtGui import QPainterPath
        clip_path = QPainterPath()
        clip_path.addRoundedRect(0, 0, w, h, 12, 12)
        painter.setClipPath(clip_path)

        # Modern background with gradient
        bg_gradient = QLinearGradient(0, 0, w, h)
        bg_gradient.setColorAt(0.0, QColor(self.theme.get("bg_dark", "#1a1a2e")))
        bg_gradient.setColorAt(1.0, QColor(self.theme.get("bg_light", "#16213e")))
        painter.setBrush(bg_gradient)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, w, h, 12, 12)

        # Inner glow border with adjusted position to prevent clipping
        border_color = QColor(self.theme.get("border_color", "#30363d"))
        border_color.setAlpha(200)
        painter.setPen(QPen(border_color, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(1, 1, w-2, h-2, 11, 11)

        # Draw waveform bars (with margin for border)
        step = (w - 4) / len(self.history)
        baseline = h * 0.7
        
        for i, v in enumerate(self.history):
            x = 2 + i * step  # Account for 2px border
            display_v = max(0, min(v, 1.0))
            amplitude = display_v * (h * 0.5)
            
            # Color based on intensity using theme
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
            painter.drawLine(
                int(x),
                int(baseline),
                int(x),
                int(baseline - amplitude)
            )

        # Draw threshold line with pulsing animation
        threshold_y = int(baseline - self.threshold * h * 0.5)
        glow_intensity = (np.sin(self.animation_counter / 12.0) * 0.5 + 0.5)
        
        threshold_color = QColor(self.theme.get("threshold_color", "#58a6ff"))
        
        # Glow layers
        for glow in range(3, 0, -1):
            glow_alpha = int(30 * glow * glow_intensity)
            glow_col = QColor(threshold_color)
            glow_col.setAlpha(glow_alpha)
            glow_pen = QPen(glow_col)
            glow_pen.setWidth(4 + glow)
            painter.setPen(glow_pen)
            painter.drawLine(2, threshold_y, w-2, threshold_y)
        
        # Main line
        threshold_alpha = int(100 + glow_intensity * 155)
        threshold_col = QColor(threshold_color)
        threshold_col.setAlpha(threshold_alpha)
        painter.setPen(QPen(threshold_col, 2))
        painter.drawLine(2, threshold_y, w-2, threshold_y)
        
        # Label
        painter.setPen(QPen(threshold_col, 1))
        painter.setFont(QFont("Arial", 9))
        threshold_text = f"{int(self.threshold * 100)}%"
        painter.drawText(7, threshold_y - 5, threshold_text)

class MainWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.last_log_index = 0
        self._last_status_text = None
        self._last_ppt_active = None

        self.setWindowTitle("Mic → Push-To-Talk (Multi-Mode)")
        self.setMinimumSize(1600, 950)

        self.ppt_key = "v"
        self.activation_mode = "ppt"
        self.current_theme = DEFAULT_THEME.copy()

        layout = QVBoxLayout()

        # Profile indicator at top
        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel("Current Profile:"))
        self.profile_label = QLabel("None")
        self.profile_label.setStyleSheet("font-weight: bold; color: #58a6ff;")
        profile_layout.addWidget(self.profile_label)
        profile_layout.addStretch()
        layout.addLayout(profile_layout)

        tabs = QTabWidget()

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

        layout.addWidget(tabs)

        self.setLayout(layout)

        self.build_main_tab()
        self.build_profiles_tab()
        self.build_targets_tab()
        self.build_theme_tab()
        self.build_dev_tab()
        
        self.mic_devices = get_valid_mics()
        load_settings(self)
        self.update_profile_indicator()
        self.refresh_profiles_list()  # Refresh to show active profile highlighting

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_status)
        self.update_timer.start(100)

        self.debug_timer = QTimer()
        self.debug_timer.timeout.connect(self.update_debug)
        self.debug_timer.start(500)

    def update_profile_indicator(self):
        """Update the profile indicator label"""
        global current_profile
        if current_profile:
            self.profile_label.setText(current_profile)
        else:
            self.profile_label.setText("None")

    # -------- MAIN TAB --------

    def build_main_tab(self):
        # Create scroll area for main content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)

        # LEFT COLUMN - Settings
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 12, 0)
        left_layout.setSpacing(12)
        
        # Activation Mode Section
        mode_label = QLabel("Activation")
        mode_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #b0b0c0;")
        left_layout.addWidget(mode_label)
        
        self.mode_dropdown = QComboBox()
        self.mode_dropdown.addItems(["ppt", "tap", "voice_only", "always_on"])
        self.mode_dropdown.setMinimumWidth(220)
        self.mode_dropdown.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.mode_dropdown.currentTextChanged.connect(self.on_mode_changed)
        left_layout.addWidget(self.mode_dropdown)

        self.mode_description = QLabel("")
        self.mode_description.setStyleSheet("color: #808090; font-size: 11px; margin-top: -8px; margin-bottom: 8px;")
        left_layout.addWidget(self.mode_description)

        # Microphone Section
        mic_label = QLabel("Microphone")
        mic_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #b0b0c0; margin-top: 8px;")
        left_layout.addWidget(mic_label)
        
        self.mic_dropdown = QComboBox()
        self.mic_dropdown.setMinimumWidth(250)
        self.mic_dropdown.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        left_layout.addWidget(self.mic_dropdown)
        self.refresh_mics()
        self.mic_dropdown.currentIndexChanged.connect(lambda: save_settings(self))

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setMaximumHeight(32)
        refresh_btn.clicked.connect(self.refresh_mics)
        left_layout.addWidget(refresh_btn)

        # Keys Section
        keys_label = QLabel("Keys")
        keys_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #b0b0c0; margin-top: 12px;")
        left_layout.addWidget(keys_label)
        
        # Activation Key
        ptt_sublabel = QLabel("Activation Key")
        ptt_sublabel.setStyleSheet("color: #808090; font-size: 11px;")
        left_layout.addWidget(ptt_sublabel)
        
        ptt_layout = QHBoxLayout()
        ppt_layout_sp = QHBoxLayout()
        self.ppt_label = QLabel(self.ppt_key)
        self.ppt_label.setStyleSheet("padding: 6px 12px; background-color: #1a1a2e; border: 1px solid #3a3a4a; border-radius: 4px; min-width: 40px; text-align: center;")
        self.ppt_label.setAlignment(Qt.AlignCenter)
        ppt_layout_sp.addWidget(self.ppt_label)
        ppt_layout_sp.addStretch()
        
        change_key_btn = QPushButton("Change")
        change_key_btn.setMaximumWidth(80)
        change_key_btn.setMaximumHeight(32)
        change_key_btn.clicked.connect(self.capture_key)
        ppt_layout_sp.addWidget(change_key_btn)
        left_layout.addLayout(ppt_layout_sp)

        # Mute Key
        mute_sublabel = QLabel("Mute Key")
        mute_sublabel.setStyleSheet("color: #808090; font-size: 11px; margin-top: 8px;")
        left_layout.addWidget(mute_sublabel)
        
        mute_layout = QHBoxLayout()
        self.mute_label = QLabel(mute_key)
        self.mute_label.setStyleSheet("padding: 6px 12px; background-color: #1a1a2e; border: 1px solid #3a3a4a; border-radius: 4px; min-width: 40px; text-align: center;")
        self.mute_label.setAlignment(Qt.AlignCenter)
        mute_layout.addWidget(self.mute_label)
        mute_layout.addStretch()
        
        mute_btn = QPushButton("Change")
        mute_btn.setMaximumWidth(80)
        mute_btn.setMaximumHeight(32)
        mute_btn.clicked.connect(self.capture_mute_key)
        mute_layout.addWidget(mute_btn)
        left_layout.addLayout(mute_layout)

        # Mute Mode
        mode_sublabel = QLabel("Mute Mode")
        mode_sublabel.setStyleSheet("color: #808090; font-size: 11px; margin-top: 8px;")
        left_layout.addWidget(mode_sublabel)
        
        self.mute_mode_dropdown = QComboBox()
        self.mute_mode_dropdown.addItems(["push", "toggle"])
        self.mute_mode_dropdown.setMinimumWidth(220)
        self.mute_mode_dropdown.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.mute_mode_dropdown.currentTextChanged.connect(lambda: save_settings(self))
        left_layout.addWidget(self.mute_mode_dropdown)

        # System Mute Section
        sysmute_label = QLabel("System Mute (All Apps)")
        sysmute_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #b0b0c0; margin-top: 12px;")
        left_layout.addWidget(sysmute_label)
        
        sysmute_key_sublabel = QLabel("System Mute Key")
        sysmute_key_sublabel.setStyleSheet("color: #808090; font-size: 11px;")
        left_layout.addWidget(sysmute_key_sublabel)
        
        sysmute_layout = QHBoxLayout()
        self.system_mute_label = QLabel("None")
        self.system_mute_label.setStyleSheet("padding: 6px 12px; background-color: #1a1a2e; border: 1px solid #3a3a4a; border-radius: 4px; min-width: 40px; text-align: center;")
        self.system_mute_label.setAlignment(Qt.AlignCenter)
        sysmute_layout.addWidget(self.system_mute_label)
        sysmute_layout.addStretch()
        
        change_sysmute_btn = QPushButton("Set Key")
        change_sysmute_btn.setMaximumWidth(80)
        change_sysmute_btn.setMaximumHeight(32)
        change_sysmute_btn.clicked.connect(self.capture_system_mute_key)
        sysmute_layout.addWidget(change_sysmute_btn)
        left_layout.addLayout(sysmute_layout)
        
        # System Mute Mode
        sysmute_mode_sublabel = QLabel("System Mute Mode")
        sysmute_mode_sublabel.setStyleSheet("color: #808090; font-size: 11px; margin-top: 8px;")
        left_layout.addWidget(sysmute_mode_sublabel)
        
        self.system_mute_mode_dropdown = QComboBox()
        self.system_mute_mode_dropdown.addItems(["push", "toggle"])
        self.system_mute_mode_dropdown.setMinimumWidth(220)
        self.system_mute_mode_dropdown.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.system_mute_mode_dropdown.currentTextChanged.connect(lambda: save_settings(self))
        left_layout.addWidget(self.system_mute_mode_dropdown)
        
        # System mute info
        sysmute_info = QLabel("Mutes mic for all apps • Requires pycaw")
        sysmute_info.setStyleSheet("color: #606070; font-size: 10px; margin-top: 4px;")
        left_layout.addWidget(sysmute_info)

        # Sensitivity Section
        sens_label = QLabel("Sensitivity")
        sens_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #b0b0c0; margin-top: 12px;")
        left_layout.addWidget(sens_label)
        
        thresh_sublabel = QLabel("Threshold")
        thresh_sublabel.setStyleSheet("color: #808090; font-size: 11px;")
        left_layout.addWidget(thresh_sublabel)
        
        # Threshold with spinbox
        thresh_layout = QHBoxLayout()
        self.threshold_slider = QSlider(Qt.Horizontal)
        self.threshold_slider.setRange(1, 100)
        self.threshold_slider.setValue(20)
        self.threshold_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        thresh_layout.addWidget(self.threshold_slider)
        
        self.threshold_spinbox = QSpinBox()
        self.threshold_spinbox.setRange(1, 100)
        self.threshold_spinbox.setValue(20)
        self.threshold_spinbox.setMaximumWidth(70)
        self.threshold_spinbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        thresh_layout.addWidget(self.threshold_spinbox)
        
        # Connect slider and spinbox
        self.threshold_slider.valueChanged.connect(self.threshold_spinbox.setValue)
        self.threshold_spinbox.valueChanged.connect(self.threshold_slider.setValue)
        self.threshold_spinbox.editingFinished.connect(lambda: self.clear_spinbox_focus(self.threshold_spinbox))
        self.threshold_slider.valueChanged.connect(lambda: save_settings(self))
        
        left_layout.addLayout(thresh_layout)

        delay_sublabel = QLabel("Release Delay (ms)")
        delay_sublabel.setStyleSheet("color: #808090; font-size: 11px; margin-top: 8px;")
        left_layout.addWidget(delay_sublabel)
        
        # Delay with spinbox
        delay_layout = QHBoxLayout()
        self.delay_slider = QSlider(Qt.Horizontal)
        self.delay_slider.setRange(0, 1000)
        self.delay_slider.setValue(300)
        self.delay_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        delay_layout.addWidget(self.delay_slider)
        
        self.delay_spinbox = QSpinBox()
        self.delay_spinbox.setRange(0, 1000)
        self.delay_spinbox.setValue(300)
        self.delay_spinbox.setMaximumWidth(70)
        self.delay_spinbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        delay_layout.addWidget(self.delay_spinbox)
        
        # Connect slider and spinbox
        self.delay_slider.valueChanged.connect(self.delay_spinbox.setValue)
        self.delay_spinbox.valueChanged.connect(self.delay_slider.setValue)
        self.delay_spinbox.editingFinished.connect(lambda: self.clear_spinbox_focus(self.delay_spinbox))
        self.delay_slider.valueChanged.connect(lambda: save_settings(self))
        
        left_layout.addLayout(delay_layout)

        # Animation Section
        anim_sublabel = QLabel("Animation FPS (20-60)")
        anim_sublabel.setStyleSheet("color: #808090; font-size: 11px; margin-top: 12px;")
        left_layout.addWidget(anim_sublabel)
        
        # FPS with spinbox
        fps_layout = QHBoxLayout()
        self.fps_slider = QSlider(Qt.Horizontal)
        self.fps_slider.setRange(20, 60)
        self.fps_slider.setValue(45)
        self.fps_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        fps_layout.addWidget(self.fps_slider)
        
        self.fps_spinbox = QSpinBox()
        self.fps_spinbox.setRange(20, 60)
        self.fps_spinbox.setValue(45)
        self.fps_spinbox.setMaximumWidth(70)
        self.fps_spinbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        fps_layout.addWidget(self.fps_spinbox)
        
        # Connect slider and spinbox
        self.fps_slider.valueChanged.connect(self.fps_spinbox.setValue)
        self.fps_spinbox.valueChanged.connect(self.fps_slider.setValue)
        self.fps_spinbox.editingFinished.connect(lambda: self.clear_spinbox_focus(self.fps_spinbox))
        self.fps_slider.valueChanged.connect(self.on_fps_changed)
        
        left_layout.addLayout(fps_layout)

        left_layout.addStretch()

        # RIGHT COLUMN - Waveform and Controls
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(12, 0, 0, 0)
        right_layout.setSpacing(12)
        
        # Waveform section
        waveform_label = QLabel("Microphone Level")
        waveform_label.setStyleSheet("font-weight: bold; color: #b0b0c0;")
        right_layout.addWidget(waveform_label)
        
        self.mic_meter = ModernMicMeter(self.current_theme)
        self.mic_meter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        right_layout.addWidget(self.mic_meter)
        self.mic_meter.setFixedHeight(120)

        # Status section
        self.status_label = QLabel("Stopped")
        self.status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.status_label.setStyleSheet("""
            font-size: 15px;
            font-weight: 600;
            color: #e0e0e0;
            padding: 12px 16px;
            background-color: #16213e;
            border-radius: 6px;
            border: 1px solid #3a3a4a;
            text-align: center;
        """)
        right_layout.addWidget(self.status_label)

        # Control buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        start_btn = QPushButton("Start")
        start_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a9eff;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 12px 24px;
                font-weight: 600;
                font-size: 13px;
                min-height: 38px;
            }
            QPushButton:hover {
                background-color: #5aafff;
            }
            QPushButton:pressed {
                background-color: #3a8eef;
            }
        """)
        start_btn.clicked.connect(self.start_script)

        stop_btn = QPushButton("Stop")
        stop_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #e85d75;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 12px 24px;
                font-weight: 600;
                font-size: 13px;
                min-height: 38px;
            }
            QPushButton:hover {
                background-color: #f07088;
            }
            QPushButton:pressed {
                background-color: #d84d65;
            }
        """)
        stop_btn.clicked.connect(self.stop_script)

        btn_layout.addWidget(start_btn)
        btn_layout.addWidget(stop_btn)
        right_layout.addLayout(btn_layout)

        right_layout.addStretch()

        # Add both columns to main layout with proper stretch factors
        # Left column gets 10 parts (55%), right gets 8 parts (45%) for better left column breathing room
        main_layout.addLayout(left_layout, 10)
        main_layout.addLayout(right_layout, 8)

        # Add main layout to scroll widget
        scroll_layout.addLayout(main_layout, 1)
        scroll.setWidget(scroll_widget)
        
        # Set scroll area to main tab
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.main_tab.setLayout(QVBoxLayout())
        self.main_tab.layout().addWidget(scroll)
        self.main_tab.layout().setContentsMargins(0, 0, 0, 0)

    def on_mode_changed(self, mode):
        """Update mode description"""
        self.activation_mode = mode
        descriptions = {
            "ppt": "Hold the key to transmit. Release to stop.",
            "tap": "Press the key to toggle transmit ON/OFF.",
            "voice_only": "Transmit automatically when voice is detected.",
            "always_on": "Always transmitting. Useful for testing."
        }
        self.mode_description.setText(descriptions.get(mode, ""))
        save_settings(self)

    def on_fps_changed(self, fps_value):
        """Update animation FPS"""
        # Convert FPS to milliseconds interval
        interval_ms = max(1, 1000 // fps_value)
        self.mic_meter.animation_timer.setInterval(interval_ms)
        save_settings(self)

    def clear_spinbox_focus(self, spinbox):
        """Clear focus and selection from spinbox after editing"""
        spinbox.clearFocus()
        spinbox.lineEdit().deselect() if spinbox.lineEdit() else None

    # -------- PROFILES TAB --------

    def build_profiles_tab(self):
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("Saved Profiles"))
        
        self.profile_list = QListWidget()
        self.profile_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.profile_list)
        
        btn_layout = QHBoxLayout()
        
        new_profile_btn = QPushButton("New Profile")
        new_profile_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        new_profile_btn.clicked.connect(self.create_new_profile)
        btn_layout.addWidget(new_profile_btn)
        
        load_profile_btn = QPushButton("Load Profile")
        load_profile_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        load_profile_btn.clicked.connect(self.load_selected_profile)
        btn_layout.addWidget(load_profile_btn)
        
        default_profile_btn = QPushButton("Set as Default")
        default_profile_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        default_profile_btn.setStyleSheet("background-color: #4a9eff;")
        default_profile_btn.clicked.connect(self.set_default_profile)
        btn_layout.addWidget(default_profile_btn)
        
        save_profile_btn = QPushButton("Save Current as Profile")
        save_profile_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        save_profile_btn.clicked.connect(self.save_current_as_profile)
        btn_layout.addWidget(save_profile_btn)
        
        delete_profile_btn = QPushButton("Delete Profile")
        delete_profile_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        delete_profile_btn.setStyleSheet("background-color: #f85149;")
        delete_profile_btn.clicked.connect(self.delete_selected_profile)
        btn_layout.addWidget(delete_profile_btn)
        
        layout.addLayout(btn_layout)
        layout.addStretch()
        
        scroll.setWidget(scroll_widget)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.profiles_tab.setLayout(QVBoxLayout())
        self.profiles_tab.layout().addWidget(scroll)
        self.profiles_tab.layout().setContentsMargins(0, 0, 0, 0)
        self.refresh_profiles_list()

    def set_default_profile(self):
        """Set the selected profile as default"""
        global default_profile
        
        if not self.profile_list.currentItem():
            return
        
        profile_name = self.profile_list.currentItem().text()
        # Remove markers for clean lookup
        profile_name = profile_name.replace("✓ ", "").replace("☆ ", "").replace(" (default)", "")
        profiles = load_all_profiles()
        
        if profile_name in profiles:
            default_profile = profile_name
            save_settings(self)
            self.refresh_profiles_list()
            log(f"Set default profile: {profile_name}")

    def refresh_profiles_list(self):
        """Refresh the profiles list and highlight active/default profiles"""
        self.profile_list.clear()
        profiles = load_all_profiles()
        for profile_name in profiles.keys():
            item = QListWidgetItem(profile_name)
            
            # Highlight the currently loaded profile
            if profile_name == current_profile:
                item.setBackground(QColor("#1f6feb"))  # Highlight with blue
                item.setForeground(QColor("#ffffff"))  # White text
                
                # Add markers for default profile
                if profile_name == default_profile:
                    item.setText(f"✓ {profile_name} (default)")
                else:
                    item.setText(f"✓ {profile_name}")
                
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            elif profile_name == default_profile:
                # Show default marker even if not loaded
                item.setText(f"☆ {profile_name}")
                item.setForeground(QColor("#58a6ff"))
            
            self.profile_list.addItem(item)

    def create_new_profile(self):
        """Create a new blank profile"""
        name, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if ok and name:
            profiles = load_all_profiles()
            if name in profiles:
                log(f"Profile '{name}' already exists")
                return
            
            profiles[name] = {
                "name": name,
                "ppt_key": "v",
                "mute_key": "m",
                "mute_mode": "push",
                "threshold": 20,
                "delay": 300,
                "activation_mode": "ppt",
                "mic_id": None,
                "theme": DEFAULT_THEME.copy()
            }
            save_all_profiles(profiles)
            self.refresh_profiles_list()
            log(f"Created profile: {name}")
            self.setFocus()

    def save_current_as_profile(self):
        """Save current settings as a profile"""
        name, ok = QInputDialog.getText(self, "Save Profile", "Profile name:")
        self.setFocus()  # Return focus immediately after dialog
        
        if ok and name:
            profiles = load_all_profiles()
            profile = create_profile_from_window(self, name)
            profiles[name] = profile
            save_all_profiles(profiles)
            self.refresh_profiles_list()
            log(f"Saved profile: {name}")
            self.profile_list.clearSelection()  # Clear selection for clarity

    def load_selected_profile(self):
        """Load the selected profile"""
        global current_profile
        
        if not self.profile_list.currentItem():
            return
        
        profile_name = self.profile_list.currentItem().text()
        # Remove markers for clean lookup
        profile_name = profile_name.replace("✓ ", "").replace("☆ ", "").replace(" (default)", "")
        profiles = load_all_profiles()
        
        if profile_name in profiles:
            current_profile = profile_name
            apply_profile_to_window(self, profiles[profile_name])
            save_settings(self)
            self.update_profile_indicator()
            self.refresh_profiles_list()  # Refresh to update highlighting
            log(f"Loaded profile: {profile_name}")

    def delete_selected_profile(self):
        """Delete the selected profile"""
        global current_profile, default_profile
        
        if not self.profile_list.currentItem():
            return
        
        profile_name = self.profile_list.currentItem().text()
        # Remove markers for clean lookup
        profile_name = profile_name.replace("✓ ", "").replace("☆ ", "").replace(" (default)", "")
        profiles = load_all_profiles()
        
        if profile_name in profiles:
            del profiles[profile_name]
            save_all_profiles(profiles)
            
            # Clear current_profile if we deleted the active one
            if current_profile == profile_name:
                current_profile = None
                self.update_profile_indicator()
            
            # Switch default to next profile if deleted default
            if default_profile == profile_name:
                if profiles:
                    default_profile = list(profiles.keys())[0]
                else:
                    default_profile = None
                save_settings(self)
            
            self.refresh_profiles_list()
            log(f"Deleted profile: {profile_name}")

    # -------- TARGETS TAB --------

    def build_targets_tab(self):
        """Build the targets/destinations tab for keypress routing"""
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        layout.addWidget(QLabel("Keypress Destinations"))
        layout.addWidget(QLabel("Select which windows/processes will receive your keypresses"))
        
        # Target list
        self.targets_list = QListWidget()
        self.targets_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.targets_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(self.targets_list)
        
        # Add target button with dropdown
        add_layout = QHBoxLayout()
        
        self.target_dropdown = QComboBox()
        self.target_dropdown.setMinimumWidth(250)
        self.target_dropdown.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh_available_targets()
        add_layout.addWidget(self.target_dropdown)
        
        add_target_btn = QPushButton("Add Target")
        add_target_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        add_target_btn.clicked.connect(self.add_target)
        add_layout.addWidget(add_target_btn)
        
        layout.addLayout(add_layout)
        
        # Remove button
        remove_btn = QPushButton("Remove Selected")
        remove_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        remove_btn.setStyleSheet("background-color: #f85149;")
        remove_btn.clicked.connect(self.remove_selected_target)
        layout.addWidget(remove_btn)
        
        # Refresh button
        refresh_targets_btn = QPushButton("Refresh Available Targets")
        refresh_targets_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        refresh_targets_btn.clicked.connect(self.refresh_available_targets)
        layout.addWidget(refresh_targets_btn)
        
        layout.addStretch()
        
        scroll.setWidget(scroll_widget)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.targets_tab.setLayout(QVBoxLayout())
        self.targets_tab.layout().addWidget(scroll)
        self.targets_tab.layout().setContentsMargins(0, 0, 0, 0)
        self.refresh_targets_list()

    def refresh_available_targets(self):
        """Populate dropdown with available windows and processes"""
        self.target_dropdown.clear()
        targets = get_available_targets()
        self.target_dropdown.addItems(targets)

    def add_target(self):
        """Add selected target to the list"""
        global selected_targets
        
        target = self.target_dropdown.currentText()
        if not target:
            return
        
        # Avoid duplicates
        if target not in selected_targets:
            selected_targets.append(target)
            self.refresh_targets_list()
            save_settings(self)
            log(f"Added target: {target}")

    def remove_selected_target(self):
        """Remove selected targets from the list"""
        global selected_targets
        
        for item in self.targets_list.selectedItems():
            target = item.text()
            if target in selected_targets:
                selected_targets.remove(target)
        
        self.refresh_targets_list()
        save_settings(self)
        log(f"Removed {len(self.targets_list.selectedItems())} target(s)")

    def refresh_targets_list(self):
        """Refresh the targets list display"""
        self.targets_list.clear()
        for target in selected_targets:
            item = QListWidgetItem(target)
            # Visual indicator for focused window
            if target == "Focused Window":
                item.setForeground(QColor("#58a6ff"))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setText(f"→ {target}")
            elif target.startswith("[Window]"):
                item.setForeground(QColor("#79c0ff"))
            elif target.startswith("[Process]"):
                item.setForeground(QColor("#f85149"))
            
            self.targets_list.addItem(item)

    # -------- THEME TAB --------

    def build_theme_tab(self):
        """Build the theme customization tab"""
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("Theme Colors", ))
        
        # Color picker buttons
        colors_to_customize = [
            ("Background Dark", "bg_dark"),
            ("Background Light", "bg_light"),
            ("Waveform Cyan", "waveform_cyan"),
            ("Waveform Blue", "waveform_blue"),
            ("Waveform Pink", "waveform_pink"),
            ("Threshold Color", "threshold_color"),
            ("Border Color", "border_color"),
            ("Accent Cyan", "accent_cyan"),
            ("Accent Pink", "accent_pink"),
        ]
        
        for label, key in colors_to_customize:
            btn_layout = QHBoxLayout()
            btn_layout.addWidget(QLabel(label))
            btn_layout.addStretch()
            
            color_btn = QPushButton("Pick Color")
            color_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            color_btn.clicked.connect(lambda checked, k=key: self.pick_color(k))
            btn_layout.addWidget(color_btn)
            
            self.color_preview = QLabel()  # Store for reuse
            self.color_preview.setFixedSize(30, 30)
            self.update_color_preview(key)
            btn_layout.addWidget(self.color_preview)
            
            layout.addLayout(btn_layout)
        
        layout.addStretch()
        
        reset_btn = QPushButton("Reset to Default Theme")
        reset_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        reset_btn.clicked.connect(self.reset_theme)
        layout.addWidget(reset_btn)
        
        scroll.setWidget(scroll_widget)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.theme_tab.setLayout(QVBoxLayout())
        self.theme_tab.layout().addWidget(scroll)
        self.theme_tab.layout().setContentsMargins(0, 0, 0, 0)

    def pick_color(self, color_key):
        """Open color picker dialog"""
        current_color = QColor(self.current_theme.get(color_key, "#00d9ff"))
        new_color = QColorDialog.getColor(current_color, self, f"Choose {color_key}")
        
        if new_color.isValid():
            self.current_theme[color_key] = new_color.name()
            self.apply_theme()
            save_settings(self)
            self.update_color_preview(color_key)

    def update_color_preview(self, key):
        """Update color preview button"""
        color = QColor(self.current_theme.get(key, "#00d9ff"))
        self.color_preview.setStyleSheet(f"background-color: {color.name()}; border-radius: 4px;")

    def apply_theme(self):
        """Apply current theme to UI"""
        self.mic_meter.set_theme(self.current_theme)

    def reset_theme(self):
        """Reset theme to default"""
        self.current_theme = DEFAULT_THEME.copy()
        self.apply_theme()
        save_settings(self)
        log("Theme reset to default")

    # -------- DEV TAB --------

    def build_dev_tab(self):
        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        splitter = QSplitter(Qt.Vertical)

        self.debug_info = QTextEdit()
        self.debug_info.setReadOnly(True)
        self.debug_info.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.config_view = QTextEdit()
        self.config_view.setReadOnly(False)
        self.config_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        splitter.addWidget(self.debug_info)
        splitter.addWidget(self.log_console)
        splitter.addWidget(self.config_view)
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        layout.addWidget(QLabel("Dev Console"))
        layout.addWidget(splitter)
        
        refresh_btn = QPushButton("Refresh Config")
        refresh_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        refresh_btn.clicked.connect(self.update_config_view)
        layout.addWidget(refresh_btn)
        
        save_btn = QPushButton("Save Config")
        save_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        save_btn.clicked.connect(self.save_config_from_editor)
        layout.addWidget(save_btn)
        
        clear_btn = QPushButton("Clear Logs")
        clear_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        clear_btn.clicked.connect(lambda: self.clear_logs())
        layout.addWidget(clear_btn)

        scroll.setWidget(scroll_widget)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.dev_tab.setLayout(QVBoxLayout())
        self.dev_tab.layout().addWidget(scroll)
        self.dev_tab.layout().setContentsMargins(0, 0, 0, 0)

    def clear_logs(self):
        with log_lock:
            log_buffer.clear()
        self.log_console.clear()
        self.last_log_index = 0

    def update_config_view(self):
        path = get_config_path()
    
        # Don't update if the user is actively editing
        if self.config_view.hasFocus():
            return

        if not os.path.exists(path):
            self.config_view.setText("No config file yet.")
            return

        try:
            with open(path, "r") as f:
                data = json.load(f)

            pretty = json.dumps(data, indent=4)
            current_text = self.config_view.toPlainText()
            
            # Only update if content actually changed
            if current_text != pretty:
                # Save scroll position
                scrollbar = self.config_view.verticalScrollBar()
                scroll_pos = scrollbar.value()
                
                self.config_view.setText(pretty)
                
                # Restore scroll position
                scrollbar.setValue(scroll_pos)

        except Exception as e:
            self.config_view.setText(f"Error reading config:\n{e}")
            
    def save_config_from_editor(self):
        try:
            data = json.loads(self.config_view.toPlainText())

            with open(get_config_path(), "w") as f:
                json.dump(data, f, indent=4)

            self.status_label.setText("Config saved")
        
            QTimer.singleShot(
                1000,
                lambda: self.status_label.setText("Listening" if running else "Stopped")
            )
        
            load_settings(self)
            self.update()

        except Exception as e:
            self.status_label.setText(f"Invalid JSON: {e}")

    # -------- FUNCTIONS --------
    
    def refresh_mics(self):
        self.mic_devices = get_valid_mics()
        self.mic_dropdown.clear()

        for i, name in self.mic_devices:
            self.mic_dropdown.addItem(name)
            
        QTimer.singleShot(0, lambda: load_settings(self))

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
        global running, stream, key_held, toggle_active, mute_toggled, system_mute_held

        running = False
        toggle_active = False
        mute_toggled = False
        
        # Unmute system microphone when stopping to be safe
        if system_mute_key and system_mute_held:
            set_system_mic_mute(False)
            system_mute_held = False

        if stream:
            stream.stop()
            stream.close()

        if key_held:
            keyboard.release(get_key_obj(self.ppt_key))
            key_held = False

    def update_status(self):
        with lock:
            is_running = running
            is_muted = mute_held
            is_ppt = key_held
            volume = smoothed_volume
            mode = activation_mode
        
        if not is_running:
            text = "Stopped"
        elif is_muted:
            text = "MUTED (Override)"
        elif is_ppt:
            text = "TRANSMITTING"
        else:
            text = "Listening"

        log(f"Status: {text}, Mode: {mode}, Vol: {volume:.2f}, Muted: {is_muted}")

        # Simple check: if smoothed volume is very low, show idle animation
        if smoothed_volume < 0.01:
            # Show smooth idle animation
            idle_value = (math.sin(time.time() * 3) * 0.5 + 0.5) * 0.08
            self.mic_meter.setLevel(idle_value)
        else:
            # Show real audio
            self.mic_meter.setLevel(volume)
        
        self.mic_meter.setThreshold(self.threshold_slider.value() / 100)
        self.mic_meter.setActive(is_ppt and not is_muted)
        self.status_label.setText(text)
        
        if (text != self._last_status_text or
            (is_ppt and not is_muted) != self._last_ppt_active):
            self._last_status_text = text
            self._last_ppt_active = is_ppt and not is_muted

    def update_debug(self):
        global last_real_audio_time
        
        targets_str = ", ".join(selected_targets) if selected_targets else "None"
        
        text = f"""
=== Mic → Push-To-Talk Debug Console ===

VERSION: 2.4.0 (Profiles + Theme + Targets + System Mute)

[ACTIVATION & MUTE]
Activation Mode: {activation_mode}
Mute Mode: {mute_mode}
Mute Key: {mute_key}
Current Status: {"Listening" if running else "Stopped"}

[SYSTEM MUTE]
System Mute Key: {system_mute_key or "None"}
System Mute Mode: {system_mute_mode if system_mute_key else "N/A"}
System Mute Enabled: {system_mute_enabled and system_mute_key}
pycaw Available: {pycaw_available}

[KEYS]
Activation Key: {ppt_key}
Transmitting: {key_held}

[AUDIO]
Current Volume: {current_volume:.3f}
Smoothed Volume: {smoothed_volume:.3f}
Max Volume Seen: {max_volume_seen:.3f}

[SETTINGS]
Threshold: {self.threshold_slider.value()}
Release Delay: {self.delay_slider.value()}ms
Animation FPS: {self.fps_slider.value()}

[PROFILES]
Current Profile: {current_profile or "None"}
Default Profile: {default_profile or "None"}
Targets: {targets_str}

[MICROPHONE]
Selected Device: {self.mic_dropdown.currentText() if self.mic_devices else "None"}
App Muted: {mute_held or mute_toggled}
"""

        # Update debug info
        self.debug_info.setText(text)

        # Handle log console with scroll position preservation
        scrollbar = self.log_console.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 10

        with log_lock:
            new_logs = log_buffer[self.last_log_index:]
            self.last_log_index = len(log_buffer)

        for line in new_logs:
            self.log_console.append(line)

        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())
        
        self.update_config_view()

    def capture_mute_key(self):
        self.status_label.setText("Press mute key...")
        self.grabKeyboard()
        self.capturing_mute = True
        
    def capture_key(self):
        self.status_label.setText("Press activation key...")
        self.grabKeyboard()
        self.capturing_ppt = True

    def capture_system_mute_key(self):
        self.status_label.setText("Press system mute key...")
        self.grabKeyboard()
        self.capturing_system_mute = True

    def keyPressEvent(self, event):
        global mute_key, ppt_key, mute_mode, system_mute_key, system_mute_mode
        
        key = QKeySequence(event.key()).toString().lower()

        if key:
            if getattr(self, "capturing_system_mute", False):
                system_mute_key = key.lower()
                system_mute_mode = self.system_mute_mode_dropdown.currentText()
                save_settings(self)
                self.system_mute_label.setText(system_mute_key)
                self.capturing_system_mute = False
                log(f"System mute key set to: {system_mute_key}")
                self.releaseKeyboard()
                self.clearFocus()
                self.status_label.setText("Listening" if running else "Stopped")
                
            elif getattr(self, "capturing_mute", False):
                mute_key = key.lower()
                mute_mode = self.mute_mode_dropdown.currentText()
                save_settings(self)
                self.mute_label.setText(mute_key)
                self.capturing_mute = False
                log(f"Mute key set to: {mute_key}")
                self.releaseKeyboard()
                self.clearFocus()
                self.status_label.setText("Listening" if running else "Stopped")
                
            elif getattr(self, "capturing_ppt", False):
                ppt_key = key.lower()
                self.ppt_key = key.lower()
                save_settings(self)
                self.ppt_label.setText(self.ppt_key)
                self.capturing_ppt = False
                log(f"Activation key set to: {ppt_key}")
                self.releaseKeyboard()
                self.clearFocus()
                self.status_label.setText("Listening" if running else "Stopped")

# ============= APP ================

app = QApplication(sys.argv)

# Enable High DPI scaling for better rendering on high-resolution displays
app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

# Set global font instead of stylesheet
app.setFont(QFont("Segoe UI", 10))

tray_icon = QSystemTrayIcon(create_studio_mic_icon())
tray_icon.setToolTip("Mic → Push-To-Talk (Multi-Mode)")
tray_icon.show()

# Modern dark theme
# Set palette for dark mode support including title bar
palette = QPalette()
palette.setColor(QPalette.WindowText, QColor("#c9d1d9"))
palette.setColor(QPalette.Window, QColor("#0d1117"))
palette.setColor(QPalette.Base, QColor("#0d1117"))
palette.setColor(QPalette.AlternateBase, QColor("#161b22"))
palette.setColor(QPalette.ToolTipBase, QColor("#0d1117"))
palette.setColor(QPalette.ToolTipText, QColor("#c9d1d9"))
palette.setColor(QPalette.Text, QColor("#c9d1d9"))
palette.setColor(QPalette.Button, QColor("#161b22"))
palette.setColor(QPalette.ButtonText, QColor("#c9d1d9"))
palette.setColor(QPalette.Link, QColor("#58a6ff"))
palette.setColor(QPalette.Highlight, QColor("#1f6feb"))
palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
app.setPalette(palette)

app.setStyleSheet("""
QMainWindow {
    background-color: #0d1117;
}

QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
    font-size: 13px;
    font-family: 'Segoe UI', 'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif;
}

QTabWidget::pane {
    border: 1px solid #30363d;
    border-radius: 6px;
    background-color: #0d1117;
}

QTabBar::tab {
    background: #161b22;
    padding: 8px 20px;
    border-radius: 6px 6px 0px 0px;
    border: 1px solid #30363d;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background: #0d1117;
    border-bottom: 2px solid #58a6ff;
    color: #58a6ff;
    font-weight: 600;
}

QLabel {
    font-weight: 500;
    color: #c9d1d9;
}

QComboBox {
    background: #0d1117;
    border: 2px solid #30363d;
    padding: 6px 8px;
    border-radius: 6px;
    color: #c9d1d9;
    margin: 0px;
    padding-right: 24px;
}

QComboBox::drop-down {
    border: none;
    background: transparent;
    width: 24px;
    subcontrol-position: right;
    subcontrol-origin: padding;
    padding-right: 4px;
}

QComboBox::down-arrow {
    image: none;
    width: 8px;
    height: 8px;
}

QComboBox QAbstractItemView {
    background: #161b22;
    selection-background-color: #58a6ff;
    color: #c9d1d9;
    border: 2px solid #30363d;
    border-radius: 4px;
    outline: none;
    padding: 4px;
}

QPushButton {
    background-color: #238636;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
    min-height: 28px;
}

QPushButton:hover {
    background-color: #2ea043;
}

QPushButton:pressed {
    background-color: #1f6feb;
}

QSlider::groove:horizontal {
    height: 6px;
    background: #30363d;
    border: 1px solid #30363d;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #58a6ff;
    width: 16px;
    margin: -5px 0;
    border-radius: 8px;
}

QSpinBox {
    background: #0d1117;
    border: 1px solid #30363d;
    padding: 4px 6px;
    border-radius: 4px;
    color: #c9d1d9;
    min-width: 50px;
}

QSpinBox:focus {
    border: 2px solid #58a6ff;
    padding: 5px 7px;
}

QTextEdit {
    background: #0d1117;
    border: 1px solid #30363d;
    color: #c9d1d9;
    border-radius: 6px;
}

QListWidget {
    background: #0d1117;
    border: 1px solid #30363d;
    color: #c9d1d9;
    border-radius: 6px;
}

QListWidget::item:selected {
    background: #58a6ff;
    color: #0d1117;
}
""")

app.setWindowIcon(create_studio_mic_icon())

window = MainWindow()
window.show()

tray_icon.setIcon(create_studio_mic_icon())
tray_icon.show()

sys.exit(app.exec())
