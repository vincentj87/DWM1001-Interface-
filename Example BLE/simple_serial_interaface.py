#this code is used to communicate with a DWM1001C device over a serial interface, allowing sending commands and receiving responses via UART


import serial
import time
import threading
import glob

BAUD = 115200

def find_port():
    """Return first /dev/ttyUSB* port or None."""
    ports = glob.glob("/dev/ttyUSB*")
    return ports[0] if ports else None

def wake_shell(ser):
    """Send ENTER twice with delay to wake DWM1001 shell."""
    ser.write(b"\r")
    time.sleep(0.3)
    ser.write(b"\r")
    time.sleep(0.3)

def uart_reader():
    """Thread that continuously reads UART and handles disconnects."""
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

        except Exception:
            pass

def reconnect_serial():
    """Wait until the USB device reappears and reopen serial port."""
    global ser

    while ser is None:
        port = find_port()
        if port:
            try:
                print(f"[+] Reconnecting to {port}...")
                ser = serial.Serial(port, BAUD, timeout=0.1)
                wake_shell(ser)
                print("[+] Reconnected successfully!")
                return
            except Exception:
                pass
        time.sleep(1)

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
            except Exception:
                ser = None
        else:
            print("[-] No device found. Waiting...")
        time.sleep(1)

    # Start UART reader thread
    threading.Thread(target=uart_reader, daemon=True).start()

    # User command loop
    try:
        while True:
            cmd = input("> ")
            if cmd.lower() == "exit":
                break

            if ser:
                try:
                    ser.write((cmd + "\r").encode())
                except serial.SerialException:
                    print("[-] USB disconnected while sending!")
                    ser = None
                    reconnect_serial()
            else:
                print("[-] USB disconnected — waiting for reconnection...")

    except KeyboardInterrupt:
        print("\n[+] Stopped by user.")

    if ser:
        ser.close()

    print("[+] Program ended.")

if __name__ == "__main__":
    main()
