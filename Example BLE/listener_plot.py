import serial
import time
import threading
import glob
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

BAUD = 115200
ser = None

# Store tag XY positions
tag_positions = {}   # {tag_id: (x, y)}

###############################
#   SERIAL HELPER FUNCTIONS   #
###############################

def find_port():
    ports = glob.glob("/dev/ttyUSB*")
    return ports[0] if ports else None

def wake_shell(ser):
    print("[*] Waking up shell...")
    ser.write(b"\r")
    time.sleep(0.4)
    ser.write(b"\r")
    time.sleep(0.4)

def write_slow(ser, text, delay=0.05):
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
        # Wake shell
        wake_shell(ser)

        # Reset the module
        print("[*] Sending RESET...")
        write_slow(ser, "reset")
        time.sleep(2)

        # Wake shell after reboot
        wake_shell(ser)

        # Set PAN ID
        print("[*] Setting PAN ID to 0x1234...")
        write_slow(ser, "nis 0x1234")
        time.sleep(0.5)

        # Set passive mode (listener)
        print("[*] Setting Listener Mode...")
        write_slow(ser, "nmp")
        time.sleep(2)

        # Wake shell again
        wake_shell(ser)

        # Enable CSV output
        print("[+] Starting CSV listener output...")
        write_slow(ser, "lec")

    except serial.SerialException:
        print("[-] Serial disconnected during setup!")


###############################
#     UART READER THREAD      #
###############################

def uart_reader():
    global ser, tag_positions
    while True:
        try:
            if ser and ser.in_waiting > 0:
                line = ser.readline().decode(errors="ignore").strip()

                if line:
                    print(f"[RX] {line}")

                    # Only parse POS lines
                    if line.startswith("POS,"):
                        # Example:
                        # POS,0,30D4,1.19,2.22,-0.78,39,x0A
                        parts = line.split(",")
                        if len(parts) >= 6:
                            tag_id = parts[2]
                            try:
                                x = float(parts[3])
                                y = float(parts[4])
                                tag_positions[tag_id] = (x, y)
                            except:
                                pass

            time.sleep(0.01)

        except serial.SerialException:
            print("[-] USB disconnected, waiting...")
            ser = None
            reconnect_serial()
        except OSError:
            pass


###############################
#       RECONNECT SERIAL      #
###############################

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
#      REAL-TIME PLOTTER      #
###############################

def start_plotter():
    plt.style.use("ggplot")
    fig, ax = plt.subplots()
    ax.set_title("Real-time UWB POS XY Plot")
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")

    def update(frame):
        if len(tag_positions) == 0:
            return

        xs = [pos[0] for pos in tag_positions.values()]
        ys = [pos[1] for pos in tag_positions.values()]
        ids = list(tag_positions.keys())

        ax.clear()
        ax.set_title("Real-time UWB POS XY Plot")
        ax.set_xlabel("X (m)")
        ax.set_ylabel("Y (m)")

        ax.scatter(xs, ys)

        # label tags
        for tag_id, x, y in zip(ids, xs, ys):
            ax.text(x, y, tag_id, fontsize=9)

        # auto scaling
        ax.set_xlim(min(xs) - 0.5, max(xs) + 0.5)
        ax.set_ylim(min(ys) - 0.5, max(ys) + 0.5)

    FuncAnimation(fig, update, interval=300)
    plt.show()


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

                # Start UART reader
                t = threading.Thread(target=uart_reader, daemon=True)
                t.start()

                # Start plotter
                p = threading.Thread(target=start_plotter, daemon=True)
                p.start()

                # Auto config listener
                setup_listener(ser)

            except Exception as e:
                print(f"[-] Connection failed: {e}")
                ser = None
        else:
            print("[-] No USB device found...")
            time.sleep(1)

    # Command loop
    print("\n[+] Listener active. Type commands below, or 'exit'.")
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
    print("[+] Program finished.")


if __name__ == "__main__":
    main()
