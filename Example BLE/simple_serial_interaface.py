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
    return ports[0] if ports else None

def wake_shell(ser):
    """Wake DWM1001 shell by sending two enters."""
    time.sleep(0.2)
    ser.write(b"\r")
    time.sleep(0.2)
    ser.write(b"\r")
    time.sleep(0.2)

def write_slow(ser, text, delay=0.05):
    """apg
    Send a command slowly so DWM1001 firmware can parse it.
    Recommended delay between characters: 3–5 ms
    """
    for ch in text:
        ser.write(ch.encode())
        time.sleep(delay)

    ser.write(b"\r")   # send ENTER
    time.sleep(0.01)

###############################
#     UART READER THREAD      #
###############################

def uart_reader():
    global ser
    while True:
        try:
            if ser and ser.in_waiting > 0:
                line = ser.readline().decode(errors="ignore").strip()
                if line:
                    print(line)
            time.sleep(0.01)

        except serial.SerialException:
            print("[-] USB disconnected! Waiting for reconnection...")
            ser = None
            reconnect_serial()

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
                wake_shell(ser)
                print(f"[+] Connected to {port}")
            except:
                ser = None
        else:
            print("[-] No device found...")
        time.sleep(1)

    # Start reader thread
    threading.Thread(target=uart_reader, daemon=True).start()

    # Command loop
    print("[+] Ready. Type commands (e.g., aps 100 200 300). Type exit to quit.")
    try:
        while True:
            cmd = input("> ").strip()
            if cmd.lower() == "exit":
                break
            if cmd == "":
                continue

            if ser:
                try:
                    write_slow(ser, cmd)   # <----- FIXED HERE
                except serial.SerialException:
                    print("[-] USB disconnected while sending!")
                    ser = None
                    reconnect_serial()
            else:
                print("[-] USB disconnected — waiting...")
    except KeyboardInterrupt:
        print("\n[+] Exiting...")

    if ser:
        ser.close()
    print("[+] Program ended.")

if __name__ == "__main__":
    main()
