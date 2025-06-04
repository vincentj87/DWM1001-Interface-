#!/usr/bin/env python3
"""
DWM1001C Manager — single-file with Tag/Anchor selection (logging enabled)
"""

import asyncio
import struct
import logging
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from bleak import BleakClient, BleakScanner

# ----------------- CONFIG -----------------

DEVICES = [
    (1, "DW0DA4", "D2:60:E7:6E:55:30"),
    (2, "DW3061", "DF:40:6F:1F:D7:11"),
    (3, "DW3068", "C6:25:47:51:C2:80"),
    (4, "DW3221", "CE:D8:74:92:70:83"),
    (5, "DW323C", "CF:4D:5E:14:14:E3"),
    (6, "DW3233", "DD:73:23:8B:A7:0E"),
    (9, "DW30D4", "CA:4E:FD:A7:76:6B"),
]

OP_MODE_UUID = "3f0afd88-7770-46b0-b5e7-9fc099598964"
NETWORK_ID_UUID = "80f9d8bc-3bff-45bb-a181-2d6a37991208"
DISCONNECT_UUID = "ed83b848-da03-4a0a-a2dc-8b401080e473"
LOCATION_UUID = "003bbdf2-c634-4b3d-ab56-7ec889b89a37"
ANCHOR_POS_UUID = "f0f26c9b-2c8c-49ac-ab60-fe03def1b40c"

GATT_STABILIZE_DELAY = 0.08
SCANNER_INTERVAL = 2.5

# ----------------- Logging -----------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("dwm_manager")

# ----------------- Utilities -----------------

def build_mode_config(role="tag"):
    bit7 = 1 << 7 if role == "anchor" else 0
    uwb_mode = 2 << 5
    fw = 0 << 4
    accel = 1 << 3
    led = 1 << 2
    fw_update = 1 << 1
    ble = 1 << 0
    byte1 = bit7 | uwb_mode | fw | accel | led | fw_update | ble
    if role == "anchor":
        byte2 = 1 << 7
    else:
        byte2 = (1 << 6) | (1 << 5)
    return struct.pack("<BB", byte1, byte2)


def decode_op_mode(data):
    if len(data) < 2:
        return f"Raw: {data.hex()}"
    b0, b1 = struct.unpack("<BB", data[:2])
    parts = []
    is_anchor = (b0 >> 7) & 1
    parts.append(f"Type: {'Anchor' if is_anchor else 'Tag'}")
    uwb_val = (b0 >> 5) & 0x03
    uwb_modes = {0: "OFF", 1: "Passive", 2: "Active", 3: "Unknown"}
    parts.append(f"UWB: {uwb_modes.get(uwb_val,'Unknown')} ({uwb_val})")
    parts.append(f"FW Ver: {((b0>>4) & 1)+1}")
    parts.append(f"Accel: {'ON' if (b0>>3)&1 else 'OFF'}")
    parts.append(f"LED: {'ON' if (b0>>2)&1 else 'OFF'}")
    parts.append(f"FW Update: {'ON' if (b0>>1)&1 else 'OFF'}")
    parts.append(f"BLE: {'ON' if (b0>>0)&1 else 'OFF'}")
    parts.append(f"Initiator: {'ON' if (b1>>7)&1 else 'OFF'}")
    parts.append(f"LowPower: {'ON' if (b1>>6)&1 else 'OFF'}")
    parts.append(f"LocEngine: {'ON' if (b1>>5)&1 else 'OFF'}")
    return "\n".join(parts)


def decode_location_data(data):
    if len(data) < 14:
        return f"Raw: {data.hex()} (Len:{len(data)})"
    try:
        if len(data) == 14:
            msg_type = data[0]
            x, y, z = struct.unpack("<iii", data[1:13])
            q = data[13]
            return f"X:{x}\nY:{y}\nZ:{z}\nQ:{q}%"
        if len(data) >= 16:
            x, y, z, q = struct.unpack("<iiii", data[2:18])
            return f"X:{x}\nY:{y}\nZ:{z}\nQ:{q}"
    except struct.error:
        return f"Raw: {data.hex()[:20]}... (unpack)"
    return f"Raw: {data.hex()}"


def parse_anchor_static(data):
    if len(data) != 13:
        raise ValueError("anchor static must be 13 bytes")
    x, y, z, q = struct.unpack("<iiiB", data)
    return x, y, z, q


# ----------------- Device Handler -----------------

class DeviceHandler:
    def __init__(self, node_id, name, address, ui_refs):
        self.node_id = node_id
        self.name = name
        self.address = address
        self.client = None
        self.connected = False
        self.notifying = False
        self.ui = ui_refs

    async def connect(self):
        if self.connected:
            log.info("%s already connected", self.address)
            return
        try:
            self.client = BleakClient(self.address)
            await self.client.connect()
            self.connected = self.client.is_connected
            if self.connected:
                log.info("Connected: %s (%s)", self.name, self.address)
                self.ui["status"].config(text="CONNECTED", foreground="#388E3C")
                self.ui["log"].config(text="Connected")
                await asyncio.sleep(GATT_STABILIZE_DELAY)
                await self._post_connect_reads()
                await self.start_location_notify()
            else:
                self.ui["status"].config(text="FAILED", foreground="#D93025")
        except Exception as e:
            log.exception("Connect error for %s", self.address)
            self.ui["status"].config(text=f"ERR:{type(e).__name__}", foreground="#D93025")
            self.ui["log"].config(text=f"Conn Err: {e}")

    async def _post_connect_reads(self):
        try:
            data = await self.client.read_gatt_char(NETWORK_ID_UUID)
            if len(data) >= 2:
                pan = struct.unpack("<H", data[:2])[0]
                self.ui["pan"].config(text=f"0x{pan:04X}")
                log.info("PAN read for %s: 0x%04X", self.address, pan)
        except Exception as e:
            log.debug("PAN read failed for %s: %s", self.address, e)
        try:
            data = await self.client.read_gatt_char(OP_MODE_UUID)
            self.ui["opmode"].config(text=decode_op_mode(data))
        except Exception:
            pass
        try:
            data = await self.client.read_gatt_char(ANCHOR_POS_UUID)
            if data and len(data) == 13:
                x, y, z, q = parse_anchor_static(data)
                self.ui["staticpos"].config(text=f"X:{x} Y:{y} Z:{z}\nQF:{q}%")
        except Exception:
            pass

    async def disconnect(self):
        if self.client:
            try:
                await self.stop_location_notify()
                await self.client.disconnect()
            except Exception:
                pass
        self.client = None
        self.connected = False
        self.notifying = False
        self.ui["status"].config(text="DISCONNECTED", foreground="#D93025")
        self.ui["notify"].config(text="OFF")
        self.ui["livestream"].config(text="---")
        self.ui["log"].config(text="Disconnected")

    async def force_disconnect_via_char(self):
        if not self.client or not self.client.is_connected:
            self.ui["log"].config(text="Not connected")
            return
        try:
            await self.client.write_gatt_char(DISCONNECT_UUID, bytes([1]))
        except Exception as e:
            self.ui["log"].config(text=f"Disconnect write err: {e}")
        finally:
            await self.disconnect()

    async def set_op_mode(self, role):
        if not self.client or not self.client.is_connected:
            self.ui["log"].config(text="Not connected")
            return
        try:
            payload = build_mode_config(role)
            await self.client.write_gatt_char(OP_MODE_UUID, payload)
            await self.force_disconnect_via_char()
            self.ui["pan"].config(text="-")
            self.ui["opmode"].config(text="OFF")
            self.ui["staticpos"].config(text="-")
            self.ui["livestream"].config(text="---")
        except Exception as e:
            self.ui["log"].config(text=f"Set mode err: {e}")

    async def write_anchor_position(self, x, y, z, q):
        if not self.client or not self.client.is_connected:
            self.ui["log"].config(text="Not connected")
            return
        try:
            payload = struct.pack("<iiiB", x, y, z, q)
            await self.client.write_gatt_char(ANCHOR_POS_UUID, payload, response=True)
            data = await self.client.read_gatt_char(ANCHOR_POS_UUID)
            if data and len(data) == 13:
                x2, y2, z2, q2 = parse_anchor_static(data)
                self.ui["staticpos"].config(text=f"X:{x2} Y:{y2} Z:{z2}\nQF:{q2}%")
        except Exception as e:
            self.ui["log"].config(text=f"Write pos err: {e}")

    async def start_location_notify(self):
        if not self.client or not self.client.is_connected:
            return
        def _cb(sender, data):
            try:
                s = decode_location_data(data)
                self.ui["livestream"].config(text=s)
            except Exception as e:
                self.ui["log"].config(text=f"Decode err: {e}")
        try:
            await self.client.start_notify(LOCATION_UUID, _cb)
            self.notifying = True
            self.ui["notify"].config(text="ON")
        except Exception as e:
            self.notifying = False
            self.ui["notify"].config(text="OFF")

    async def stop_location_notify(self):
        if not self.client or not self.client.is_connected or not self.notifying:
            self.notifying = False
            self.ui["notify"].config(text="OFF")
            self.ui["livestream"].config(text="---")
            return
        try:
            await self.client.stop_notify(LOCATION_UUID)
            self.notifying = False
            self.ui["notify"].config(text="OFF")
            self.ui["livestream"].config(text="---")
        except Exception:
            pass


# ----------------- Main Application -----------------

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("DWM1001C Manager")
        self.root.geometry("1400x700")

        self._make_styles()
        self.handlers = {}
        self.ui_refs = {}

        self._build_ui()
        for node_id, name, addr in DEVICES:
            self.handlers[addr] = DeviceHandler(node_id, name, addr, self.ui_refs[addr])

    def _make_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        self.scan_btn = ttk.Button(top, text="Start Scanning", command=self._toggle_scan)
        self.scan_btn.pack(side="left", padx=6)
        self.scan_lbl = ttk.Label(top, text="Scanner Idle", foreground="gray")
        self.scan_lbl.pack(side="left", padx=6)

        container = ttk.Frame(self.root, padding=8)
        container.pack(fill="both", expand=True)

        headers = ["ID", "Name", "Address", "RSSI", "Status", "PAN ID", "Anchor Pos", "Live Pos", "OpMode", "Notify", "Actions", "Log"]
        for i, h in enumerate(headers):
            lbl = ttk.Label(container, text=h, font=("Segoe UI", 10, "bold"))
            lbl.grid(row=0, column=i, sticky="w", padx=4)

        for r, (node_id, name, addr) in enumerate(DEVICES, start=1):
            base_row = r
            ttk.Label(container, text=str(node_id)).grid(row=base_row, column=0, sticky="w", padx=4)
            ttk.Label(container, text=name).grid(row=base_row, column=1, sticky="w", padx=4)
            ttk.Label(container, text=addr, font=("Consolas", 9)).grid(row=base_row, column=2, sticky="w", padx=4)

            lbl_rssi = ttk.Label(container, text="---", foreground="gray")
            lbl_rssi.grid(row=base_row, column=3, sticky="w", padx=4)
            lbl_status = ttk.Label(container, text="DISCONNECTED", foreground="#D93025")
            lbl_status.grid(row=base_row, column=4, sticky="w", padx=4)
            lbl_pan = ttk.Label(container, text="-")
            lbl_pan.grid(row=base_row, column=5, sticky="w", padx=4)
            lbl_static = ttk.Label(container, text="-", font=("Consolas", 9), justify="left")
            lbl_static.grid(row=base_row, column=6, sticky="w", padx=4)
            lbl_live = ttk.Label(container, text="---", font=("Consolas", 9), justify="left", foreground="#1A73E8")
            lbl_live.grid(row=base_row, column=7, sticky="w", padx=4)
            lbl_op = ttk.Label(container, text="-")
            lbl_op.grid(row=base_row, column=8, sticky="w", padx=4)
            lbl_notify = ttk.Label(container, text="OFF")
            lbl_notify.grid(row=base_row, column=9, sticky="w", padx=4)
            action_frame = ttk.Frame(container)
            action_frame.grid(row=base_row, column=10, sticky="w", padx=4)
            lbl_log = ttk.Label(container, text="", foreground="#555555")
            lbl_log.grid(row=base_row, column=11, sticky="w", padx=4)

            # Buttons
            ttk.Button(action_frame, text="Connect", command=lambda a=addr: self._schedule(self._connect(a))).pack(side="left")
            ttk.Button(action_frame, text="Disc", command=lambda a=addr: self._schedule(self._disconnect(a))).pack(side="left")
            ttk.Button(action_frame, text="PAN", command=lambda a=addr: self._schedule(self._read_pan(a))).pack(side="left")
            ttk.Button(action_frame, text="Mode", command=lambda a=addr: self._schedule(self._read_mode(a))).pack(side="left")
            ttk.Button(action_frame, text="RPos", command=lambda a=addr: self._schedule(self._read_static_pos(a))).pack(side="left")
            ttk.Button(action_frame, text="WPos", command=lambda a=addr: self._ask_write_pos(a)).pack(side="left")
            ttk.Button(action_frame, text="Loc", command=lambda a=addr: self._toggle_notify(a)).pack(side="left")
            ttk.Button(action_frame, text="ForceDisc", command=lambda a=addr: self._confirm_force_disconnect(a)).pack(side="left")

            # Role dropdown
            role_var = tk.StringVar(value="Tag")
            ttk.OptionMenu(action_frame, role_var, "Tag", "Tag", "Anchor").pack(side="left")
            ttk.Button(action_frame, text="Apply Role", command=lambda a=addr, v=role_var: self._schedule(self._set_role(a, v.get().lower()))).pack(side="left")

            # Store refs
            self.ui_refs[addr] = {
                "rssi": lbl_rssi,
                "status": lbl_status,
                "pan": lbl_pan,
                "staticpos": lbl_static,
                "livestream": lbl_live,
                "opmode": lbl_op,
                "notify": lbl_notify,
                "log": lbl_log,
                "role_var": role_var
            }

    # ----------------- Async helpers -----------------

    def _schedule(self, coro):
        try:
            return asyncio.ensure_future(coro)
        except RuntimeError:
            log.error("Event loop not running")

    async def _set_role(self, addr, role):
        handler = self.handlers.get(addr)
        if not handler:
            return
        self.ui_refs[addr]["log"].config(text=f"Setting role to {role}...")
        await handler.set_op_mode(role)
        if role == "anchor" and handler.notifying:
            await handler.stop_location_notify()
            self.ui_refs[addr]["livestream"].config(text="---")
        elif role == "tag":
            await handler.start_location_notify()
        try:
            data = await handler.client.read_gatt_char(OP_MODE_UUID)
            self.ui_refs[addr]["opmode"].config(text=decode_op_mode(data))
            self.ui_refs[addr]["log"].config(text=f"Role set to {role}")
        except Exception as e:
            self.ui_refs[addr]["log"].config(text=f"Read back err: {e}")

    # -------------- Other async functions (connect/disconnect/read PAN/mode/pos) --------------
    # Keep your previous implementations here: _connect, _disconnect, _read_pan, _read_mode, _read_static_pos, _ask_write_pos, _write_pos, _toggle_notify, _confirm_force_disconnect

    async def _tk_update_loop(self):
        try:
            while True:
                try:
                    self.root.update()
                except tk.TclError:
                    break
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            pass

    def run(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self._tk_update_loop())
        async def _idle():
            while True:
                await asyncio.sleep(1)
        loop.create_task(_idle())
        try:
            loop.run_forever()
        finally:
            tasks = asyncio.all_tasks(loop=loop)
            for t in tasks:
                t.cancel()
            try:
                loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            except Exception:
                pass
            loop.stop()
            loop.close()


# ----------------- Entrypoint -----------------

def main():
    app = App()
    log.info("Starting application")
    app.run()


if __name__ == "__main__":
    main()
