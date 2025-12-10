import serial
import time
import threading
import glob
import paho.mqtt.client as mqtt
import json 
# --- Global Configuration ---
BAUD = 115200
ser = None
mqtt_client = None
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "dwm1001/pos_"
MQTT_USER = "orangepi"
MQTT_PASS = "secret123"

###########################################
#   SERIAL HELPER FUNCTIONS
###########################################

def find_port():
    """Attempts to find the serial port for the DWM1001."""
    ports = []
    # Unix/Linux devices
    ports.extend(glob.glob("/dev/ttyUSB*"))
    ports.extend(glob.glob("/dev/ttyACM*"))
    # Windows devices
    ports.extend(glob.glob("COM*"))
    
    # Return the first found port, or None
    return ports[0] if ports else None

def wake_shell(ser):
    """
    Wake DWM1001 shell by sending two carriage returns.
    Crucial for entering command mode. Delays increased for stability.
    """
    if not ser: return
    print("[*] Waking shell...")
    # Send first CR
    ser.write(b"\r")
    time.sleep(0.5) # Increased delay
    # Send second CR
    ser.write(b"\r")
    time.sleep(0.5) # Increased delay

def write_slow(ser, text, delay=0.05):
    """
    Send a command slowly to the DWM1001 to ensure the firmware
    can process each character without corruption. The post-command
    delay is also increased to ensure the module stabilizes.
    """
    if not ser: return
    for ch in text:
        ser.write(ch.encode())
        time.sleep(delay) # Slightly increased character delay
    # Send ENTER (Carriage Return) to execute the command
    ser.write(b"\r")
    time.sleep(0.5) # Increased post-command execution delay

###########################################
#   MQTT PARSING AND PUBLISH
###########################################

def parse_and_publish(line):
    """
    Parses a DWM1001 POS message (e.g., POS,1,4521,0.5,1.2,0.0,100)
    and publishes the data to the MQTT broker.
    """
    # Check for the expected message start
    if not line.startswith("POS"):
        return
        
    parts = line.split(",")
    # Expected length for a full POS message (POS, nodeid, tagid, x, y, z, qf)
    if len(parts) < 7:
        return
        
    try:
        # Extract data fields
        # parts[0] = "POS"
        # parts[1] = Node ID (Anchor/Tag - ignored here)
        tag_id = parts[2]
        x = float(parts[3])
        y = float(parts[4])
        z = float(parts[5])
        qf = int(parts[6].split()[0]) # Extract quality factor, handling potential extra data/newline
        
    except ValueError:
        # Handle cases where conversion to float/int fails
        return
        
    payload = {
        "id": tag_id,
        "x": x,
        "y": y,
        "z": z,
        "qf": qf
    }
    
    # Publish as a JSON string (or just a string, depending on broker config)
    # Note: The original request used str(payload), which results in a Python dictionary string
    mqtt_client.publish(MQTT_TOPIC+tag_id, json.dumps(payload))
    print(f"[MQTT] Published data for {tag_id}")

###########################################
#   UART READER THREAD
###########################################

def uart_reader():
    """
    Thread function to continuously read data from the serial port.
    """
    global ser
    while True:
        try:
            # Check if serial object is valid and data is waiting
            if ser and ser.in_waiting > 0:
                # Read line, decode, and strip whitespace
                line = ser.readline().decode(errors="ignore").strip()
                if line:
                    print(f"[RX] {line}")
                    # Process the line for MQTT publishing
                    parse_and_publish(line)
            time.sleep(0.01)
        except serial.SerialException:
            print("[-] Serial disconnected! Waiting for reconnect...")
            # Set ser to None to trigger the reconnection logic in the main thread
            ser = None
            reconnect_serial()
        except OSError:
            # Catch common OS errors like 'Bad file descriptor'
            pass
        except Exception as e:
            # General exception handling for the thread
            print(f"[-] Reader thread error: {e}")

def reconnect_serial():
    """Handles the attempt to reconnect the serial port."""
    global ser
    while ser is None:
        port = find_port()
        if port:
            try:
                print(f"[+] Reconnecting to {port}...")
                ser = serial.Serial(port, BAUD, timeout=0.1)
                wake_shell(ser)
                print("[+] Reconnected!")
                # Re-run setup in case module state was lost
                setup_listener(ser)
                return
            except Exception as e:
                print(f"[-] Reconnection attempt failed: {e}")
                ser = None # Ensure loop continues if connection fails
        time.sleep(1)


###########################################
#   CONFIGURATION ROUTINE (Robust version)
###########################################

def setup_listener(ser):
    """
    Runs the specific sequence to reset and configure the node as a Passive Listener,
    incorporating necessary time delays and wake-up calls.
    """
    if not ser:
        print("[-] Setup aborted: Serial port is not open.")
        return
    try:
        # 1. Wake shell first to ensure we can send the reset command
        wake_shell(ser)
        
        # 2. Reset the module
        print("[*] Sending RESET command...")
        write_slow(ser, "reset")
        
        # 3. Wait for reboot
        print("[*] Waiting 2 seconds for reboot...")
        time.sleep(2)
        
        # 4. Wake shell again (Module starts in Generic mode after reset)
        wake_shell(ser)
        
        # 5. Set PAN ID to 0x1234
        print("[*] Setting PAN ID to 0x1234...")
        write_slow(ser, "nis 0x1234")
        time.sleep(0.5)
        
        # 6. Set to Passive Mode (Listener)
        print("[*] Setting Node to Passive Mode (Listener)...")
        write_slow(ser, "nmp")
        
        # Wait for mode change reboot (often happens after nmp)
        print("[*] Waiting 2 seconds for mode change reboot...")
        time.sleep(2) 
        
        # 7. Wake shell one last time after mode change reset
        wake_shell(ser)
        
        # 8. Enable CSV Listener Output
        print("[+] Enabling CSV Listener output (lec)...")
        write_slow(ser, "lec")
        
        print("\n[+] Listener configured successfully.")
        
    except serial.SerialException as e:
        print(f"[-] Configuration error: Serial disconnected during setup: {e}")
    except Exception as e:
        print(f"[-] Configuration error: {e}")

###########################################
#   MAIN
###########################################

def connect_serial_initial():
    """Initial connection loop for the main function."""
    global ser
    while True:
        port = find_port()
        if port:
            try:
                print(f"[+] Connecting to {port}...")
                ser = serial.Serial(port, BAUD, timeout=0.1)
                print(f"[+] Serial Connected to {port}")
                # We defer wake_shell until setup_listener to ensure the timing is right
                return ser
            except Exception as e:
                print(f"[-] Failed to connect to {port}: {e}")
        else:
            print("[-] No USB device found...")
        time.sleep(1)

def main():
    global ser, mqtt_client
    
    # --- MQTT Setup ---
    print(f"[+] Setting up MQTT client for {MQTT_BROKER}:{MQTT_PORT}...")
    try:
        mqtt_client = mqtt.Client()
        mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start() # Start a background thread to handle network traffic
        print("[+] MQTT Connected and loop started.")
    except Exception as e:
        print(f"[-] Failed to connect to MQTT: {e}. Running without MQTT.")
        # If MQTT fails, we might still want to proceed with serial logic
    
    # --- Serial Connection and Setup ---
    ser = connect_serial_initial()

    # Start the UART reader thread immediately
    t = threading.Thread(target=uart_reader, daemon=True)
    t.start()
    
    # Run the configuration routine on the successfully connected port
    setup_listener(ser)
    
    # --- Command Loop ---
    print("\n[+] System running. Type commands or 'exit'.\n")
    try:
        while True:
            cmd = input("> ").strip()
            if cmd == "":
                continue
            if cmd.lower() == "exit":
                break
                
            if ser:
                write_slow(ser, cmd)
            else:
                print("[-] USB disconnected — waiting for reconnection...")
                reconnect_serial()
                
    except KeyboardInterrupt:
        print("\n[+] Stopping...")
        
    # --- Cleanup ---
    if mqtt_client:
        mqtt_client.loop_stop()
        print("[+] MQTT loop stopped.")
        
    if ser:
        ser.close()
        print("[+] Serial port closed.")
        
    print("[+] Program ended.")

if __name__ == "__main__":
    main()