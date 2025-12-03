import serial
import time
import threading
import glob
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque
import itertools

# --- CONFIGURATION ---
BAUD = 115200
HISTORY_LEN = 30 # How many past points to keep for the "trail"

# Global control and storage
tag_data = {}               # Stores tag positions: {'ID': {'x': deque, 'y': deque}}
tag_colors = {}             # Stores tag colors: {'ID': 'color_code'}
data_lock = threading.Lock()
exit_flag = threading.Event()

# Color palette for tags (uses distinct, high-contrast colors)
COLORS = ['#E6194B', '#3CB44B', '#FFE119', '#4363D8', '#F58231', '#911EB4', '#46F0F0', '#F032E6', '#BCF60C', '#FABEBE']
color_cycler = itertools.cycle(COLORS)

###############################
#   SERIAL HELPER FUNCTIONS   #
###############################

def find_port():
    ports = glob.glob("/dev/ttyUSB*")
    # Add Windows/Other OS ports if needed:
    # ports.extend(glob.glob("COM*"))
    return ports[0] if ports else None

def wake_shell(ser):
    """Wake DWM1001 shell by sending two enters."""
    ser.write(b"\r")
    time.sleep(0.1)
    ser.write(b"\r")
    time.sleep(0.1)

def write_slow(ser, text, delay=0.01):
    """Send a command slowly and execute with ENTER."""
    for ch in text:
        ser.write(ch.encode())
        time.sleep(delay)
    ser.write(b"\r")
    time.sleep(0.1)

###############################
#    CONFIGURATION ROUTINE    #
###############################

def setup_listener(ser):
    try:
        print("[*] Configuring DWM1001...")
        wake_shell(ser)
        
        # 1. Reset to clear previous state
        print("    -> Sending RESET...")
        write_slow(ser, "reset")
        time.sleep(2) 

        # 2. Re-wake shell after reset
        wake_shell(ser)

        # 3. Set PAN ID
        print("    -> Setting PAN ID to 0x1234...")
        write_slow(ser, "nis 0x1234")
        time.sleep(0.5)

        # 4. Set to Passive (Listener) Mode
        print("    -> Setting Passive Mode (nmp)...")
        write_slow(ser, "nmp")
        time.sleep(2) # Wait for mode change reset

        # 5. Final Wake & Enable Output
        wake_shell(ser)
        print("    -> Enabling CSV Output (lec)...")
        write_slow(ser, "lec")
        print("[+] Configuration Complete! Waiting for position data...")

    except serial.SerialException:
        print("[-] Error during setup. Serial link failed.")

###############################
#     DATA PARSING THREAD     #
###############################

def uart_reader(ser):
    global tag_data, tag_colors
    while not exit_flag.is_set():
        try:
            # Check if serial object is valid and open
            if ser and ser.is_open and ser.in_waiting > 0:
                line = ser.readline().decode(errors="ignore").strip()
                
                # Print the raw data to the terminal (as requested)
                if line:
                    print(f"[RAW] {line}") 
                
                # Check for position data
                if line.startswith("POS"):
                    # The observed format is POS,0,TAG_ID,X,Y,Z,QF,EXTRA
                    parts = line.split(',')
                    
                    # Ensure we have enough parts
                    if len(parts) >= 5:
                        tag_id = parts[2]  # Tag ID is at index 2
                        try:
                            # X and Y coordinates are at indices 3 and 4, and appear to be in meters
                            x = float(parts[3]) 
                            y = float(parts[4])
                            
                            with data_lock:
                                if tag_id not in tag_data:
                                    # Initialize new tag entry and assign a color
                                    tag_data[tag_id] = {
                                        'x': deque(maxlen=HISTORY_LEN),
                                        'y': deque(maxlen=HISTORY_LEN)
                                    }
                                    tag_colors[tag_id] = next(color_cycler)
                                
                                # Append new coordinates
                                tag_data[tag_id]['x'].append(x)
                                tag_data[tag_id]['y'].append(y)

                                # Print parsed data to the terminal (as requested)
                                print(f"[POS] Tag:{tag_id}, X:{x:.2f}m, Y:{y:.2f}m")
                                
                        except ValueError:
                            # Skip if conversion to float fails (e.g., malformed data)
                            pass 
            else:
                time.sleep(0.01)

        except serial.SerialException as e:
            # This happens if the device is unplugged
            print(f"[-] Reader serial error: {e}")
            break 
        except Exception as e:
            # Catch all other exceptions, e.g., during shutdown
            if not exit_flag.is_set():
                print(f"[-] Unexpected Reader error: {e}")
            break


###############################
#      PLOTTING FUNCTION      #
###############################

def update_plot(frame):
    plt.cla() # Clear axis
    
    all_x = []
    all_y = []

    with data_lock:
        for tag_id, coords in tag_data.items():
            if coords['x']:
                color = tag_colors[tag_id]
                
                # Plot the trail (lighter color, dashed line)
                plt.plot(coords['x'], coords['y'], color=color, linestyle='--', alpha=0.5)
                
                # Plot the current position (solid dot)
                current_x = coords['x'][-1]
                current_y = coords['y'][-1]
                
                # Scatter plot for the current position with Label
                plt.scatter(current_x, current_y, s=150, color=color, 
                            label=f"Tag {tag_id} ({current_x:.2f}, {current_y:.2f})")
                
                # Add the tag ID label next to the dot
                plt.text(current_x + 0.15, current_y + 0.15, tag_id, color=color, fontsize=10)

                # Collect all coordinates for dynamic axis calculation
                all_x.extend(coords['x'])
                all_y.extend(coords['y'])

    # --- Dynamic Axis Adjustment ---
    if all_x and all_y:
        # Determine the min/max X and Y coordinates
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)

        # Calculate a buffer (e.g., 1 meter) for margins
        buffer = 1.0 

        # Set the limits dynamically, handling cases where min and max are the same
        x_range = max(max_x - min_x, 2 * buffer)
        y_range = max(max_y - min_y, 2 * buffer)
        
        plt.xlim(min_x - buffer, max_x + buffer)
        plt.ylim(min_y - buffer, max_y + buffer)
    else:
        # Fallback for when no data is received yet
        plt.xlim(-1, 5) 
        plt.ylim(-1, 5)
        
    plt.xlabel("X (meters)")
    plt.ylabel("Y (meters)")
    plt.title(f"Real-Time Tag Tracking (Tags: {len(tag_data)})")
    plt.grid(True)
    
    # Only try to show legend if tags have been plotted
    if tag_data:
        plt.legend(loc='upper right', fontsize=8)

###############################
#            MAIN             #
###############################

def main():
    global ser
    ser = None
    
    port = find_port()
    if not port:
        print("[-] No DWM1001 found on USB. Check cable and permissions.")
        return

    try:
        # 1. Setup Serial Connection
        print(f"[+] Connecting to {port}...")
        ser = serial.Serial(port, BAUD, timeout=0.1)
        
        # 2. Run configuration sequence
        setup_listener(ser)

        # 3. Start background thread to read UART data
        t = threading.Thread(target=uart_reader, args=(ser,), daemon=True)
        t.start()

        # 4. Start the GUI Plot
        print("\n[+] Starting Plotter... Use Ctrl+C in the terminal to exit gracefully.")
        fig = plt.figure()
        # Set cache_frame_data=False to suppress the Matplotlib warning
        ani = animation.FuncAnimation(fig, update_plot, interval=100, cache_frame_data=False) 
        plt.show()

    except KeyboardInterrupt:
        print("\n[+] Exiting gracefully...")
    
    except Exception as e:
        print(f"[-] An unexpected error occurred in main: {e}")

    finally:
        # Cleanup routine
        exit_flag.set() # Signal all threads to stop
        time.sleep(0.5) # Give reader thread time to exit
        if 'ser' in locals() and ser and ser.is_open:
            ser.close()
            print("[+] Serial closed.")
        print("[+] Program ended.")

if __name__ == "__main__":
    main()