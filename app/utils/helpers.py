"""
Utility helper functions
"""
import logging
import inspect
from app.config import log_buffer, log_lock, logger

def log(message, level="INFO"):
    """Log a message to both file and UI buffer"""
    
    # Get caller function name
    frame = inspect.currentframe().f_back
    func_name = frame.f_code.co_name

    formatted = f"[{func_name}] | [{level}] | {message}"

    logger.info(formatted)
    
    with log_lock:
        log_buffer.append(formatted)


def get_key_obj(key_str):
    """Convert key string to pynput key object"""
    from pynput.keyboard import Key
    
    key_map = {
        'shift': Key.shift,
        'ctrl': Key.ctrl,
        'alt': Key.alt,
        'enter': Key.enter,
        'space': Key.space,
        'tab': Key.tab,
        'backspace': Key.backspace,
        'delete': Key.delete,
        'home': Key.home,
        'end': Key.end,
        'page_up': Key.page_up,
        'page_down': Key.page_down,
        'f1': Key.f1,
        'f2': Key.f2,
        'f3': Key.f3,
        'f4': Key.f4,
        'f5': Key.f5,
        'f6': Key.f6,
        'f7': Key.f7,
        'f8': Key.f8,
        'f9': Key.f9,
        'f10': Key.f10,
        'f11': Key.f11,
        'f12': Key.f12,
    }
    
    lower_key = key_str.lower()
    return key_map.get(lower_key, lower_key)


def format_time_ms(ms):
    """Format milliseconds as human-readable string"""
    if ms < 1000:
        return f"{ms}ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60
    return f"{minutes:.1f}m"


def clamp(value, min_val, max_val):
    """Clamp a value between min and max"""
    return max(min_val, min(max_val, value))
