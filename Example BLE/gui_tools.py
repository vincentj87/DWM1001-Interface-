#!/usr/bin/env python3
"""
DWM1001C Manager — Combined GUI for UWB Operations (Connect, Config, Location)
Fix: RPos button now uses the Live Location UUID (003bbdf2...) and 14-byte parsing
     from the user's successful 'get_anchor_pos.py' script.
Includes: PAN ID read/write functionality integrated from read_write_pansid.py
"""

import asyncio
import struct
import logging
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from bleak import BleakClient, BleakScanner
import threading

# ----------------- CONFIG -----------------

# List of devices to manage (You can adjust this list)
DEVICES = [
    (1, "DW0DA4", "D2:60:E7:6E:55:30"),
    (2, "DW3061", "DF:40:6F:1F:D7:11"),
    (3, "DW3068", "C6:25:47:51:C2:80"),
    (4, "DW3221", "CE:D8:74:92:70:83"),
    (5, "DW323C", "CF:4D:5E:14:14:E3"),
    (6, "DW3233", "DD:73:23:8B:A7:0E"),
    (9, "DW30D4", "CA:4E:FD:A7:76:6B"),
]

# BLE GATT UUIDs
OP_MODE_UUID = "3f0afd88-7770-46b0-b5e7-9fc099598964"
NETWORK_ID_UUID = "80f9d8bc-3bff-45bb-a181-2d6a37991208"  # PAN ID Characteristic
DISCONNECT_UUID = "ed83b848-da03-4a0a-a2dc-8b401080e473"

# Core difference here:
# LOCATION_UUID is used for Live Ranging data (RPos, 14 bytes) AND is what
# the user's 'get_anchor_pos.py' successfully read.
LOCATION_UUID = "003bbdf2-c634-4b3d-ab56-7ec889b89a37" 

# ANCHOR_POS_UUID is for Anchor Position Write (ApoS, 13 bytes)
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
    # Same as operation_mode.py
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
    # This is the 14-byte parsing used in get_anchor_pos.py and location notification
    if len(data) < 14:
        return f"Raw: {data.hex()} (Len:{len(data)})"
    try:
        msg_type = data[0]
        x, y, z = struct.unpack("<iii", data[1:13]) 
        q = data[13] if len(data) >= 14 else 0 
        return f"Type:{msg_type}\nX:{x} mm\nY:{y} mm\nZ:{z} mm\nQ:{q}%"
    except struct.error:
        return f"Raw: {data.hex()[:20]}... (unpack error)"
    return f"Raw: {data.hex()}"


def parse_anchor_static_write(data):
    # Used only for writing the 13-byte ApoS characteristic
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

    async def _force_config_refresh(self):
        """Forces the DWM1001C firmware to re-load all persistent config."""
        if not self.client or not self.client.is_connected: return
        self.ui["log"].config(text="Attempting config refresh...")
        try:
            data = await self.client.read_gatt_char(OP_MODE_UUID)
            if len(data) >= 2:
                # Write the exact same data back
                await self.client.write_gatt_char(OP_MODE_UUID, data, response=False)
                log.info("Forced config refresh on %s by rewriting OpMode.", self.address)
                await asyncio.sleep(GATT_STABILIZE_DELAY * 3)
                self.ui["log"].config(text="Config refresh complete.")
        except Exception as e:
            log.debug("Force config refresh failed for %s: %s", self.address, e)
            self.ui["log"].config(text=f"Config refresh failed: {type(e).__name__}")


    async def _post_connect_reads(self):
        """Reads configuration data immediately after connection."""
        await self._read_pan()
        await self._read_mode()
        
        # Keep the fix: Force a refresh before reading position characteristics
        await self._force_config_refresh()
        
        # Read position using the characteristic the user's script successfully used (LOCATION_UUID)
        await self._read_static_pos()

    # --- Read/Write PAN ID (Integrated from read_write_pansid.py) ---
    async def _read_pan(self):
        """Read PAN ID from device and update UI."""
        if not self.client or not self.client.is_connected: return
        try:
            # Read 2-byte PAN ID (little endian)
            data = await self.client.read_gatt_char(NETWORK_ID_UUID)
            
            print(f"Raw PAN ID bytes: {data.hex()}")
            
            if len(data) >= 2:
                pan_id_read = struct.unpack("<H", data[:2])[0]
                self.ui["pan"].config(text=f"0x{pan_id_read:04X}")
                self.ui["log"].config(text=f"Read PAN: 0x{pan_id_read:04X}")
                log.info(f"✔ Network ID (PAN ID) = {pan_id_read}  (hex: {hex(pan_id_read)})")
        except Exception as e:
            log.debug("PAN read failed for %s: %s", self.address, e)
            self.ui["log"].config(text=f"Read PAN Err: {type(e).__name__}")
    
    async def write_pan(self, pan_id: int):
        """Write PAN ID to device."""
        if not self.client or not self.client.is_connected:
            self.ui["log"].config(text="Not connected")
            return
        try:
            # 2-byte little-endian format
            payload = struct.pack("<H", pan_id)
            
            print(f"Writing PAN ID = {hex(pan_id)} (bytes={payload.hex()})")
            
            # Write to GATT characteristic
            await self.client.write_gatt_char(NETWORK_ID_UUID, payload, response=True)
            
            self.ui["log"].config(text=f"PAN ID 0x{pan_id:04X} written.")
            log.info("Network ID successfully written!")
            
            # Read back to confirm
            await self._read_pan()
            
        except Exception as e:
            log.error(f"Write PAN error: {e}")
            self.ui["log"].config(text=f"Write PAN Err: {e}")

    # --- Read Operation Mode ---
    async def _read_mode(self):
        if not self.client or not self.client.is_connected: return
        try:
            data = await self.client.read_gatt_char(OP_MODE_UUID)
            self.ui["opmode"].config(text=decode_op_mode(data))
            self.ui["log"].config(text="Read OpMode success.")
        except Exception as e:
            self.ui["log"].config(text=f"Read OpMode Err: {type(e).__name__}")

    # --- Set Operation Mode ---
    async def set_op_mode(self, role):
        if not self.client or not self.client.is_connected:
            self.ui["log"].config(text="Not connected")
            return
        try:
            self.ui["log"].config(text=f"Setting role to {role}...")
            payload = build_mode_config(role)
            await self.client.write_gatt_char(OP_MODE_UUID, payload)
            await self.force_disconnect_via_char() 
            self.ui["log"].config(text=f"Role set to {role}. Reconnect required.")
            self.ui["pan"].config(text="-")
            self.ui["opmode"].config(text=f"Changing to {role}...")
            self.ui["staticpos"].config(text="-")
            self.ui["livestream"].config(text="---")
        except Exception as e:
            self.ui["log"].config(text=f"Set mode err: {e}")

    # --- Read Anchor Static Position (RPos button fix) ---
    # We now read the LOCATION_UUID (003bbdf2...) using the 14-byte logic
    # from the user's original get_anchor_pos.py.
    async def _read_static_pos(self):
        if not self.client or not self.client.is_connected: return
        try:
            # *** FIX: Using LOCATION_UUID (003bbdf2...) as requested by user ***
            data = await self.client.read_gatt_char(LOCATION_UUID)
            
            if data and len(data) == 14:
                # 14-byte parsing (Type, X, Y, Z, QF)
                msg_type = data[0]
                x, y, z = struct.unpack("<iii", data[1:13])
                q = data[13]
                
                self.ui["staticpos"].config(text=f"X:{x} Y:{y} Z:{z}\nQF:{q}% (Type {msg_type})")
                self.ui["log"].config(text="Read RPos (14-byte) success.")
            else:
                 status_msg = f"Read RPos: len={len(data)}"
                 self.ui["log"].config(text=status_msg + " (Needs Anchor Role/Refresh)")
        except Exception as e:
            self.ui["log"].config(text=f"Read RPos Err: {type(e).__name__}")

    # --- Write Anchor Position (ApoS) ---
    async def write_anchor_position(self, x, y, z, q):
        if not self.client or not self.client.is_connected:
            self.ui["log"].config(text="Not connected")
            return
        try:
            # This must still use the dedicated ApoS write characteristic (ANCHOR_POS_UUID)
            payload = struct.pack("<iiiB", x, y, z, q)
            await self.client.write_gatt_char(ANCHOR_POS_UUID, payload, response=True)
            self.ui["log"].config(text=f"Wrote ApoS: X={x}, Y={y}, Z={z}, Q={q}")
            
            # Read RPos characteristic to verify the write updated the active position
            await self._read_static_pos() 
        except Exception as e:
            self.ui["log"].config(text=f"Write ApoS err: {e}")

    # --- Location Notifications ---
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
            self.ui["log"].config(text="Location Notify ON")
        except Exception as e:
            self.notifying = False
            self.ui["notify"].config(text="OFF")
            self.ui["log"].config(text=f"Notify start err: {type(e).__name__}")

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
            self.ui["log"].config(text="Location Notify OFF")
        except Exception:
            pass

    # --- Connection Management ---
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
            self.ui["log"].config(text="Wrote Force Disconnect")
        except Exception as e:
            self.ui["log"].config(text=f"Disconnect write err: {e}")
        finally:
            await self.disconnect()


# ----------------- Main Application (Tkinter GUI) -----------------

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("DWM1001C BLE Manager")
        self.root.geometry("1650x700")

        self.scanner = None
        self.is_scanning = False
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self._make_styles()
        self.handlers = {}
        self.ui_refs = {}
        self.discovered_devices = {}

        self._build_ui()
        for node_id, name, addr in DEVICES:
            self.handlers[addr] = DeviceHandler(node_id, name, addr, self.ui_refs[addr])

    def _make_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure('TButton', padding=1, font=('Segoe UI', 8))
        style.configure('TLabel', padding=1)

    def _build_ui(self):
        # Top Frame for scanning controls
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        self.scan_btn = ttk.Button(top, text="Start Scanning", command=self._toggle_scan)
        self.scan_btn.pack(side="left", padx=6)
        self.scan_lbl = ttk.Label(top, text="Scanner Idle", foreground="gray")
        self.scan_lbl.pack(side="left", padx=6)
        ttk.Button(top, text="Refresh Status", command=self._refresh_rssi_ui).pack(side="left", padx=6)
        
        ttk.Button(top, text="Manual Config Refresh", command=self._ask_force_refresh).pack(side="left", padx=20)

        container = ttk.Frame(self.root, padding=8)
        container.pack(fill="both", expand=True)

        # UI Headers
        headers = ["ID", "Name", "Address", "RSSI", "Status", "PAN ID", "Anchor Pos", "Live Pos", "OpMode", "Notify", "Actions", "Log"]
        for i, h in enumerate(headers):
            lbl = ttk.Label(container, text=h, font=("Segoe UI", 10, "bold"))
            lbl.grid(row=0, column=i, sticky="w", padx=4)

        # Device Rows
        for r, (node_id, name, addr) in enumerate(DEVICES, start=1):
            base_row = r
            ttk.Label(container, text=str(node_id)).grid(row=base_row, column=0, sticky="w", padx=4)
            ttk.Label(container, text=name).grid(row=base_row, column=1, sticky="w", padx=4)
            ttk.Label(container, text=addr, font=("Consolas", 9)).grid(row=base_row, column=2, sticky="w", padx=4)

            # UI Elements for Data
            lbl_rssi = ttk.Label(container, text="---", foreground="gray")
            lbl_rssi.grid(row=base_row, column=3, sticky="w", padx=4)
            lbl_status = ttk.Label(container, text="DISCONNECTED", foreground="#D93025")
            lbl_status.grid(row=base_row, column=4, sticky="w", padx=4)
            lbl_pan = ttk.Label(container, text="-")
            lbl_pan.grid(row=base_row, column=5, sticky="w", padx=4)
            
            # The RPos button is tied to lbl_static
            lbl_static = ttk.Label(container, text="-", font=("Consolas", 9), justify="left")
            lbl_static.grid(row=base_row, column=6, sticky="w", padx=4)
            
            # The live notification stream is tied to lbl_live
            lbl_live = ttk.Label(container, text="---", font=("Consolas", 9), justify="left", foreground="#1A73E8")
            lbl_live.grid(row=base_row, column=7, sticky="w", padx=4)
            
            lbl_op = ttk.Label(container, text="-")
            lbl_op.grid(row=base_row, column=8, sticky="w", padx=4)
            lbl_notify = ttk.Label(container, text="OFF")
            lbl_notify.grid(row=base_row, column=9, sticky="w", padx=4)
            
            # Action Frame
            action_frame = ttk.Frame(container)
            action_frame.grid(row=base_row, column=10, sticky="w", padx=4)
            
            lbl_log = ttk.Label(container, text="", foreground="#555555")
            lbl_log.grid(row=base_row, column=11, sticky="w", padx=4)

            # Buttons 
            ttk.Button(action_frame, text="Connect", command=lambda a=addr: self._schedule(self.handlers[a].connect())).pack(side="left")
            ttk.Button(action_frame, text="Disc", command=lambda a=addr: self._schedule(self.handlers[a].disconnect())).pack(side="left")
            ttk.Button(action_frame, text="RPAN", command=lambda a=addr: self._schedule(self.handlers[a]._read_pan())).pack(side="left")
            ttk.Button(action_frame, text="WPAN", command=lambda a=addr: self._ask_write_pan(a)).pack(side="left")
            # RPos button now uses the 14-byte location UUID read logic
            ttk.Button(action_frame, text="RPos", command=lambda a=addr: self._schedule(self.handlers[a]._read_static_pos())).pack(side="left") 
            ttk.Button(action_frame, text="WPos", command=lambda a=addr: self._ask_write_pos(a)).pack(side="left")
            ttk.Button(action_frame, text="Loc", command=lambda a=addr: self._toggle_notify(a)).pack(side="left")
            ttk.Button(action_frame, text="ForceDisc", command=lambda a=addr: self._confirm_force_disconnect(a)).pack(side="left")

            # Role dropdown
            role_var = tk.StringVar(value="Tag")
            ttk.OptionMenu(action_frame, role_var, "Tag", "Tag", "Anchor").pack(side="left", padx=(4,0))
            ttk.Button(action_frame, text="Set Role", command=lambda a=addr, v=role_var: self._schedule(self.handlers[a].set_op_mode(v.get().lower()))).pack(side="left")

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

    # ----------------- Scanning Logic -----------------

    def _refresh_rssi_ui(self):
        for addr, (name, rssi) in self.discovered_devices.items():
            if addr in self.ui_refs:
                self.ui_refs[addr]["rssi"].config(text=str(rssi), foreground="#000000" if rssi > -80 else "#FFA500")

    def _scan_callback(self, device, advertisement_data):
        self.discovered_devices[device.address] = (device.name, advertisement_data.rssi)
        if device.address in self.ui_refs:
            self.ui_refs[device.address]["rssi"].config(text=str(advertisement_data.rssi), foreground="#000000" if advertisement_data.rssi > -80 else "#FFA500")

    async def _scan_task(self):
        self.scanner = BleakScanner(self._scan_callback)
        self.scan_lbl.config(text="Scanning...", foreground="#1A73E8")
        while self.is_scanning:
            await self.scanner.start()
            await asyncio.sleep(SCANNER_INTERVAL)
            await self.scanner.stop()
            await asyncio.sleep(1)
        self.scan_lbl.config(text="Scanner Idle", foreground="gray")
        self.scan_btn.config(text="Start Scanning")

    def _toggle_scan(self):
        if self.is_scanning:
            self.is_scanning = False
            self.scan_btn.config(text="Stopping...")
        else:
            self.is_scanning = True
            self.scan_btn.config(text="Stop Scanning")
            self._schedule(self._scan_task())
            
    # ----------------- Manual Configuration Refresh -----------------
    
    def _ask_force_refresh(self):
        device_addresses = [addr for addr, handler in self.handlers.items() if handler.connected]
        
        if not device_addresses:
            messagebox.showinfo("Info", "No devices currently connected to refresh.")
            return
            
        top = tk.Toplevel(self.root)
        top.title("Select Device to Refresh")
        selected_addr = tk.StringVar(top)
        
        options = {}
        for addr in device_addresses:
            options[f"{self.handlers[addr].name} | {addr}"] = addr
            
        ttk.Label(top, text="Select Device:").pack(padx=10, pady=5)
        
        name_list = list(options.keys())
        if not name_list:
            top.destroy()
            return
            
        selected_addr.set(name_list[0]) 
        
        option_menu = ttk.OptionMenu(top, selected_addr, selected_addr.get(), *name_list)
        option_menu.pack(padx=10, pady=5)
        
        def confirm_refresh():
            selected_name_addr = selected_addr.get()
            actual_addr = options.get(selected_name_addr)
            
            if actual_addr in self.handlers:
                self._schedule(self.handlers[actual_addr]._force_config_refresh())
            top.destroy()

        ttk.Button(top, text="Perform Refresh", command=confirm_refresh).pack(pady=10)
        top.transient(self.root)
        top.grab_set()
        self.root.wait_window(top)

    # ----------------- User Input Dialogs -----------------

    def _ask_write_pan(self, addr):
        """Dialog for writing PAN ID to a device (from read_write_pansid.py)."""
        handler = self.handlers.get(addr)
        if not handler or not handler.connected:
            messagebox.showerror("Error", "Device not connected.", parent=self.root)
            return

        pan_str = simpledialog.askstring("Write PAN ID", "Enter new PAN ID (e.g., 0x1A2B or 6700):", parent=self.root)
        if pan_str:
            try:
                if pan_str.lower().startswith('0x'):
                    pan_id = int(pan_str, 16)
                else:
                    pan_id = int(pan_str, 10)

                if 0 <= pan_id <= 0xFFFF:
                    self._schedule(handler.write_pan(pan_id))
                else:
                    messagebox.showerror("Error", "PAN ID must be between 0 and 65535.", parent=self.root)
            except ValueError:
                messagebox.showerror("Error", "Invalid PAN ID format.", parent=self.root)

    def _ask_write_pos(self, addr):
        handler = self.handlers.get(addr)
        if not handler or not handler.connected:
            messagebox.showerror("Error", "Device not connected.", parent=self.root)
            return

        x_str = simpledialog.askstring("Write Anchor Position", "Enter X position (mm):", initialvalue="1000", parent=self.root)
        if not x_str: return
        y_str = simpledialog.askstring("Write Anchor Position", "Enter Y position (mm):", initialvalue="2000", parent=self.root)
        if not y_str: return
        z_str = simpledialog.askstring("Write Anchor Position", "Enter Z position (mm):", initialvalue="1500", parent=self.root)
        if not z_str: return
        q_str = simpledialog.askstring("Write Anchor Position", "Enter Quality Factor Q (0-100):", initialvalue="100", parent=self.root)
        if not q_str: return

        try:
            x = int(x_str)
            y = int(y_str)
            z = int(z_str)
            q = int(q_str)
            if not 0 <= q <= 100:
                 messagebox.showerror("Error", "Quality Factor (Q) must be between 0 and 100.", parent=self.root)
                 return
            self._schedule(handler.write_anchor_position(x, y, z, q))
        except ValueError:
            messagebox.showerror("Error", "Invalid position/quality value. Must be integers.", parent=self.root)

    def _toggle_notify(self, addr):
        handler = self.handlers.get(addr)
        if not handler or not handler.connected:
            messagebox.showerror("Error", "Device not connected.", parent=self.root)
            return
        if handler.notifying:
            self._schedule(handler.stop_location_notify())
        else:
            self._schedule(handler.start_location_notify())

    def _confirm_force_disconnect(self, addr):
        if messagebox.askyesno("Confirm Force Disconnect", "Forcefully disconnect device? This is often required after setting mode.", parent=self.root):
            self._schedule(self.handlers[addr].force_disconnect_via_char())

    # ----------------- Async/Tkinter Integration -----------------

    def _schedule(self, coro):
        try:
            return asyncio.ensure_future(coro)
        except RuntimeError:
            log.error("Event loop not running")
            messagebox.showerror("Error", "Asyncio event loop is not running.", parent=self.root)

    async def _tk_update_loop(self):
        try:
            while True:
                try:
                    self.root.update_idletasks()
                    self.root.update()
                except tk.TclError:
                    break 
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            pass

    def on_closing(self):
        log.info("Closing application...")
        self.is_scanning = False
        self.root.destroy()

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
            log.info("Stopping event loop.")
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
    try:
        app = App()
        log.info("Starting application")
        app.run()
    except Exception as e:
        log.critical(f"Fatal error in main application: {e}")

if __name__ == "__main__":
    main()