import cv2
import numpy as np
import time
import pydirectinput
import subprocess
import os
from datetime import datetime
from mss import mss

# --- CONFIGURATION ---
TARGET_EVENT = "turbo_squad"  
CONFIDENCE_THRESHOLD = 0.85     
CHECKBOX_OFFSET_X = 325         
MAX_SCROLLS = 5                 

# --- DEBUG & SAFETY CONFIGURATION ---
CONSECUTIVE_CRASH_LIMIT = 3     # Stop the bot if it crashes/fails this many times in a row
g_consecutive_crashes = 0       # Global counter for consecutive failures

# --- NITRO & RESOLUTION CONFIGURATION ---
NITRO_50_PERCENT_COORD = (1440, 420) 
CLICK_NITRO_ZONE = (1800, 950)       
CLICK_DRIFT_ZONE = (850, 950)        

pydirectinput.PAUSE = 0.05

# --- GLOBAL RAM CACHE FOR IMAGES ---
LOADED_TEMPLATES = {}

def preload_templates():
    """
    Pre-loads all image files from the disk into the RAM cache at startup.
    This eliminates disk read latency (I/O bottlenecks) during the race loop [4].
    """
    print("[*] Pre-loading all templates into RAM...")
    files = [
        "multiplayer_btn.png", "multiplayer_btn_black.png", "get_ready_btn.png", 
        "filter_btn.png", "owned_label.png", "ascending_label.png",
        "order_toggle_btn.png", "stars_label.png", "done_btn.png", 
        "fuel_can.png", "play_btn.png", "next_btn.png", "home_btn.png",
        "nitro_x2_icon.png", "nitro_normal_icon.png", "ramp_barrel_icon.png", 
        "reversed_ramp_barrel_icon.png", "ramp_flat_icon.png"
    ]
    for f in files:
        img = cv2.imread(f, 0)
        if img is not None:
            LOADED_TEMPLATES[f] = img
        else:
            print(f"[-] Warning: Template '{f}' not found on disk. Ensure it is placed in this directory.")

def capture_screen():
    with mss() as sct:
        monitor = sct.monitors[1]
        screenshot = np.array(sct.grab(monitor))
        gray = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2GRAY)
        return gray, screenshot

def find_template(template_path, gray_screen):
    """
    Pulls the template from the RAM cache instead of reading from disk [4].
    Falls back to disk read if the template was not cached at startup.
    """
    template = LOADED_TEMPLATES.get(template_path)
    if template is None:
        template = cv2.imread(template_path, 0)
        if template is None:
            return None
        LOADED_TEMPLATES[template_path] = template

    h, w = template.shape
    result = cv2.matchTemplate(gray_screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    
    if max_val >= CONFIDENCE_THRESHOLD:
        center_x = max_loc[0] + int(w / 2)
        center_y = max_loc[1] + int(h / 2)
        return (center_x, center_y)
    return None

def click_template_safely(template_input, label, max_attempts=5, offset_x=0, offset_y=0):
    templates = [template_input] if isinstance(template_input, str) else template_input
    
    for attempt in range(max_attempts):
        gray, _ = capture_screen()
        
        for t_name in templates:
            coords = find_template(t_name, gray)
            if coords:
                click_x = coords[0] + offset_x
                click_y = coords[1] + offset_y
                pydirectinput.moveTo(click_x, click_y)
                time.sleep(0.2)
                pydirectinput.click()
                print(f"[+] Clicked {label} (matched: {t_name}).")
                return True
                
        time.sleep(1.0)
    return False

# --- SYSTEM PROCESS CONTROL & DEBUG TELEMETRY ---

def log_crash_telemetry(run_num):
    """
    Telemetry recorder. Saves a visual snapshot of the screen at failure, 
    logs a timestamped text audit, and evaluates consecutive crash safety limits.
    """
    global g_consecutive_crashes
    g_consecutive_crashes += 1
    
    # 1. Create debug folder if missing
    if not os.path.exists("debug"):
        os.makedirs("debug")
        
    timestamp = int(time.time())
    readable_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 2. Capture and save failure screenshot
    try:
        _, color = capture_screen()
        screenshot_path = f"debug/crash_run_{run_num}_{timestamp}.png"
        cv2.imwrite(screenshot_path, color)
        print(f"[DEBUG] Failure state screenshot saved to {screenshot_path}")
    except Exception as e:
        print(f"[-] Debug Error: Failed to write screenshot: {e}")
        
    # 3. Write to continuous text log
    try:
        log_path = "debug/crash_log.txt"
        with open(log_path, "a") as log_file:
            log_file.write(f"[{readable_time}] Run #{run_num} FAILED. "
                           f"Consecutive failure count: {g_consecutive_crashes}/{CONSECUTIVE_CRASH_LIMIT}\n")
        print(f"[DEBUG] Crash event logged in {log_path}")
    except Exception as e:
        print(f"[-] Debug Error: Failed to append to text log: {e}")
        
    # 4. Enforce Safety Threshold to prevent runaway system loops
    if g_consecutive_crashes >= CONSECUTIVE_CRASH_LIMIT:
        print(f"\n[FATAL ERROR] Game failed consecutively {g_consecutive_crashes} times.")
        print("[!] Stopping automation chain to prevent runaway OS execution. Human review required.")
        input("[*] Resolve the issue, then press Enter to exit the script...")
        raise SystemExit

def is_game_running():
    """
    Checks the Windows tasklist in CSV format.
    CSV output prevents Windows from truncating our 29-character process name.
    """
    try:
        output = subprocess.check_output(
            'tasklist /fo csv /fi "IMAGENAME eq Asphalt9_Steam_x64_rtl.exe"', 
            shell=True
        ).decode('utf-8', errors='ignore')
        return "Asphalt9_Steam_x64_rtl" in output
    except Exception:
        return False

def force_close_game():
    """Executes a hard process termination on the game client to clear freezes [5]."""
    print("[!] Force closing Asphalt 9 client...")
    try:
        subprocess.call(
            'taskkill /F /IM Asphalt9_Steam_x64_rtl.exe', 
            shell=True, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
    except Exception:
        pass
    time.sleep(3.0) 

def ensure_game_running():
    """Verifies process state and launches the game client if not present [5]."""
    if is_game_running():
        return True

    print("[*] Game client is not running. Initiating clean launch...")
    game_path = r"C:\Program Files (x86)\Steam\steamapps\common\Asphalt 9 Legends\Asphalt9_Steam_x64_rtl.exe"
    working_dir = r"C:\Program Files (x86)\Steam\steamapps\common\Asphalt 9 Legends"

    try:
        subprocess.Popen([game_path], cwd=working_dir)
        print("[*] Game executable spawned. Waiting 40 seconds for boot sequence...")
        time.sleep(40.0) 

        print("[*] Sending focus click to game window...")
        pydirectinput.click(960, 540) 
        time.sleep(2.0)
        return True
    except Exception as e:
        print(f"[-] Critical: Failed to launch game: {e}")
        return False

# --- MENU NAVIGATION CODE ---

def recover_to_main_menu():
    print("[!] Automation chain broke before starting the race. Initializing Recovery Routine...")
    pydirectinput.press('esc')
    time.sleep(1.0)
    
    for attempt in range(3):
        if click_template_safely("home_btn.png", "Home Button", max_attempts=5):
            print("[+] Successfully recovered back to Main Menu.")
            time.sleep(4.0) 
            return True
        pydirectinput.press('esc')
        time.sleep(1.0)
        
    print("[-] Critical: Recovery routine failed.")
    return False

def scroll_right_page():
    """
    Replaces the unstable mouse-drag with deterministic keyboard navigation [4].
    Presses the Right Arrow key 6 times (one click per car) to shift to the next page.
    """
    print("[*] Shifting garage view right by 1 page (6 cars)...")
    for _ in range(6):
        pydirectinput.press('right')
        time.sleep(0.15) # 150ms buffer to let the UI register the movement
    time.sleep(1.5) # Wait for page transition rendering to stabilize

def is_purple_fuel(color_img, x, y, w, h):
    crop = color_img[y:y+h, x:x+w]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGRA2BGR)
    hsv = cv2.cvtColor(hsv, cv2.COLOR_BGR2HSV)
    lower_purple = np.array([130, 80, 80])
    upper_purple = np.array([170, 255, 255])
    mask = cv2.inRange(hsv, lower_purple, upper_purple)
    return cv2.countNonZero(mask) > 10

def find_fueled_cars():
    template = LOADED_TEMPLATES.get("fuel_can.png")
    if template is None: return []
    h, w = template.shape
    gray_screen, color_screen = capture_screen()
    res = cv2.matchTemplate(gray_screen, template, cv2.TM_CCOEFF_NORMED)
    loc = np.where(res >= CONFIDENCE_THRESHOLD)
    raw_points = []
    for pt in zip(*loc[::-1]):
        if not any(np.linalg.norm(np.array(pt) - np.array(p)) < 40 for p in raw_points):
            raw_points.append(pt)
    fueled_car_coords = []
    for pt in raw_points:
        x, y = pt[0], pt[1]
        if is_purple_fuel(color_screen, x, y, w, h):
            fueled_car_coords.append((x + 100, y + 150))
    return sorted(fueled_car_coords, key=lambda p: (p[1] // 150, p[0]))

def select_active_car():
    """
    Dynamic Step-Scanner. 
    Checks the screen, and if no fuel is found, shifts the garage right 
    by exactly 1 car at a time, stopping the instant fuel is detected [4].
    """
    max_steps = 25 # Loop up to your total count of 25 cars
    
    for step in range(max_steps):
        print(f"[*] Scanning garage (Step {step + 1}/{max_steps})...")
        fueled_cars = find_fueled_cars()
        
        if fueled_cars:
            # The instant we see a fueled car on the screen, click it! [4]
            target = fueled_cars[0]
            print(f"[+] Active car detected at step {step + 1}. Selecting card at ({target[0]}, {target[1]})...")
            pydirectinput.click(target[0], target[1])
            return True
            
        # If no fuel is visible, shift right by exactly 1 car to reveal the next candidate [4]
        if step < max_steps - 1:
            print("[*] No fuel visible. Shifting right by 1 car...")
            pydirectinput.press('right')
            time.sleep(0.2) # Wait 200ms for the UI slide animation to complete
            
    print("[-] Critical: Stepped through all 25 slots and found 0 cars with fuel.")
    return False

def apply_garage_filters():
    if not click_template_safely("filter_btn.png", "Filter Button"): return False
    time.sleep(1.5) 
    if not click_template_safely("owned_label.png", "Owned Checkbox", offset_x=CHECKBOX_OFFSET_X): return False
    time.sleep(0.5)
    gray, _ = capture_screen()
    if find_template("ascending_label.png", gray):
        if not click_template_safely("order_toggle_btn.png", "Order Toggle Button"): return False
        time.sleep(0.5)
    if not click_template_safely("stars_label.png", "Stars Checkbox", offset_x=CHECKBOX_OFFSET_X): return False
    time.sleep(0.5)
    return click_template_safely("done_btn.png", "Done Button")

# --- ACTIVE RACE CODE ---

def check_nitro_bar_50(color_screen):
    """
    Checks if the nitro bar is at or above 50% by looking at a specific pixel's color.
    """
    x, y = NITRO_50_PERCENT_COORD
    b, g, r = color_screen[y, x][:3]
    return r > 200 and g > 150

def select_best_path(gray_screen):
    """
    Scans a restricted horizontal Region of Interest (ROI) at the top of the screen
    for TouchDrive path icons and clicks according to priority.
    """
    # Define vertical bounds for the TouchDrive icons on 1080p
    roi_y_start = 1300
    roi_y_end = 1800
    
    # Crop the grayscale image to our path region (highly accelerates CV processing)
    roi_gray = gray_screen[roi_y_start:roi_y_end, :]

    priority_tiers = [
        [("nitro_x2_icon.png", "X2 Nitro")],
        [("nitro_normal_icon.png", "Normal Nitro")],
        [("ramp_barrel_icon.png", "Barrel Roll"), ("reversed_ramp_barrel_icon.png", "Barrel Roll 2"), ("ramp_flat_icon.png", "Flat Ramp")]
    ]
    
    for tier in priority_tiers:
        for file_name, label in tier:
            try:
                # Search inside the smaller cropped region
                coords = find_template(file_name, roi_gray)
                if coords:
                    # Translate coordinates back to full-screen coordinates
                    click_x = coords[0]
                    click_y = coords[1] + roi_y_start
                    
                    pydirectinput.click(click_x, click_y)
                    print(f"[+] Selected Path: {label}!")
                    return True
            except Exception as e:
                pass
    return False

def run_active_race():
    """Active racing loop using a blind, non-blocking time-based state machine."""
    print("[*] Waiting 20 seconds for the race to start...")
    time.sleep(20.0)
    print("[+] Race active! Commencing blind autopilot...")
    
    drive_state = 0       
    state_timer = time.time()
    next_btn_coords = None

    while True:
        try:
            gray, color = capture_screen()

            # Robustness guard: Ensure the process hasn't suddenly terminated mid-race [5]
            if not is_game_running():
                print("[-] Alert: Game process terminated unexpectedly during race.")
                break

            next_btn_coords = find_template("next_btn.png", gray)
            if next_btn_coords:
                print("[+] Results screen detected. Breaking active race loop.")
                break

            # Path Selection Manager (Now running on cropped screen and RAM cache)
            select_best_path(gray)

            # Blind Driving State Machine (Non-blocking)
            current_time = time.time()
            elapsed = current_time - state_timer

            if drive_state == 0:
                pydirectinput.click(CLICK_NITRO_ZONE[0], CLICK_NITRO_ZONE[1])
                drive_state = 1
                state_timer = current_time  

            elif drive_state == 1:
                if elapsed >= 0.5:
                    pydirectinput.click(CLICK_NITRO_ZONE[0], CLICK_NITRO_ZONE[1])
                    print("[+] Nitro double-tap executed!")
                    drive_state = 2
                    state_timer = current_time  

            elif drive_state == 2:
                if elapsed >= 3.5:
                    pydirectinput.click(CLICK_DRIFT_ZONE[0], CLICK_DRIFT_ZONE[1])
                    print("[+] Drift initiated!")
                    drive_state = 3
                    state_timer = current_time

            elif drive_state == 3:
                if elapsed >= 1.0:
                    drive_state = 0  
                    state_timer = current_time

            time.sleep(0.02)

        except Exception as e:
            pass

    # Process exit validation: If the game crashed, skip post-race clicks [5]
    if not is_game_running():
        return

    print("[*] Exiting results screen...")
    time.sleep(2.0)
    
    pydirectinput.moveTo(next_btn_coords[0], next_btn_coords[1])
    time.sleep(0.2)
    pydirectinput.click()
    print("[+] Clicked First NEXT Button.")
    
    time.sleep(4.0)
    
    pydirectinput.click()
    print("[+] Clicked Second NEXT Button.")
    time.sleep(4.0)
    print("[+] Transitioning back to lobby...")

# --- SEAMLESS CYCLE CONTROLLER ---

def execute_full_cycle():
    """
    State-Hand-off Controller.
    Returns:
      - "SUCCESS" if the run finished and completed normally.
      - "RECOVERED" if a menu error occurred but we successfully soft-recovered to Lobby [4].
      - "FAILED" if an error occurred and the soft recovery failed (hard crash detected) [5].
    """
    print("\n--- ENTERING MENU STATE ---")
    
    try:
        gray, _ = capture_screen()
        
        # 1. State check: Are we already on the Event Lobby?
        if find_template("get_ready_btn.png", gray):
            print("[*] Detected Event Lobby directly. Skipping main menu navigation.")
            
        # 2. State check: Is the Multiplayer Tab already selected/active (black)?
        elif find_template("multiplayer_btn_black.png", gray):
            print("[*] Detected Multiplayer button already in selected (black) state. Skipping tab navigation.")
            # Jump straight to clicking the event
            event_file = f"{TARGET_EVENT}_btn.png"
            if not click_template_safely(event_file, f"Event: {TARGET_EVENT}", max_attempts=10): 
                raise Exception("Failed to find Target Event Card")
            time.sleep(3.0)
            
        else:
            # 3. Otherwise: Perform the standard main menu navigation
            print("[*] Navigating from Main Menu...")
            target_templates = ["multiplayer_btn.png", "multiplayer_btn_black.png"]
            if not click_template_safely(target_templates, "Multiplayer Tab", max_attempts=10):  
                raise Exception("Failed to find Multiplayer Tab")
            time.sleep(3.0)
            
            event_file = f"{TARGET_EVENT}_btn.png"
            if not click_template_safely(event_file, f"Event: {TARGET_EVENT}", max_attempts=10): 
                raise Exception("Failed to find Target Event Card")
            time.sleep(3.0) 

        # Click GET READY to open the garage
        if not click_template_safely("get_ready_btn.png", "GET READY Button", max_attempts=10): 
            raise Exception("Failed to find GET READY button")
        time.sleep(3.0) 

        if not apply_garage_filters(): 
            raise Exception("Failed to apply garage filters")
        time.sleep(2.0) 

        if not select_active_car():
            raise Exception("Out of vehicles with fuel")
        time.sleep(2.0)

        # Click Play to start the race
        if not click_template_safely("play_btn.png", "PLAY Button", max_attempts=10): 
            raise Exception("Failed to find PLAY button")

    except Exception as e:
        print(f"[-] Error in navigation chain: {e}")
        
        # Soft Recovery check [4]:
        if recover_to_main_menu():
            return "RECOVERED"
        else:
            return "FAILED"

    # --- PHASE 2: HAND-OFF TO ACTIVE RACING ---
    print("\n--- HANDING OFF TO ACTIVE RACE STATE ---")
    run_active_race()
    
    return "SUCCESS"

if __name__ == "__main__":
    preload_templates()
    
    run_count = 1
    while True:
        print(f"\n===========================================")
        print(f"      COMMENCING AUTOMATION RUN #{run_count}")
        print(f"===========================================")
        
        # 1. Ensure the game process is running and focused before starting the run [5]
        ensure_game_running()
        
        # 2. Execute full cycle and analyze the specific outcome status [5]
        run_status = execute_full_cycle()
        
        if run_status == "FAILED":
            # Hard crash recovery [5]
            log_crash_telemetry(run_count)
            print("[-] Run failed and soft-recovery failed. Force-restarting game client...")
            force_close_game()
            time.sleep(3.0)
            
        elif run_status == "RECOVERED":
            # Soft recovery [4]
            print("[+] Soft-recovery successful. Starting next attempt without re-booting client.")
            time.sleep(3.0)
            
        else: # "SUCCESS"
            # Standard completed run
            if g_consecutive_crashes > 0:
                print(f"[DEBUG] Active run successful. Resetting consecutive crash counter (was {g_consecutive_crashes}).")
                g_consecutive_crashes = 0
            run_count += 1