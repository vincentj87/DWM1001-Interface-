import asyncio
import struct
from bleak import BleakClient

ADDRESS = "DD:73:23:8B:A7:0E"

# Correct BLE UUID for Location Data
POSITION_CHAR_UUID = "003bbdf2-c634-4b3d-ab56-7ec889b89a37"

async def main():
    async with BleakClient(ADDRESS) as client:
        if not client.is_connected:
            print("Failed to connect")
            return

        print("Connected to device")

        # Read raw location-data characteristic
        data = await client.read_gatt_char(POSITION_CHAR_UUID)
        print("Raw data length:", len(data))
        print("Raw hex:", data.hex())

        if len(data) != 14:
            print("Unexpected payload size:", len(data))
            return

        # Parse according to BLE API spec:
        # byte 0 = type (should be 0)
        msg_type = data[0]

        # bytes 1–4, 5–8, 9–12
        x, y, z = struct.unpack("<iii", data[1:13])

        # byte 13
        qf = data[13]

        print("\nAnchor Position:")
        print("  Type =", msg_type)     # expected 0 (position only)
        print("  X =", x, "mm")
        print("  Y =", y, "mm")
        print("  Z =", z, "mm")
        print("  QF =", qf, "%")

if __name__ == "__main__":
    asyncio.run(main())
