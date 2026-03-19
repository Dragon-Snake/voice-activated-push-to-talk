#!/usr/bin/env python3
"""
Verify that all imports work correctly with absolute paths
Run this before building the executable

Usage:
    python verify_imports.py
"""

import sys
from pathlib import Path


def verify_imports():
    """Verify all imports can be resolved"""
    print("="*60)
    print("Import Verification")
    print("="*60 + "\n")
    
    errors = []
    
    # Test imports
    tests = [
        ("app.config", "setup_logging, ppt_key, DEFAULT_THEME"),
        ("app.main", "main"),
        ("app.ui.main_window", "MainWindow"),
        ("app.ui.overlay", "QuickActionsOverlay"),
        ("app.ui.widgets", "create_studio_mic_icon"),
        ("app.audio.mic_monitor", "list_microphones, start_audio_stream"),
        ("app.audio.sounds", "play_event_sound, AudioEventListenerWidget"),
        ("app.input.hotkeys", "start_keyboard_listener"),
        ("app.core.controller", "Application"),
        ("app.core.profiles", "load_profiles"),
        ("app.utils.helpers", "log"),
    ]
    
    for module_path, items in tests:
        try:
            module = __import__(module_path, fromlist=items.split(", "))
            print(f"✓ {module_path}")
            
            # Verify items exist in module
            for item in items.split(", "):
                item = item.strip()
                if not hasattr(module, item):
                    errors.append(f"  ✗ {module_path}.{item} not found")
                    print(f"  ✗ {item} not found")
        
        except ImportError as e:
            errors.append(f"✗ {module_path}: {e}")
            print(f"✗ {module_path}")
            print(f"  Error: {e}")
    
    print("\n" + "="*60)
    
    if errors:
        print(f"❌ {len(errors)} error(s) found:\n")
        for error in errors:
            print(f"  {error}")
        print("\n⚠️  Fix errors before building executable")
        return False
    else:
        print("✅ All imports verified successfully!")
        print("\n✓ Safe to build executable with: python build.py")
        return True


if __name__ == "__main__":
    success = verify_imports()
    sys.exit(0 if success else 1)
