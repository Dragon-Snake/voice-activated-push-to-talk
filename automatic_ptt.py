import sounddevice as sd
import numpy as np
import time
import tkinter as tk
from tkinter import ttk
import threading
from pynput.keyboard import Controller, KeyCode
import customtkinter as ctk

keyboard = Controller()

running = False
key_held = False
last_voice_time = 0
current_volume = 0
stream = None
smoothed_volume = 0.0
smoothing_factor = 0.2  # 0 = no smoothing, 1 = very slow

# ----------------- Microphone detection -----------------

def is_working_mic(index):
    try:
        with sd.InputStream(device=index, channels=1, samplerate=44100) as s:
            data, _ = s.read(1024)
            volume = np.sqrt(np.mean(data**2))
            return volume > 0
    except Exception:
        return False

def get_valid_mics():
    devices = sd.query_devices()
    seen = set()
    valid = []

    for i, d in enumerate(devices):
        name = d['name']
        max_in = d["max_input_channels"]

        if max_in > 0 and all(x not in name for x in ["Stereo Mix", "Primary Sound Capture", "Microsoft Sound Mapper", "Mic in at"]):
            if name not in seen:
                seen.add(name)
                if is_working_mic(i):
                    valid.append((i, name))
    return valid

# ----------------- Audio callback -----------------

def audio_callback(indata, frames, time_info, status):
    global current_volume
    if status:
        print(status)
    # RMS normalized to 0–1 range
    current_volume = min(np.sqrt(np.mean(indata**2)) * 10, 1.0)

# ----------------- Mic processing loop -----------------

def update_gui_status():
    # Determine the label text
    if not running:
        text = "Stopped"
    elif key_held:
        text = "PTT ACTIVE"
    else:
        text = "Listening"

    status_label.configure(text=text)
    root.after(50, update_gui_status)  # run again every 50ms

def mic_loop():
    global key_held, last_voice_time, smoothed_volume

    MIN_HOLD = 0.1  # seconds

    while running:
        volume = current_volume
        threshold_value = threshold.get() / 1000
        release_delay = delay.get() / 1000
        key_obj = KeyCode.from_char(key_entry.get() or last_ptt_key)

        # Smooth volume
        smoothed_volume = (smoothing_factor * volume) + ((1 - smoothing_factor) * smoothed_volume)
        root.after(0, mic_meter.set, smoothed_volume)

        # Check PTT
        if smoothed_volume > threshold_value:
            last_voice_time = time.time()
            if not key_held:
                keyboard.press(key_obj)
                key_held = True
        else:
            if key_held and (time.time() - last_voice_time > release_delay) and (time.time() - last_voice_time > MIN_HOLD):
                keyboard.release(key_obj)
                key_held = False

        time.sleep(0.01)

# ----------------- Start / Stop -----------------

def start_script():
    global running, stream
    if running:
        return

    if not mic_devices:
        status_label.config(text="No working mic detected")
        return

    selected_name = mic_dropdown.get()
    mic_tuple = next((t for t in mic_devices if t[1] == selected_name), None)
    if mic_tuple is None:
        status_label.config(text="No working mic selected")
        return

    selected_index = mic_tuple[0]

    # Make sure we have a valid PTT key
    ptt_char = key_entry.get() or last_ptt_key

    try:
        stream = sd.InputStream(
            device=selected_index,
            channels=1,
            samplerate=44100,
            callback=audio_callback
        )
        stream.start()
    except Exception as e:
        root.after(0, status_label.config, {"text": f"Failed to start mic: {e}"})
        return

    running = True  # set first
    root.after(0, status_label.config, {"text": "Listening"})  # schedule GUI update safely
    threading.Thread(target=mic_loop, daemon=True).start()

def stop_script():
    global running, key_held, stream
    running = False
    if stream:
        stream.stop()
        stream.close()
        stream = None

    if key_held:
        keyboard.release(KeyCode.from_char(key_entry.get()))
        key_held = False

    update_gui_status()

# ----------------- GUI -----------------
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

root = ctk.CTk()
root.title("Mic → Push-To-Talk")
root.geometry("450x500")

def toggle_theme():
    current = ctk.get_appearance_mode()
    ctk.set_appearance_mode("Light" if current=="Dark" else "Dark")

# ----------------- Tabview -----------------
tabview = ctk.CTkTabview(root, width=400)
tabview.pack(pady=10, padx=10, fill="both", expand=True)
tabview.add("Main")
tabview.add("Dev")
main_tab = tabview.tab("Main")
dev_tab = tabview.tab("Dev")

# ----------------- Microphone -----------------
ctk.CTkLabel(main_tab, text="Microphone").pack(pady=(10,0))
mic_devices = get_valid_mics()
mic_names = [d[1] for d in mic_devices]
mic_dropdown = ctk.CTkComboBox(main_tab, values=mic_names)
mic_dropdown.pack(pady=(0,10))
if mic_devices:
    mic_dropdown.set(mic_names[0])

def refresh_devices():
    global mic_devices
    mic_devices = get_valid_mics()
    mic_dropdown.configure(values=[d[1] for d in mic_devices])
    if mic_devices:
        mic_dropdown.set(mic_devices[0][1])

ctk.CTkButton(main_tab, text="Refresh Mics", command=refresh_devices).pack(pady=(0,10))

# ----------------- PTT Key Handling -----------------
default_ptt_key = "v"
last_ptt_key = default_ptt_key

# Create PTT Key Entry (disabled typing, click to capture)
ctk.CTkLabel(main_tab, text="PTT Key").pack()
key_entry = ctk.CTkEntry(main_tab, width=50)
key_entry.insert(0, default_ptt_key)
key_entry.configure(state="readonly")  # prevent typing
key_entry.pack(pady=(0,10))

# Capture a single key press when user clicks the entry
def capture_ptt_key(event):
    _ = event  # ignore event
    key_entry.configure(state="normal")  # temporarily allow input
    
    def on_key(event_inner):
        global last_ptt_key
        key = event_inner.char
        if key:
            key_entry.delete(0, "end")
            key_entry.insert(0, key[0])
            last_ptt_key = key[0]
        key_entry.configure(state="readonly")
        key_entry.unbind("<Key>", key_binding_id)
    
    global key_binding_id
    key_binding_id = key_entry.bind("<Key>", on_key)
    key_entry.delete(0, "end")

# Bind click to capture
key_entry.bind("<Button-1>", capture_ptt_key)

# ----------------- Slider helpers -----------------
def slider_to_entry(slider, entry):
    val = int(slider.get())
    entry.delete(0, "end")
    entry.insert(0, str(val))

def entry_to_slider(entry, slider, min_val, max_val):
    try:
        val = int(entry.get())
        if val < min_val: val = min_val
        elif val > max_val: val = max_val
        slider.set(val)
        entry.delete(0, "end")
        entry.insert(0, str(val))
    except:
        entry.delete(0, "end")
        entry.insert(0, str(int(slider.get())))

# ----------------- Threshold & Delay -----------------
threshold_frame = ctk.CTkFrame(main_tab)
threshold_frame.pack(pady=(5,10), fill="x", padx=20)
ctk.CTkLabel(threshold_frame, text="Mic Threshold").grid(row=0, column=0, sticky="w")
threshold = ctk.CTkSlider(threshold_frame, from_=1, to=100)
threshold.set(20)
threshold.grid(row=0, column=1, sticky="ew", padx=(10,5))
threshold_value_entry = ctk.CTkEntry(threshold_frame, width=50)
threshold_value_entry.grid(row=0, column=2)
threshold_value_entry.insert(0, "20")
threshold.configure(command=lambda v: slider_to_entry(threshold, threshold_value_entry))
threshold_value_entry.bind("<Return>", lambda e: entry_to_slider(threshold_value_entry, threshold, 1, 100))

delay_frame = ctk.CTkFrame(main_tab)
delay_frame.pack(pady=(5,10), fill="x", padx=20)
ctk.CTkLabel(delay_frame, text="Release Delay (ms)").grid(row=0, column=0, sticky="w")
delay = ctk.CTkSlider(delay_frame, from_=0, to=1000)
delay.set(300)
delay.grid(row=0, column=1, sticky="ew", padx=(10,5))
delay_entry = ctk.CTkEntry(delay_frame, width=50)
delay_entry.grid(row=0, column=2)
delay_entry.insert(0, "300")
delay.configure(command=lambda v: slider_to_entry(delay, delay_entry))
delay_entry.bind("<Return>", lambda e: entry_to_slider(delay_entry, delay, 0, 1000))

# ----------------- Mic Level & Status -----------------
ctk.CTkLabel(main_tab, text="Mic Level").pack(pady=(5,0))
mic_meter = ctk.CTkProgressBar(main_tab, width=300)
mic_meter.set(0)
mic_meter.pack(pady=(0,10))

status_label = ctk.CTkLabel(main_tab, text="Stopped")
status_label.pack(pady=(0,10))

button_frame = ctk.CTkFrame(main_tab)
button_frame.pack(pady=(0,20))
ctk.CTkButton(button_frame, text="Start", command=start_script).grid(row=0, column=0, padx=10)
ctk.CTkButton(button_frame, text="Stop", command=stop_script).grid(row=0, column=1, padx=10)

ctk.CTkButton(main_tab, text="Toggle Theme", command=toggle_theme).pack(pady=(0,10))

# ----------------- DEV TAB -----------------
debug_info = ctk.CTkLabel(dev_tab, text="", justify="left")
debug_info.pack(pady=10, padx=10)

def update_debug_info():
    # Always show debug info, even if not running
    selected_index = mic_names.index(mic_dropdown.get()) if mic_dropdown.get() in mic_names else -1
    info_text = (
        f"Version: 1.0.0\n"
        f"Current Volume: {current_volume:.3f}\n"
        f"Smoothed Volume: {smoothed_volume:.3f}\n"
        f"Mic Device Index: {selected_index}\n"
        f"PTT Key Held: {key_held}\n"
        f"Threshold: {threshold.get()}\n"
        f"Release Delay: {delay.get()}\n"
        f"Last PTT Key: {last_ptt_key}\n"
        f"Status: {'Listening' if running else 'Stopped'}"
    )
    debug_info.configure(text=info_text)
    root.after(100, update_debug_info)  # keep refreshing

update_gui_status()
update_debug_info()
root.mainloop()