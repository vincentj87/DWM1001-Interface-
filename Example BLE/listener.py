import serial
import time
import threading
import glob

BAUD = 115200

###############################
#   SERIAL HELPER FUNCTIONS   #
###############################

def find_port():
    ports = glob.glob("/dev/ttyUSB*")
    # On Windows you might use "COM*" or list ports differently
    return ports[0] if ports else None

def wake_shell(ser):
    """
    Wake DWM1001 shell by sending two enters within 1 second.
    Reference: Section 6.1 Usage of UART Shell Mode [cite: 816]
    """
    print("[*] Waking up shell...")
    ser.write(b"\r")
    time.sleep(0.5)
    ser.write(b"\r")
    time.sleep(0.5)

def write_slow(ser, text, delay=0.05):
    """
    Send a command slowly so DWM1001 firmware can parse it.
    """
    # Send characters
    for ch in text:
        ser.write(ch.encode())
        time.sleep(delay)
    
    # Send ENTER to execute
    ser.write(b"\r")
    time.sleep(0.1)

###############################
#    CONFIGURATION ROUTINE    #
###############################

def setup_listener(ser):
    """
    Runs the specific sequence to reset and configure the node as a Listener.
    """
    try:
        # 1. Wake shell first to ensure we can send the reset command
        wake_shell(ser)
        
        # 2. Reset the module
        # Command: reset [cite: 823, 836]
        print("[*] Sending RESET command...")
        write_slow(ser, "reset")
        
        # 3. Wait 2 seconds as requested
        print("[*] Waiting 2 seconds for reboot...")
        time.sleep(2)

        # 4. Wake shell again (Module starts in Generic mode after reset)
        wake_shell(ser)

        # 5. Set PAN ID to 0x1234
        # Command: nis <PAN_ID> 
        print("[*] Setting PAN ID to 0x1234...")
        write_slow(ser, "nis 0x1234")
        time.sleep(0.5)

        # 6. Set to Passive Mode (Listener)
        # Command: nmp 
        # Note: Changing mode usually triggers an internal reset
        print("[*] Setting Node to Passive Mode (Listener)...")
        write_slow(ser, "nmp")
        
        print("[*] Waiting for mode change reboot...")
        time.sleep(2) 

        # 7. Wake shell one last time after mode change reset
        wake_shell(ser)

        # 8. Enable CSV Listener Output
        # Command: lec [cite: 824, 850]
        print("[+] Enabling CSV Listener output...")
        write_slow(ser, "lec")

    except serial.SerialException:
        print("[-] Error during setup: Serial disconnected.")

###############################
#     UART READER THREAD      #
###############################

def uart_reader():
    global ser
    while True:
        try:
            if ser and ser.in_waiting > 0:
                # Read line, decode, and strip whitespace
                line = ser.readline().decode(errors="ignore").strip()
                if line:
                    print(f"[RX] {line}")
            time.sleep(0.01)

        except serial.SerialException:
            print("[-] USB disconnected! Waiting for reconnection...")
            ser = None
            reconnect_serial()
        except OSError:
            pass

def reconnect_serial():
    global ser
    while ser is None:
        port = find_port()
        if port:
            try:
                print(f"[+] Reconnecting to {port}...")
                ser = serial.Serial(port, BAUD, timeout=0.1)
                wake_shell(ser)
                print("[+] Reconnected!")
                return
            except:
                pass
        time.sleep(1)

###############################
#            MAIN             #
###############################

def main():
    global ser
    ser = None

    print("[+] Searching for USB device...")
    while ser is None:
        port = find_port()
        if port:
            try:
                ser = serial.Serial(port, BAUD, timeout=0.1)
                print(f"[+] Connected to {port}")
                
                # Start reading thread immediately to see output
                t = threading.Thread(target=uart_reader, daemon=True)
                t.start()

                # Run the automated configuration sequence
                setup_listener(ser)

            except Exception as e:
                print(f"[-] Connection failed: {e}")
                ser = None
        else:
            print("[-] No device found...")
            time.sleep(1)
        
        # If connected, break the search loop
        if ser: 
            break

    # Command loop
    print("\n[+] System Configured. You can type manual commands below (or 'exit').")
    try:
        while True:
            cmd = input("> ").strip()
            if cmd.lower() == "exit":
                break   
            if cmd == "":
                continue

            if ser:
                try:
                    write_slow(ser, cmd)
                except serial.SerialException:
                    print("[-] USB disconnected while sending!")
                    ser = None
                    reconnect_serial()
            else:
                print("[-] USB disconnected — waiting...")
            
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\n[+] Exiting...")

    if ser:
        ser.close()
    print("[+] Program ended.")

if __name__ == "__main__":
    main()