"""
Profile management - load, save, create, delete profiles
Handles all profile persistence and manipulation
"""
import json
import os
from copy import deepcopy

import app.config as config
from app.utils.helpers import log
from app.config import (
    get_profiles_path, get_appdata_path, DEFAULT_PROFILE_DATA, 
    DEFAULT_AUDIO_SETTINGS
)


# Global profiles dictionary
all_profiles = {}


def initialize_profiles():
    """Initialize profile system - load profiles or create default"""
    global all_profiles
    
    log("Initializing profiles...")
    
    # Load existing profiles
    if load_profiles():
        log(f"Loaded {len(all_profiles)} profiles")
    else:
        log("No existing profiles found, creating default")
        # Create a default profile
        create_profile("Default", DEFAULT_PROFILE_DATA.copy())
        config.current_profile = "Default"
        config.default_profile = "Default"
        save_profiles()
        log("Default profile created")


def load_profiles():
    """
    Load all profiles from disk
    Returns True if successful, False otherwise
    """
    global all_profiles
    
    try:
        profiles_path = get_profiles_path()
        
        if not os.path.exists(profiles_path):
            log(f"Profiles file does not exist: {profiles_path}")
            all_profiles = {}
            return False
        
        with open(profiles_path, 'r') as f:
            data = json.load(f)
        
        all_profiles = data.get("profiles", {})
        config.default_profile = data.get("default_profile", None)
        
        # Validate loaded profiles
        for profile_name in all_profiles:
            validate_profile(profile_name)
        
        log(f"Successfully loaded {len(all_profiles)} profiles")
        return True
    
    except Exception as e:
        log(f"Error loading profiles: {e}")
        all_profiles = {}
        return False


def save_profiles():
    """
    Save all profiles to disk
    Returns True if successful, False otherwise
    """
    try:
        profiles_path = get_profiles_path()
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(profiles_path), exist_ok=True)
        
        data = {
            "profiles": all_profiles,
            "default_profile": config.default_profile,
            "version": 1
        }
        
        with open(profiles_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        log(f"Saved {len(all_profiles)} profiles to disk")
        return True
    
    except Exception as e:
        log(f"Error saving profiles: {e}")
        return False


def validate_profile(profile_name):
    """
    Validate and fix a profile structure
    Fills in missing fields with defaults
    """
    if profile_name not in all_profiles:
        return False
    
    profile = all_profiles[profile_name]
    defaults = DEFAULT_PROFILE_DATA.copy()
    
    # Fill in missing top-level fields
    for key, value in defaults.items():
        if key not in profile:
            profile[key] = deepcopy(value)
    
    # Ensure audio_settings structure
    if "audio_settings" not in profile:
        profile["audio_settings"] = DEFAULT_AUDIO_SETTINGS.copy()
    else:
        # Fill in missing audio settings
        for key, value in DEFAULT_AUDIO_SETTINGS.items():
            if key not in profile["audio_settings"]:
                profile["audio_settings"][key] = deepcopy(value)
    
    return True


def create_profile(profile_name, profile_data=None):
    """
    Create a new profile
    
    Args:
        profile_name: Name of the profile
        profile_data: Optional profile data dict (defaults to DEFAULT_PROFILE_DATA)
    
    Returns:
        True if successful, False otherwise
    """
    global all_profiles
    
    if profile_name in all_profiles:
        log(f"Profile '{profile_name}' already exists")
        return False
    
    if profile_data is None:
        profile_data = deepcopy(DEFAULT_PROFILE_DATA)
    else:
        # Merge with defaults to ensure all fields exist
        merged = deepcopy(DEFAULT_PROFILE_DATA)
        merged.update(profile_data)
        profile_data = merged
    
    all_profiles[profile_name] = profile_data
    validate_profile(profile_name)
    log(f"Created profile: '{profile_name}'")
    
    return True


def delete_profile(profile_name):
    """
    Delete a profile
    
    Args:
        profile_name: Name of profile to delete
    
    Returns:
        True if successful, False otherwise
    """
    global all_profiles
    
    if profile_name not in all_profiles:
        log(f"Profile '{profile_name}' does not exist")
        return False
    
    if profile_name == config.current_profile:
        log(f"Cannot delete profile '{profile_name}' - it is currently loaded")
        return False
    
    del all_profiles[profile_name]
    
    # If we just deleted the default profile, set a new default
    if profile_name == config.default_profile and all_profiles:
        new_default = list(all_profiles.keys())[0]
        config.default_profile = new_default
        log(f"Default profile was deleted. New default: '{new_default}'")
    
    log(f"Deleted profile: '{profile_name}'")
    return True


def get_profile(profile_name):
    """
    Get profile data
    
    Args:
        profile_name: Name of profile to get
    
    Returns:
        Profile dict or None if not found
    """
    if profile_name not in all_profiles:
        return None
    
    return all_profiles[profile_name]


def profile_exists(profile_name):
    """Check if a profile exists"""
    return profile_name in all_profiles


def get_all_profile_names():
    """Get list of all profile names"""
    return list(all_profiles.keys())


def load_profile(profile_name):
    """
    Load a profile into the active configuration
    
    Args:
        profile_name: Name of profile to load
    
    Returns:
        True if successful, False otherwise
    """
    if not profile_exists(profile_name):
        log(f"Profile '{profile_name}' does not exist")
        return False
    
    profile = get_profile(profile_name)
    if not profile:
        return False
    
    try:
        with config.lock:
            # Load PTT settings
            config.ptt_key = profile.get("ptt_key", "v")
            config.activation_mode = profile.get("activation_mode", "ptt")
            
            # Load mute settings
            config.mute_key = profile.get("mute_key", "m")
            config.mute_mode = profile.get("mute_mode", "push")
            
            # Load system mute settings
            config.system_mute_key = profile.get("system_mute_key", None)
            config.system_mute_mode = profile.get("system_mute_mode", "push")
            
            # Load audio settings
            config.audio_settings = deepcopy(profile.get("audio_settings", DEFAULT_AUDIO_SETTINGS))

            # Load mic selection
            mic_device_id = profile.get("mic_device_id", None)
            
            # Validate if mic still exists
            if mic_device_id is None:
                try:
                    from app.audio.mic_monitor import list_microphones
                    available_mics = list_microphones()
                    
                    # Extract mic id
                    mic_ids = []
                    for mic in available_mics:
                        if isinstance(mic, dict):
                            mic_ids.append(mic.get('id'))
                        elif isinstance(mic, tuple):
                            mic_ids.append(mic[0])
                            
                    # Check if device is still available
                    if mic_device_id in mic_ids:
                        config.selected_mic_device_id = mic_device_id
                        log(f"[mic_device_id] | [INFO] | Loaded mic: {mic_device_id}")
                    else:
                        log(f"[mic_device_id] | [INFO] | Unable to load device {mic_device_id}.")
                        config.selected_mic_device_id = None
                        
                except Exception as e:
                    log("[mic_device_id] | [ERROR] | unable to validat mic device {e}")
                    config.selected_mic_device_id = None
                    
            else:
                config.selected_mic_device_id = None
            
            # Load targets
            targets = profile.get("targets", [])
            if not targets:
                targets = ["Focused Window"]
            config.selected_targets = targets
            
            # Set current profile
            config.current_profile = profile_name

            # Debug: confirm mic_device_id applied to config
        
        log(f"Loaded profile: '{profile_name}'", "INFO")
        return True
    
    except Exception as e:
        log(f"Error loading profile '{profile_name}': {e}", "ERROR")
        return False


def save_profile(profile_name, overwrite=True):
    """
    Save current active settings to a profile
    
    Args:
        profile_name: Name of profile to save to
        overwrite: If True, overwrite existing. If False, fail if exists
    
    Returns:
        True if successful, False otherwise
    """
    if profile_name in all_profiles and not overwrite:
        log(f"Profile '{profile_name}' already exists", "WARNING")
        return False
    
    with config.lock:
        profile_data = {
            "ptt_key": config.ptt_key,
            "activation_mode": config.activation_mode,
            "mute_key": config.mute_key,
            "mute_mode": config.mute_mode,
            "system_mute_key": config.system_mute_key,
            "system_mute_mode": config.system_mute_mode,
            "threshold": getattr(config, 'threshold', 45),
            "release_delay": getattr(config, 'release_delay', 500),
            "mic_device_id": getattr(config, "selected_mic_device_id", None),
            "audio_settings": deepcopy(getattr(config, 'audio_settings', DEFAULT_AUDIO_SETTINGS)),
            "targets": config.selected_targets,
        }
    
    all_profiles[profile_name] = profile_data
    validate_profile(profile_name)
    log(f"Saved profile: '{profile_name}'", "INFO")
    
    return True


def rename_profile(old_name, new_name):
    """
    Rename a profile
    
    Args:
        old_name: Current profile name
        new_name: New profile name
    
    Returns:
        True if successful, False otherwise
    """
    if old_name not in all_profiles:
        log(f"Profile '{old_name}' does not exist", "WARNING")
        return False
    
    if new_name in all_profiles:
        log(f"Profile '{new_name}' already exists", "WARNING")
        return False
    
    all_profiles[new_name] = all_profiles.pop(old_name)
    
    # Update references
    if config.current_profile == old_name:
        config.current_profile = new_name
    if config.default_profile == old_name:
        config.default_profile = new_name
    
    log(f"Renamed profile: '{old_name}' -> '{new_name}'", "INFO")
    return True


def duplicate_profile(source_name, new_name):
    """
    Duplicate a profile
    
    Args:
        source_name: Profile to duplicate
        new_name: Name for the new profile
    
    Returns:
        True if successful, False otherwise
    """
    if source_name not in all_profiles:
        log(f"Profile '{source_name}' does not exist", "WARNING")
        return False
    
    if new_name in all_profiles:
        log(f"Profile '{new_name}' already exists", "WARNING")
        return False
    
    all_profiles[new_name] = deepcopy(all_profiles[source_name])
    log(f"Duplicated profile: '{source_name}' -> '{new_name}'", "INFO")
    
    return True


def set_default_profile(profile_name):
    """
    Set the default profile to load on startup
    
    Args:
        profile_name: Profile name to set as default
    
    Returns:
        True if successful, False otherwise
    """
    if not profile_exists(profile_name):
        log(f"Profile '{profile_name}' does not exist", "WARNING")
        return False
    
    config.default_profile = profile_name
    log(f"Default profile set to: '{profile_name}'", "INFO")
    
    return True


def get_profile_summary(profile_name):
    """
    Get a human-readable summary of a profile
    
    Args:
        profile_name: Profile to summarize
    
    Returns:
        String summary or None if profile not found
    """
    profile = get_profile(profile_name)
    if not profile:
        return None
    
    summary = f"""
Profile: {profile_name}
━━━━━━━━━━━━━━━━━━━━━━
PTT Key: {profile.get('ptt_key', 'V')}
Mode: {profile.get('activation_mode', 'ptt').upper()}
Mute Key: {profile.get('mute_key', 'M')}
Threshold: {profile.get('threshold', 45)}
Release Delay: {profile.get('release_delay', 500)}ms
Targets: {len(profile.get('targets', []))} configured
    """
    return summary.strip()


def export_profile(profile_name, export_path):
    """
    Export a profile to a JSON file
    
    Args:
        profile_name: Profile to export
        export_path: Path to export to
    
    Returns:
        True if successful, False otherwise
    """
    profile = get_profile(profile_name)
    if not profile:
        log(f"Profile '{profile_name}' does not exist", "WARNING")
        return False
    
    try:
        export_data = {
            "profile_name": profile_name,
            "profile_data": profile,
            "version": 1
        }
        
        os.makedirs(os.path.dirname(export_path), exist_ok=True)
        
        with open(export_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        log(f"Exported profile '{profile_name}' to {export_path}", "INFO")
        return True
    
    except Exception as e:
        log(f"Error exporting profile: {e}", "ERROR")
        return False


def import_profile(import_path, profile_name=None):
    """
    Import a profile from a JSON file
    
    Args:
        import_path: Path to import from
        profile_name: Name for imported profile (defaults to original name)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        with open(import_path, 'r') as f:
            import_data = json.load(f)
        
        profile_data = import_data.get("profile_data")
        original_name = import_data.get("profile_name", "imported_profile")
        
        if profile_name is None:
            profile_name = original_name
        
        if profile_name in all_profiles:
            log(f"Profile '{profile_name}' already exists", "WARNING")
            return False
        
        create_profile(profile_name, profile_data)
        log(f"Imported profile as '{profile_name}'", "INFO")
        return True
    
    except Exception as e:
        log(f"Error importing profile: {e}", "ERROR")
        return False


def reset_profile_to_default(profile_name):
    """
    Reset a profile to default settings
    
    Args:
        profile_name: Profile to reset
    
    Returns:
        True if successful, False otherwise
    """
    if profile_name not in all_profiles:
        log(f"Profile '{profile_name}' does not exist", "WARNING")
        return False
    
    all_profiles[profile_name] = deepcopy(DEFAULT_PROFILE_DATA)
    validate_profile(profile_name)
    log(f"Reset profile '{profile_name}' to defaults", "INFO")
    
    return True


# Profile data structure helpers

def get_profile_audio_settings(profile_name):
    """Get audio settings for a profile"""
    profile = get_profile(profile_name)
    if not profile:
        return DEFAULT_AUDIO_SETTINGS.copy()
    return profile.get("audio_settings", DEFAULT_AUDIO_SETTINGS.copy())


def update_profile_audio_settings(profile_name, audio_settings):
    """Update audio settings for a profile"""
    if profile_name not in all_profiles:
        return False
    
    all_profiles[profile_name]["audio_settings"] = audio_settings
    validate_profile(profile_name)
    return True


def get_profile_targets(profile_name):
    """Get targets for a profile"""
    profile = get_profile(profile_name)
    if not profile:
        return []
    return profile.get("targets", [])


def update_profile_targets(profile_name, targets):
    """Update targets for a profile"""
    if profile_name not in all_profiles:
        return False
    
    all_profiles[profile_name]["targets"] = targets
    return True


def get_default_profile():
    """
    Get the default profile name that auto-loads on startup
    
    Returns:
        Profile name or None if not set
    """
    return config.default_profile
