"""
Main application controller - ties everything together
"""
import threading
import time
import numpy as np
from typing import Optional

import app.config as config
from app.utils.helpers import log, get_key_obj
from app.audio.mic_monitor import start_audio_stream, stop_audio_stream, list_microphones
from app.input.hotkeys import start_keyboard_listener, stop_keyboard_listener
from app.core.profiles import (
    initialize_profiles, load_profiles, load_profile, save_profiles, 
    get_all_profile_names, set_default_profile, get_default_profile
)

class _SystemMicMuter:
    """
    Best-effort system-wide microphone mute (Windows).
    Uses pycaw/comtypes when available; otherwise becomes a no-op.
    """

    def __init__(self):
        self._endpoint = None
        self._available: Optional[bool] = None
        self._last_muted: Optional[bool] = None

    def _ensure_endpoint(self):
        if self._available is False:
            return None
        if self._endpoint is not None:
            return self._endpoint

        try:
            import comtypes  # type: ignore
            from ctypes import POINTER
            from comtypes import CLSCTX_ALL
            from comtypes import cast
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore
            from pycaw.constants import EDataFlow, ERole  # type: ignore

            enumerator = AudioUtilities.GetDeviceEnumerator()
            device = enumerator.GetDefaultAudioEndpoint(EDataFlow.eCapture, ERole.eCommunications)
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            endpoint = cast(interface, POINTER(IAudioEndpointVolume))
            self._endpoint = endpoint
            self._available = True
            return endpoint
        except Exception as e:
            self._available = False
            log(f"System mic mute unavailable: {e}", "WARNING")
            return None

    def set_muted(self, muted: bool):
        # Avoid COM calls if state unchanged
        if self._last_muted is not None and self._last_muted == muted:
            return

        endpoint = self._ensure_endpoint()
        if endpoint is None:
            self._last_muted = muted
            return

        try:
            endpoint.SetMute(1 if muted else 0, None)
            self._last_muted = muted
            
            if muted:
                log("System microphone MUTED (all applications)", "INFO")
            else:
                log("System microphone UNMUTED", "INFO")
            
            
        except Exception as e:
            log(f"Failed to set system mic mute: {e}", "ERROR")


class Application:
    """Main application controller"""
    
    def __init__(self, qt_app, window):
        self.qt_app = qt_app
        self.window = window
        self.window.parent_app = self
        self.is_running = False
        self.mic_thread = None
        
        log("Initializing application...", "INFO")
        
        # Initialize profile system
        initialize_profiles()
        
        # Load default profile if available
        if config.default_profile:
            load_profile(config.default_profile)
            log(f"Loaded default profile: {config.default_profile}", "INFO")
        else:
            log("No default profile available", "WARNING")
        
        # Start keyboard listener
        start_keyboard_listener()
        
        # Update UI with loaded profile
        self.refresh_ui()

        # Populate microphone list on startup if UI supports it
        try:
            if hasattr(self.window, "refresh_mics"):
                self.window.refresh_mics()
        except Exception as e:
            log(f"Error refreshing mics on startup: {e}", "ERROR")
        
        log("Application ready", "INFO")
    
    def refresh_ui(self):
        """Refresh the UI with current settings"""
        try:
            # Update profile label
            if hasattr(self.window, 'profile_label') and config.current_profile:
                self.window.profile_label.setText(config.current_profile)
            
            # Update profile list
            if hasattr(self.window, 'profile_list'):
                self.window.profile_list.clear()
                for profile_name in get_all_profile_names():
                    self.window.profile_list.addItem(profile_name)
            
            # Update activation mode combo
            if hasattr(self.window, 'mode_combo'):
                self.window.mode_combo.setCurrentText(config.activation_mode)
            
            # Update PTT key label
            if hasattr(self.window, 'ptt_label'):
                self.window.ptt_label.setText(config.ptt_key.upper())
            
            # Update mute key label
            if hasattr(self.window, 'mute_label'):
                self.window.mute_label.setText(config.mute_key.upper())
            
            # Update mute mode combo
            if hasattr(self.window, 'mute_mode_combo'):
                self.window.mute_mode_combo.setCurrentText(config.mute_mode)
            
            # Update threshold slider
            if hasattr(self.window, 'threshold_slider'):
                self.window.threshold_slider.setValue(config.threshold)
            
            # Update delay slider
            if hasattr(self.window, 'delay_slider'):
                self.window.delay_slider.setValue(config.release_delay)
                
            # Update system mute key label
            if hasattr(self, 'system_mute_label'):
                if config.system_mute_key:
                    self.system_mute_label.setText(config.system_mute_key.upper())
                    self.system_mute_label.setStyleSheet("font-weight: bold; color: #58a6ff;")
                else:
                    self.system_mute_label.setText("NONE")
                    self.system_mute_label.setStyleSheet("font-weight: bold; color: #888888;")
            
            # Update system mute mode combo
            if hasattr(self, 'system_mute_mode_combo'):
                self.system_mute_mode_combo.setCurrentText(config.system_mute_mode)
        
        except Exception as e:
            log(f"Error refreshing UI: {e}", "ERROR")
            
    def auto_select_microphone(self):
        """
        Automatically select best microphone for this system.
        Tests each filtered mic and picks the first that works.
        
        Returns:
            (device_id, device_name) of selected mic, or None
        """
        from app.audio.mic_monitor import list_microphones, test_audio_device
        
        mics = list_microphones()
        if not mics:
            log("No microphones found for auto-selection", "WARNING")
            return None
        
        log("Auto-selecting microphone...", "INFO")
        
        # Try each mic in order
        for device_id, name in mics:
            log(f"Testing microphone: {name}", "DEBUG")
            
            # Quick test: 0.5 second audio capture
            # Returns adaptive score (peak * 0.7 + avg * 0.3)
            score = test_audio_device(device_id, duration=0.5)
            
            # Accept if score > 0.0001 (very low threshold)
            # This catches ANY responsive microphone
            if score > 0.0001:
                log(f"✓ Selected: {name} (score: {score:.4f})", "INFO")
                return (device_id, name)
        
        # If no responsive mic, use first one anyway
        log("No responsive mic found, using first available", "WARNING")
        if mics:
            return mics[0]
        return None
    
    
    def initialize_microphone(self):
        """
        Initialize microphone on app startup.
        
        Logic:
        1. Check if stored device still exists
        2. If yes, use it (trust previous choice)
        3. If no, auto-detect best available
        4. Save selection to profile
        
        Returns:
            True if initialization successful, False otherwise
        """
        import config
        from app.core.profiles import save_profile
        from app.audio.mic_monitor import list_microphones
        
        # Get list of available mics
        mics = list_microphones()
        if not mics:
            log("No microphones found!", "ERROR")
            return False
        
        # Check if we have a stored device from previous session
        stored_device = getattr(config, "selected_mic_device_id", None)
        
        # If stored device exists, try to use it
        if stored_device is not None:
            for device_id, name in mics:
                if device_id == stored_device:
                    log(f"Using stored microphone: {name} (device {device_id})", "INFO")
                    config.selected_mic_device_id = device_id
                    return True
        
        # Stored device missing or doesn't exist - auto-detect
        log("Stored device missing or first run - auto-detecting...", "INFO")
        selected = self.auto_select_microphone()
        
        if selected:
            device_id, name = selected
            config.selected_mic_device_id = device_id
            
            # Save to current profile
            try:
                if config.current_profile:
                    save_profile(config.current_profile, overwrite=True)
                    log(f"Saved mic selection to profile: {config.current_profile}", "DEBUG")
            except Exception as e:
                log(f"Could not save mic selection to profile: {e}", "WARNING")
            
            return True
        
        # No mic could be selected
        log("Failed to initialize microphone", "ERROR")
        return False
    
    def start_ptt(self):
        """Start PTT - simple working version"""
        if self.is_running:
            return
        
        try:
            # Check we have mics
            if not hasattr(self.window, 'mic_devices') or not self.window.mic_devices:
                log("No microphones available", "ERROR")
                self.window.status_label.setText("❌ No microphones")
                return
            
            # Get selected mic device
            idx = self.window.mic_dropdown.currentIndex()
            if idx < 0:
                idx = 0
            
            device_id, device_name = self.window.mic_devices[idx]
            
            log(f"Starting PTT with: {device_name} (device {device_id})", "INFO")
            
            # Try to start stream
            from app.audio.mic_monitor import start_audio_stream
            
            if not start_audio_stream(device_id):
                log("Failed to start audio stream", "ERROR")
                self.window.status_label.setText("❌ Failed to start microphone")
                return
            
            # Set state
            config.running = True
            self.is_running = True
            
            # Start monitoring thread
            import threading
            self.mic_thread = threading.Thread(
                target=self.mic_monitor_loop,
                daemon=True
            )
            self.mic_thread.start()
            
            log("PTT started successfully", "INFO")
            self.window.status_label.setText("🎙️ Listening...")
        
        except Exception as e:
            log(f"Error starting PTT: {e}", "ERROR")
            self.window.status_label.setText(f"❌ Error: {e}")
            config.running = False
            self.is_running = False
    
    def stop_ptt(self):
        """Stop PTT (microphone listening)"""
        if not self.is_running:
            return
        
        try:
            config.running = False
            self.is_running = False
            stop_audio_stream()
            log("PTT stopped", "INFO")
            self.window.status_label.setText("Stopped")
        
        except Exception as e:
            log(f"Error stopping PTT: {e}", "ERROR")
    
    def mic_monitor_loop(self):
        """Background loop for microphone monitoring"""
        log("Mic monitor loop started", "INFO")
        
        from pynput.keyboard import Controller
        keyboard = Controller()
        smoothing_factor = 0.5
        last_voice_time = time.time()
        system_muter = _SystemMicMuter()
        
        last_log_time = time.time()

        while config.running:
            try:
                with config.lock:
                    volume = float(config.current_volume)
                    smoothed = float(config.smoothed_volume)
                    is_muted = config.mute_held or config.mute_toggled
                    system_mute_requested = bool(getattr(config, "system_mute_enabled", False)) and bool(
                        getattr(config, "system_mute_held", False)
                    )
                    mode = config.activation_mode
                    tap_state = config.toggle_active
                    key_held_val = config.key_held
                    threshold_value = config.threshold / 100.0
                    release_delay = config.release_delay / 1000.0
                    ptt_key_to_use = config.ptt_key

                # Apply system-wide mic mute (independent of in-app mute)
                system_muter.set_muted(system_mute_requested)

                # Periodic debug logging so Dev tab has live data
                now = time.time()
                if now - last_log_time >= 1.0:
                    last_log_time = now
                    log(
                        f"loop: vol={smoothed:.3f} "
                        f"mode={mode} muted={is_muted} "
                        f"tap={tap_state} key_held={key_held_val}"
                    )
                
                # Smooth the volume
                config.smoothed_volume = smoothing_factor * volume + (1 - smoothing_factor) * smoothed
                if config.smoothed_volume < 0.01:
                    config.smoothed_volume = 0

                if is_muted:
                    if key_held_val:
                        keyboard.release(get_key_obj(ptt_key_to_use))
                        with config.lock:
                            config.key_held = False
                    config.smoothed_volume = 0
                
                elif mode == "ptt":
                    # PTT mode: key press triggers transmission
                    if key_held_val and config.smoothed_volume > threshold_value:
                        last_voice_time = time.time()
                    elif key_held_val and (time.time() - last_voice_time > release_delay):
                        keyboard.release(get_key_obj(ptt_key_to_use))
                        with config.lock:
                            config.key_held = False

                elif mode == "tap":
                    # Tap mode: toggle transmission with key press
                    if tap_state:
                        if config.smoothed_volume > threshold_value:
                            last_voice_time = time.time()
                            if not key_held_val:
                                keyboard.press(get_key_obj(ptt_key_to_use))
                                with config.lock:
                                    config.key_held = True
                        else:
                            if key_held_val and (time.time() - last_voice_time > release_delay):
                                keyboard.release(get_key_obj(ptt_key_to_use))
                                with config.lock:
                                    config.key_held = False
                    else:
                        if key_held_val:
                            keyboard.release(get_key_obj(ptt_key_to_use))
                            with config.lock:
                                config.key_held = False

                elif mode == "voice_only":
                    # Voice only: automatic transmission on voice detection
                    if config.smoothed_volume > threshold_value:
                        last_voice_time = time.time()
                        if not key_held_val:
                            keyboard.press(get_key_obj(ptt_key_to_use))
                            with config.lock:
                                config.key_held = True
                    else:
                        if key_held_val and (time.time() - last_voice_time > release_delay):
                            keyboard.release(get_key_obj(ptt_key_to_use))
                            with config.lock:
                                config.key_held = False

                elif mode == "always_on":
                    # Always on: continuous transmission
                    if not key_held_val:
                        keyboard.press(get_key_obj(ptt_key_to_use))
                        with config.lock:
                            config.key_held = True

                time.sleep(0.01)
            
            except Exception as e:
                log(f"Error in mic monitor loop: {e}", "ERROR")
                break
        
        log("Mic monitor loop ended", "INFO")
    
    def shutdown(self):
        """Shutdown the application"""
        log("Shutting down application...", "INFO")
        
        self.stop_ptt()
        stop_keyboard_listener()
        
        # Save profiles before exiting
        save_profiles()
        
        log("Application shutdown complete", "INFO")


def get_default_profile():
    """Get the default profile name"""
    return config.default_profile
