# This code is used to read and write the PAN ID (Network ID) of a Bluetooth device using the Bleak library.

import asyncio
import struct
from bleak import BleakClient

ADDRESS = "DF:40:6F:1F:D7:11"
NETWORK_ID_UUID = "80f9d8bc-3bff-45bb-a181-2d6a37991208"

async def main():
    async with BleakClient(ADDRESS) as client:
        if not client.is_connected:
            print("Failed to connect")
            return

        print("Connected to device")

        # PAN ID contoh: 0x1342
        pan_id = 0x1342

        # 2-byte little-endian
        payload = struct.pack("<H", pan_id)

        print(f"Writing PAN ID = {hex(pan_id)} (bytes={payload.hex()})")

        await client.write_gatt_char(NETWORK_ID_UUID, payload)

        print("Network ID successfully written!")
          # Read 2-byte PAN ID
        data = await client.read_gatt_char(NETWORK_ID_UUID)

        print(f"Raw bytes: {data.hex()}")

        # Decode (little endian uint16)
        pan_id_read = struct.unpack("<H", data)[0]

        print(f"✔ Network ID (PAN ID) = {pan_id_read}  (hex: {hex(pan_id_read)})")

if __name__ == "__main__":
    asyncio.run(main())
