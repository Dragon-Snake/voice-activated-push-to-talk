"""
DIAGNOSTIC SCRIPT - Run this to understand your microphone setup

Usage:
  python debug_mics.py

This will show:
1. All Windows audio devices
2. Why each device is included/excluded
3. Which device is your actual microphone
4. Audio capture test on each device
"""

import sounddevice as sd
import numpy as np
import time


def show_all_devices():
    """Show all devices with detailed info"""
    print("\n" + "="*80)
    print("ALL WINDOWS AUDIO DEVICES")
    print("="*80 + "\n")
    
    devices = sd.query_devices()
    
    for i, d in enumerate(devices):
        print(f"Device {i}: {d['name']}")
        print(f"  Input channels:  {d['max_input_channels']}")
        print(f"  Output channels: {d['max_output_channels']}")
        print(f"  Sample rate:     {d['default_samplerate']} Hz")
        print(f"  Latency (in):    {d.get('default_low_input_latency', 0):.4f}s")
        print(f"  Latency (out):   {d.get('default_low_output_latency', 0):.4f}s")
        print()


def test_filter_logic():
    """Show which devices would pass filtering"""
    print("="*80)
    print("FILTER RESULTS")
    print("="*80 + "\n")
    
    devices = sd.query_devices()
    passed = []
    
    for i, d in enumerate(devices):
        name = d['name']
        lower_name = name.lower()
        
        print(f"Device {i}: {name}")
        
        # Check 1: Output channels
        if d['max_output_channels'] > 0:
            print(f"  ✗ FAIL: Has output channels ({d['max_output_channels']})")
            print()
            continue
        print(f"  ✓ PASS: No output channels")
        
        # Check 2: Input channels
        if d['max_input_channels'] <= 0:
            print(f"  ✗ FAIL: No input channels")
            print()
            continue
        print(f"  ✓ PASS: Has {d['max_input_channels']} input channel(s)")
        
        # Check 3: Channel count
        if d['max_input_channels'] > 2:
            print(f"  ✗ FAIL: Too many channels ({d['max_input_channels']}) - likely array/virtual")
            print()
            continue
        print(f"  ✓ PASS: Normal channel count (1-2)")
        
        # Check 4: Latency
        latency = d.get('default_low_input_latency', 0)
        if latency > 0.5:
            print(f"  ✗ FAIL: High latency ({latency:.3f}s) - problematic device")
            print()
            continue
        print(f"  ✓ PASS: Good latency ({latency:.4f}s)")
        
        # Check 5: Name filters
        skip_keywords = [
            "stereo mix",
            "what u hear",
            "loopback",
            "speakers",
            "output",
            "virtual",
            "mapper",
            "rear panel",
            "rear mic",
            "rear",
            "line in",
            "line out",
        ]
        
        if any(k in lower_name for k in skip_keywords):
            matched = [k for k in skip_keywords if k in lower_name]
            print(f"  ✗ FAIL: Keyword filter - {matched}")
            print()
            continue
        print(f"  ✓ PASS: Name is OK (no filtered keywords)")
        
        # All filters passed!
        print(f"  ✅ ACCEPTED AS MICROPHONE")
        passed.append((i, name))
        print()
    
    print("="*80)
    print(f"SUMMARY: {len(passed)} real microphone(s) found\n")
    for i, name in passed:
        print(f"  Device {i}: {name}")
    print()
    
    return passed
            
def test_audio_capture(device_id, duration=2.0):
    volumes = []

    def callback(indata, frames, time_info, status):
        if status:
            print(f"  ⚠ {status}")
        vol = np.sqrt(np.mean(indata[:,0]**2))
        volumes.append(vol)
        bar = "█" * min(int(vol * 50), 50)
        print(f"  Volume: {vol:.4f} {bar}")

    try:
        with sd.InputStream(device=device_id,
                            channels=1,
                            samplerate=44100,
                            blocksize=2048,
                            callback=callback):
            print(f"Speak into the microphone for {duration} seconds...")
            sd.sleep(int(duration * 1000))  # sd.sleep uses milliseconds safely
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

    if volumes:
        avg = np.mean(volumes)
        max_vol = np.max(volumes)
        print(f"\n  Test complete! Average: {avg:.4f}, Peak: {max_vol:.4f}")
        return avg > 0.001
    else:
        print("  ❌ No audio data captured")
        return False

def main():
    print("\n" + "="*80)
    print("MICROPHONE DIAGNOSTIC TOOL")
    print("="*80)
    
    # Show all devices
    show_all_devices()
    
    # Show filtering
    passed = test_filter_logic()
    
    if not passed:
        print("\n⚠️  NO MICROPHONES FOUND!")
        print("Possible causes:")
        print("  1. All mics are virtual/mapper devices")
        print("  2. Microphone is unplugged")
        print("  3. All mics are disabled in Windows")
        return
    
    # Test audio on each passed device
    print("\n" + "="*80)
    print("AUDIO CAPTURE TEST")
    print("="*80)
    
    working = []
    for device_id, name in passed:
        print(f"\nDevice {device_id}: {name}")
        if test_audio_capture(device_id, duration=2.0):
            working.append((device_id, name))
    
    # Summary
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)
    print(f"\nFilter passed: {len(passed)} device(s)")
    for i, name in passed:
        print(f"  Device {i}: {name}")
    
    print(f"\nAudio test passed: {len(working)} device(s)")
    for i, name in working:
        print(f"  Device {i}: {name}")
    
    if working:
        print(f"\n✅ Your microphone is: Device {working[0][0]}: {working[0][1]}")
        print(f"   Use this device ID in your app!")
    else:
        print(f"\n❌ No working microphones found")
        print(f"   Check Windows Sound Settings")
    
    print()


if __name__ == "__main__":
    main()
