import asyncio
import struct
import threading
from bleak import BleakClient
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

ADDRESS = "CF:4D:5E:14:14:E3"
LOCATION_CHAR_UUID = "003bbdf2-c634-4b3d-ab56-7ec889b89a37"

positions_x = []
positions_y = []

def parse_position(data: bytes):
    if len(data) < 13:
        return None
    packet_type = data[0]
    if packet_type not in (0, 2):
        return None
    x, y, z = struct.unpack("<iii", data[1:13])
    quality = data[13] if len(data) > 13 else 0
    return {"x_m": x / 1000.0, "y_m": y / 1000.0, "z_m": z / 1000.0, "quality": quality}

async def notification_handler(sender, data):
    pos = parse_position(data)
    if pos:
        positions_x.append(pos["x_m"])
        positions_y.append(pos["y_m"])
        print(f"x={pos['x_m']:.3f}, y={pos['y_m']:.3f}, quality={pos['quality']}")

async def ble_task():
    async with BleakClient(ADDRESS) as client:
        if not client.is_connected:
            print("Failed to connect")
            return
        await client.start_notify(LOCATION_CHAR_UUID, notification_handler)
        while True:
            await asyncio.sleep(0.1)

def run_ble_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ble_task())

def update(frame):
    plt.cla()
    plt.scatter(positions_x, positions_y, c='blue')
    plt.xlabel("X (m)")
    plt.ylabel("Y (m)")
    plt.title("Real-time XY Position")
    # Dynamic axis limits based on current data
    if positions_x and positions_y:
        plt.xlim(min(positions_x) - 1, max(positions_x) + 1)
        plt.ylim(min(positions_y) - 1, max(positions_y) + 1)

def main():
    # Enable interactive mode and set flexible figure size
    plt.ion()
    fig = plt.figure(figsize=(10, 8))  # width=10in, height=8in
    fig.canvas.manager.set_window_title("UWB Real-time XY Visualization")

    # Run BLE in a separate thread
    ble_thread = threading.Thread(target=run_ble_loop, daemon=True)
    ble_thread.start()

    # Start matplotlib animation in main thread
    ani = FuncAnimation(fig, update, interval=500)
    plt.show(block=True)  # allows resizing

if __name__ == "__main__":
    main()
