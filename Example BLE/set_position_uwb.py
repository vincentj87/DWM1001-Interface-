# This code is used to set the position of a UWB anchor device (DWM1001C) via Bluetooth using the Bleak library.

import asyncio
import struct
from bleak import BleakClient

ADDRESS = "DF:40:6F:1F:D7:11"
position_anchor_set_uuid = "f0f26c9b-2c8c-49ac-ab60-fe03def1b40c"   # write-only characteristic

async def main():
    async with BleakClient(ADDRESS) as client:
        if not client.is_connected:
            print("Failed to connect")
            return

        print("Connected to device")

        # Data posisi (X,Y,Z,Q)
        x = 1000   # mm
        y = 1000   # mm
        z = 0      # mm
        q = 100    # quality

        # pack ke 13 bytes
        payload = struct.pack("<iiiB", x, y, z, q)

        print("Writing position:", x, y, z, q)
        await client.write_gatt_char(position_anchor_set_uuid, payload)

        print("Anchor position successfully written!")

if __name__ == "__main__":
    asyncio.run(main())
