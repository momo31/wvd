import os
import sys
import json
import time
import struct
import subprocess
from datetime import datetime

# Import external libraries
try:
    import cv2
    import numpy as np
except ImportError:
    print("Required packages (opencv-python, numpy) are missing. Attempting to install...")
    subprocess.run([sys.executable, "-m", "pip", "install", "opencv-python", "numpy"])
    import cv2
    import numpy as np

CONFIG_PATH = "config.json"
IMAGE_FOLDER = "resources/images/"
OUTPUT_FOLDER = "img"

def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"Error: {CONFIG_PATH} not found.")
        return None
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading configuration file: {e}")
        return None

def get_adb_path(emu_path):
    if not emu_path:
        return "adb"
    adb_path = emu_path
    adb_path = adb_path.replace("HD-Player.exe", "HD-Adb.exe")  # Bluestacks
    adb_path = adb_path.replace("MuMuPlayer.exe", "adb.exe")      # MuMu
    adb_path = adb_path.replace("MuMuNxDevice.exe", "adb.exe")    # MuMu
    if os.path.exists(adb_path):
        return adb_path
    print(f"Warning: Resolved ADB path '{adb_path}' does not exist. Using system default 'adb'.")
    return "adb"

def connect_device(adb_path, adb_address):
    print(f"Connecting to device at {adb_address} using ADB at '{adb_path}'...")
    try:
        # Run adb connect
        result = subprocess.run([adb_path, "connect", adb_address], capture_output=True, text=True)
        print(result.stdout.strip())
        
        # Verify connection status
        devices_result = subprocess.run([adb_path, "devices"], capture_output=True, text=True)
        if adb_address in devices_result.stdout:
            print("Successfully connected to the emulator.")
            return True
        else:
            print("Warning: Address not found in adb devices output. Connection might have failed.")
            return False
    except Exception as e:
        print(f"Error connecting to device: {e}")
        return False

def capture_screen(adb_path, serial):
    try:
        process_result = subprocess.run(
            [adb_path, "-s", serial, "exec-out", "screencap"],
            capture_output=True,
            timeout=5
        )
        if process_result.stderr:
            print(f"Capture error stderr: {process_result.stderr.decode('utf-8', errors='ignore').strip()}")
            return None
        
        raw_data = process_result.stdout
        if len(raw_data) < 12:
            return None
        
        # Parse width, height, and format
        w, h, fmt = struct.unpack("<III", raw_data[:12])
        expected_pixels = w * h * 4
        pixels_data = raw_data[12:]
        
        if len(pixels_data) > expected_pixels:
            pixels_data = pixels_data[:expected_pixels]
        elif len(pixels_data) < expected_pixels:
            return None
        
        image = np.frombuffer(pixels_data, dtype=np.uint8)
        image = image.reshape((h, w, 4))
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
        return image
    except Exception as e:
        print(f"Screen capture exception: {e}")
        return None

def load_template(filename):
    path = os.path.join(IMAGE_FOLDER, filename)
    if not os.path.exists(path):
        print(f"Template image not found: {path}")
        return None
    try:
        # Load image supporting unicode paths
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        print(f"Error loading template image '{filename}': {e}")
        return None

def check_template(screen_img, template_img):
    if screen_img is None or template_img is None:
        return 0.0
    try:
        # Resize template if it's larger than the screenshot
        t_h, t_w = template_img.shape[:2]
        s_h, s_w = screen_img.shape[:2]
        if t_h > s_h or t_w > s_w:
            scale = min(s_w / t_w, s_h / t_h)
            new_w = max(1, int(t_w * scale))
            new_h = max(1, int(t_h * scale))
            template_img = cv2.resize(template_img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        result = cv2.matchTemplate(screen_img, template_img, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        return max_val
    except Exception as e:
        print(f"Error matching template: {e}")
        return 0.0

def main():
    print("=== Android Emulator Chest Open Screenshot Utility ===")
    config = load_config()
    if not config:
        return
    
    general_config = config.get("GENERAL", {})
    emu_path = general_config.get("EMU_PATH")
    adb_address = general_config.get("ADB_ADRESS")
    
    if not adb_address:
        print("Error: ADB_ADRESS not found in config.json")
        return

    adb_path = get_adb_path(emu_path)
    
    # Establish connection
    if not connect_device(adb_path, adb_address):
        print("Continuing with default adb configuration...")

    # Load templates
    chest_opening = load_template("chestOpening.png")
    chest_flag = load_template("chestFlag.png")
    dung_flag = load_template("dungFlag.png")
    
    if chest_opening is None and chest_flag is None:
        print("Error: Neither chestOpening.png nor chestFlag.png templates could be loaded.")
        return
    
    if dung_flag is None:
        print("Warning: dungFlag.png template could not be loaded. Dungeon screen detection will be disabled.")

    print("\nStarting monitor loop. Scanning screen for chests...")
    print("Press Ctrl+C to terminate.")
    
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    
    try:
        while True:
            screen = capture_screen(adb_path, adb_address)
            if screen is None:
                time.sleep(1.0)
                continue
            
            # Check if chest is detected
            opening_val = check_template(screen, chest_opening) if chest_opening is not None else 0.0
            flag_val = check_template(screen, chest_flag) if chest_flag is not None else 0.0
            
            # Threshold: 0.8 (same as the original script)
            if opening_val >= 0.8 or flag_val >= 0.8:
                detection_type = "chestOpening" if opening_val >= 0.8 else "chestFlag"
                conf = max(opening_val, flag_val)
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Chest detected! ({detection_type} conf: {conf:.2f}). Waiting 7 seconds before capturing...")
                time.sleep(7.0)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting capture sequence...")
                
                # Create filename prefix for this chest opening event
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                capture_count = 0
                max_captures = 15  # Safety timeout (15 seconds max)
                consecutive_misses = 0
                
                # Capture loop
                for i in range(max_captures):
                    t_start = time.time()
                    
                    # Capture and save
                    cap_img = capture_screen(adb_path, adb_address)
                    if cap_img is not None:
                        file_path = os.path.join(OUTPUT_FOLDER, f"chest_{timestamp}_{capture_count}.png")
                        cv2.imwrite(file_path, cap_img)
                        print(f"  -> Saved {file_path}")
                        capture_count += 1
                        
                        # Check exit conditions
                        # 1. Dungeon screen detected
                        if dung_flag is not None:
                            dung_val = check_template(cap_img, dung_flag)
                            if dung_val >= 0.8:
                                print(f"  -> Dungeon screen detected (dungFlag conf: {dung_val:.2f}). Stopping capture.")
                                break
                        
                        # 2. Chest is no longer on screen (both opening and flag are missing for 3 consecutive seconds)
                        op_val = check_template(cap_img, chest_opening) if chest_opening is not None else 0.0
                        fl_val = check_template(cap_img, chest_flag) if chest_flag is not None else 0.0
                        if op_val < 0.5 and fl_val < 0.5:
                            consecutive_misses += 1
                            if consecutive_misses >= 3:
                                print("  -> Chest UI disappeared. Stopping capture.")
                                break
                        else:
                            consecutive_misses = 0
                    
                    # Sleep to maintain 1-second interval
                    elapsed = time.time() - t_start
                    sleep_time = max(0.0, 1.0 - elapsed)
                    time.sleep(sleep_time)
                
                print(f"Finished capture sequence. Total saved: {capture_count} screenshots.")
                print("Resuming monitor loop...")
                
            # Scan interval
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print("\nMonitor loop terminated by user.")

if __name__ == "__main__":
    main()
