# import serial
# import time
# import threading
# import glob 

# # 1 DW0DA4 D2:60:E7:6E:55:30
# # 2 DW3061 DF:40:6F:1F:D7:11
# # 3 DW3068 C6:25:47:51:C2:80 


# PORTS = glob.glob("/dev/ttyUSB*")
# BAUD = 115200

# def wake_shell(ser):
#     """Send ENTER twice with delay to wake DWM1001 shell."""
#     ser.write(b"\r")
#     time.sleep(0.3)
#     ser.write(b"\r")
#     time.sleep(0.3)

# def uart_reader(ser):
#     """Threaded UART reader that prints all incoming data."""
#     while True:
#         try:
#             if ser.in_waiting > 0:
#                 line = ser.readline().decode(errors="ignore").strip()
#                 if line:
#                     print(line)
#             time.sleep(0.01)
#         except Exception:
#             break

# def main():
#     if not PORTS:
#         print("[-] No serial ports found.")
#         return
#     PORT = PORTS[0]
#     print(f"[+] Opening {PORT} ...")
#     ser = serial.Serial(PORT, BAUD, timeout=0.1)

#     # Wake shell
#     wake_shell(ser)

#     print("[+] UART Reader started.")
#     print("[+] Type commands below (or 'exit' to quit):\n")

#     # Start reader thread
#     reader_thread = threading.Thread(target=uart_reader, args=(ser,), daemon=True)
#     reader_thread.start()

#     try:
#         while True:
#             cmd = input("> ")

#             if cmd.lower() == "exit":
#                 break

#             # Send command with CR
#             ser.write((cmd + "\r").encode())

#     except KeyboardInterrupt:
#         print("\n[+] Stopped by user.")

#     ser.close()
#     print("[+] Serial port closed.")

# if __name__ == "__main__":
#     main()

# 1 DW0DA4 D2:60:E7:6E:55:30
# 2 DW3061 DF:40:6F:1F:D7:11
# 3 DW3068 C6:25:47:51:C2:80 
# 4 DW3221 CE:D8:74:92:70:83
# 5 DW323C CF:4D:5E:14:14:E3
# 6 DW3233 DD:73:23:8B:A7:0E 
# 9 DW30D4 CA:4E:FD:A7:76:6B
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
