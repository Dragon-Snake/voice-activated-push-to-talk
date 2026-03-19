"""
FIXED audio_callback
"""
import sounddevice as sd
import numpy as np
import time

import app.config as config
from app.utils.helpers import log


# Global audio stream
stream = None

# Callback diagnostics
callback_count = 0


def is_working_mic(device_id, timeout=0.3):
    """Test if a device can actually capture audio"""
    try:
        test_stream = sd.InputStream(
            device=device_id,
            channels=1,
            samplerate=44100,
            blocksize=2048,
        )
        test_stream.start()
        time.sleep(timeout)
        test_stream.stop()
        test_stream.close()
        log(f"Device {device_id} is working", "DEBUG")
        return True
    except Exception as e:
        log(f"Device {device_id} test failed: {e}", "DEBUG")
        return False


def list_microphones():
    """Get list of working microphones - test BEFORE adding!"""
    devices = sd.query_devices()
    seen = set()
    valid = []
    
    for i, d in enumerate(devices):
        name = d["name"]
        
        # Basic filters
        if d["max_input_channels"] <= 0:
            continue
        
        if d["max_output_channels"] > 0:
            continue
            
        if name in seen:
            continue
        
        # Filter keywords
        if any(x in name.lower() for x in [
            "stereo mix", "mapper", "rear", "loopback", 
            "speakers", "virtual", "output", "line out"
        ]):
            continue
        
        seen.add(name)
        
        # KEY: Test if it actually works before adding!
        if is_working_mic(i, timeout=0.3):
            valid.append((i, name))
            log(f"Found working mic: {name} (device {i})", "INFO")
    
    log(f"Total working mics: {len(valid)}", "INFO")
    return valid


def audio_callback(indata, frames, time_info, status):
    """Audio callback - AGGRESSIVE BOOST with faster decay like old code"""
    global callback_count
    
    callback_count += 1
    
    if status:
        log(f"CALLBACK STATUS ERROR: {status}", "WARNING")
    
    try:
        # Check what we're getting
        if indata is None or len(indata) == 0:
            log(f"CALLBACK: Got empty data (frames={frames})", "WARNING")
            return
        
        # Handle both mono and stereo - match old code exactly
        if indata.ndim == 1:
            audio_data = indata.flatten()
        else:
            audio_data = indata[:, 0]
        
        # Calculate raw RMS - exactly like old code: np.sqrt(np.mean(indata ** 2))
        raw_volume = float(np.sqrt(np.mean(audio_data ** 2)))
        
        # Log every 20 callbacks (diagnostic)
        if callback_count % 20 == 0:
            log(f"CALLBACK #{callback_count}: raw_vol={raw_volume:.6f}", "DEBUG")
        
        # UPDATE config with AGGRESSIVE BOOST like old working code
        with config.lock:
            config.max_volume_seen = max(config.max_volume_seen * 0.995, raw_volume, 0.01)
            
            normalized_volume = (raw_volume / config.max_volume_seen) * 10.0
            
            # Cap at 1.0 to avoid issues
            config.current_volume = min(normalized_volume, 1.0)
            
            if callback_count % 20 == 0:
                log(f"  raw={raw_volume:.6f}, max_seen={config.max_volume_seen:.6f}, "
                    f"norm={raw_volume/config.max_volume_seen:.4f}, boosted={config.current_volume:.4f}", "DEBUG")
    
    except Exception as e:
        log(f"CALLBACK ERROR: {type(e).__name__}: {e}", "ERROR")


def start_audio_stream(device_index=None):
    """Start audio stream - simple version"""
    global stream, callback_count
    
    try:
        log(f"Opening stream on device {device_index}...", "INFO")
        
        # Reset counter
        callback_count = 0
        
        stream = sd.InputStream(
            device=device_index,
            channels=1,
            samplerate=44100,
            callback=audio_callback,
            blocksize=2048,
        )
        stream.start()
        log(f"Stream started on device {device_index}", "INFO")
        
        # Give it a moment to start
        time.sleep(0.1)
        log(f"Stream active: {stream.active}, callbacks: {callback_count}", "INFO")
        
        return True
    
    except (sd.PortAudioError, ValueError) as e:
        # Try default device as fallback
        log(f"Device {device_index} failed: {e}, trying default...", "WARNING")
        try:
            callback_count = 0
            
            stream = sd.InputStream(
                device=None,
                channels=1,
                samplerate=44100,
                callback=audio_callback,
                blocksize=2048,
            )
            stream.start()
            log("Stream started on default device", "INFO")
            time.sleep(0.1)
            log(f"Stream active: {stream.active}, callbacks: {callback_count}", "INFO")
            return True
        except Exception as e2:
            log(f"Default device also failed: {e2}", "ERROR")
            return False
    
    except Exception as e:
        log(f"Unexpected error: {e}", "ERROR")
        return False


def stop_audio_stream():
    """Stop audio stream"""
    global stream
    
    try:
        if stream:
            log(f"Closing stream. Callbacks: {callback_count}", "INFO")
            stream.stop()
            stream.close()
            stream = None
            log("Stream stopped", "INFO")
    except Exception as e:
        log(f"Error stopping stream: {e}", "ERROR")
