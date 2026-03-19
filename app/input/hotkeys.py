"""
Hotkey and keyboard input handling using pynput
"""
from pynput import keyboard
from pynput.keyboard import Key

import app.config as config
from app.utils.helpers import log, get_key_obj
from app.audio.sounds import play_event_sound


# Global keyboard listener
listener = None


def on_press(key):
    """Handle key press events"""
    try:
        # Try to get the character from the key
        try:
            char = key.char
            if char and char.lower() == config.ptt_key.lower():
                # PTT key pressed
                with config.lock:
                    if config.activation_mode == "ptt":
                        config.key_held = True
                        play_event_sound("ptt_on")
                    elif config.activation_mode == "tap":
                        config.toggle_active = not config.toggle_active
                        event = "ptt_on" if config.toggle_active else "ptt_off"
                        play_event_sound(event)
            
            # Mute key
            if char and char.lower() == config.mute_key.lower():
                with config.lock:
                    if config.mute_mode == "toggle":
                        config.mute_toggled = not config.mute_toggled
                        event = "mute_on" if config.mute_toggled else "mute_off"
                        play_event_sound(event)
                    else:
                        config.mute_held = True
                        play_event_sound("mute_on")
            
            # System mute key
            if config.system_mute_key and char and char.lower() == config.system_mute_key.lower():
                with config.lock:
                    if config.system_mute_mode == "toggle":
                        config.system_mute_held = not config.system_mute_held
                    else:
                        config.system_mute_held = True
        
        except AttributeError:
            # Special key (F12, etc)
            key_str = str(key).replace("Key.", "")
            
            if key_str == config.ptt_key:
                with config.lock:
                    if config.activation_mode == "ptt":
                        config.key_held = True
                        play_event_sound("ptt_on")
                    elif config.activation_mode == "tap":
                        config.toggle_active = not config.toggle_active
                        event = "ptt_on" if config.toggle_active else "ptt_off"
                        play_event_sound(event)
            
            elif key_str == config.mute_key:
                with config.lock:
                    if config.mute_mode == "toggle":
                        config.mute_toggled = not config.mute_toggled
                        event = "mute_on" if config.mute_toggled else "mute_off"
                        play_event_sound(event)
                    else:
                        config.mute_held = True
                        play_event_sound("mute_on")
            
            elif config.system_mute_key and key_str == config.system_mute_key:
                with config.lock:
                    if config.system_mute_mode == "toggle":
                        config.system_mute_held = not config.system_mute_held
                    else:
                        config.system_mute_held = True
    
    except Exception as e:
        log(f"Error in key press handler: {e}", "ERROR")


def on_release(key):
    """Handle key release events"""
    try:
        try:
            char = key.char
            if char and char.lower() == config.ptt_key.lower():
                with config.lock:
                    if config.key_held:
                        config.key_held = False
                        play_event_sound("ptt_off")
            
            if char and char.lower() == config.mute_key.lower():
                with config.lock:
                    if config.mute_mode == "push" and config.mute_held:
                        config.mute_held = False
                        play_event_sound("mute_off")
            
            if config.system_mute_key and char and char.lower() == config.system_mute_key.lower():
                with config.lock:
                    if config.system_mute_mode == "push" and config.system_mute_held:
                        config.system_mute_held = False
        
        except AttributeError:
            # Special key
            key_str = str(key).replace("Key.", "")
            
            if key_str == config.ptt_key:
                with config.lock:
                    if config.key_held:
                        config.key_held = False
                        play_event_sound("ptt_off")
            
            elif key_str == config.mute_key:
                with config.lock:
                    if config.mute_mode == "push" and config.mute_held:
                        config.mute_held = False
                        play_event_sound("mute_off")
            
            elif config.system_mute_key and key_str == config.system_mute_key:
                with config.lock:
                    if config.system_mute_mode == "push" and config.system_mute_held:
                        config.system_mute_held = False
    
    except Exception as e:
        log(f"Error in key release handler: {e}", "ERROR")


def start_keyboard_listener():
    """Start the global keyboard listener"""
    global listener
    
    try:
        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.start()
        log("Keyboard listener started", "INFO")
        return True
    except Exception as e:
        log(f"Error starting keyboard listener: {e}", "ERROR")
        return False


def stop_keyboard_listener():
    """Stop the global keyboard listener"""
    global listener
    
    try:
        if listener:
            listener.stop()
            log("Keyboard listener stopped", "INFO")
    except Exception as e:
        log(f"Error stopping keyboard listener: {e}", "ERROR")
