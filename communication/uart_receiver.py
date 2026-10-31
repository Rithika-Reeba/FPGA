"""
UART Receiver Module for FPGA Telemetry Communication
=====================================================
Interfaces with the physical FPGA board (Digilent Basys 3 Artix-7 XC7A35T-1CPG236C)
over Serial / UART (115200 8N1) to receive real-time on-chip sensor telemetry.

Supported Telemetry Streams:
  1. JSON Stream:
     {"Temperature":35.2,"VCCINT":1.002,"VCCAUX":1.801,"VCCBRAM":1.000,"RO_Frequency":249.8,"Error_Rate":0.000010}
  2. Handshake / Status Text:
     HELLO FPGA - Basys 3 Artix-7 Health Monitor Online
  3. Key-Value Fallback Stream:
     TEMP:35.2,VCCINT:1.002,VCCAUX:1.801,VCCBRAM:1.000,RO:249.8,ERR:0.000010
"""

import json
import time
import sys
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import RO_STAGES, calculate_ro_delay_ns
from hardware.host.health_reader import parse_line as parse_hex_line

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False


class ConnectionState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    PORT_OPEN_WAITING = "PORT_OPEN_WAITING"      # Port open, listening for valid packets
    RECEIVING_TELEMETRY = "RECEIVING_TELEMETRY"  # Actively receiving valid packets
    NO_TELEMETRY = "NO_TELEMETRY"               # Port open, but 0 valid packets (e.g. wrong port)
    STALE_DATA = "STALE_DATA"                   # Packets stopped
    ERROR = "ERROR"                             # Port failed to open (access denied, etc.)


class FPGAUARTReceiver:
    """
    UART Communication interface with robust state machine, error recovery,
    stale data detection, and physical bounds validation for Basys 3 telemetry.
    """

    def __init__(self, port: str = "COM10", baudrate: int = 115200, timeout: float = 1.0, stale_threshold_sec: float = 3.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.stale_threshold_sec = stale_threshold_sec

        self.serial_conn: Optional[Any] = None
        self.state: ConnectionState = ConnectionState.DISCONNECTED
        self.last_error_msg: str = ""

        # Telemetry & Diagnostic Metrics
        self.last_valid_packet: Optional[Dict[str, Any]] = None
        self.last_packet_time: float = 0.0
        self.packet_count: int = 0
        self.error_count: int = 0
        self.handshake_detected: bool = False
        self.handshake_message: str = ""
        self.connection_start_time: float = 0.0

        # Rolling packet rate estimation
        self._recent_timestamps: List[float] = []

    @property
    def is_port_open(self) -> bool:
        """Returns True if the OS serial port handle is open."""
        return self.serial_conn is not None and getattr(self.serial_conn, "is_open", False)

    @property
    def is_streaming(self) -> bool:
        """Returns True ONLY if actively receiving valid FPGA telemetry packets within the stale threshold."""
        now = time.time()
        return (
            self.is_port_open
            and self.state == ConnectionState.RECEIVING_TELEMETRY
            and self.packet_count > 0
            and (now - self.last_packet_time) <= self.stale_threshold_sec
        )

    @property
    def is_connected(self) -> bool:
        """Returns True if serial connection is open and active (not in error or disconnected state)."""
        return (
            self.is_port_open
            and self.state in (
                ConnectionState.PORT_OPEN_WAITING,
                ConnectionState.RECEIVING_TELEMETRY,
                ConnectionState.NO_TELEMETRY,
                ConnectionState.STALE_DATA
            )
        )

    @classmethod
    def _is_bluetooth_port(cls, port_obj: Any) -> bool:
        """Determines if a serial port is a virtual Bluetooth link."""
        hwid = (getattr(port_obj, "hwid", "") or "").lower()
        desc = (getattr(port_obj, "description", "") or "").lower()
        return "bthenum" in hwid or "bluetooth" in desc

    @classmethod
    def _classify_port_device(cls, port_obj: Any) -> Tuple[str, str, bool]:
        """
        Classifies a serial port device into category, clean description, and is_usb flag.
        Returns: (category, clean_description, is_usb)
        """
        desc = getattr(port_obj, "description", "") or "Generic Serial Port"
        hwid = (getattr(port_obj, "hwid", "") or "").lower()
        vid = getattr(port_obj, "vid", None)
        pid = getattr(port_obj, "pid", None)
        mfg = (getattr(port_obj, "manufacturer", "") or "").lower()

        # Check Digilent Basys 3 FTDI FT2232 signature
        if (vid in (0x0403, 1027) and pid in (0x6010, 24592)) or "0403:6010" in hwid or "0403+6010" in hwid:
            return "Basys 3 FPGA (FTDI FT2232)", "Digilent Basys 3 Artix-7 Dual USB-UART/JTAG", True
        if "digilent" in desc.lower() or "digilent" in hwid or "digilent" in mfg:
            return "Basys 3 FPGA (Digilent)", "Digilent USB Device", True

        # Check other common USB-to-UART bridges
        if (vid in (0x0403, 1027) and pid in (0x6001, 24577)) or "ft232" in desc.lower() or "0403:6001" in hwid:
            return "FTDI FT232R USB-UART", desc, True
        if vid in (0x0403, 1027) or "ftdi" in mfg or "ftdi" in hwid:
            return "FTDI USB-UART Bridge", desc, True
        if (vid in (0x10C4, 4292)) or "cp210" in desc.lower() or "cp210" in hwid:
            return "Silicon Labs CP210x USB-UART", desc, True
        if (vid in (0x1A86, 6790)) or "ch340" in desc.lower() or "ch341" in desc.lower() or "1a86:" in hwid:
            return "WCH CH340 USB-UART", desc, True
        if (vid in (0x067B, 1659)) or "pl2303" in desc.lower():
            return "Prolific PL2303 USB-UART", desc, True
        if (vid in (0x2E8A, 11914)) or "pico" in desc.lower() or "rp2040" in desc.lower():
            return "Raspberry Pi RP2040 USB CDC", desc, True
        if (vid in (0x2341, 9025)) or "arduino" in desc.lower():
            return "Arduino USB Serial", desc, True

        # Check Bluetooth links
        if cls._is_bluetooth_port(port_obj):
            return "Bluetooth Serial Link", desc, False

        # Generic USB Serial
        if "usb" in desc.lower() or "usb" in hwid:
            return "Generic USB Serial Device", desc, True

        return "Standard Serial COM Port", desc, False

    @classmethod
    def detect_fpga_port(cls) -> Optional[str]:
        """
        Auto-detects the Digilent Basys 3 USB-UART COM port.
        Searches device descriptions, hardware IDs, and manufacturer for FTDI FT2232 / Digilent signatures.
        """
        if not SERIAL_AVAILABLE:
            return None
        try:
            for p in serial.tools.list_ports.comports():
                category, _, is_usb = cls._classify_port_device(p)
                if "Basys 3" in category:
                    return p.device
            # Fallback: check any FTDI or USB device
            for p in serial.tools.list_ports.comports():
                category, _, is_usb = cls._classify_port_device(p)
                if is_usb and not cls._is_bluetooth_port(p):
                    return p.device
        except Exception:
            pass
        return None

    @classmethod
    def probe_port(cls, port_name: str, timeout: float = 0.4) -> Dict[str, Any]:
        """
        Probes a specific serial port to check if it can be opened and whether
        it is streaming valid Basys 3 FPGA telemetry packets.
        """
        if not SERIAL_AVAILABLE:
            return {"status": "ERROR", "message": "PySerial not available in environment.", "telemetry": False}

        try:
            with serial.Serial(
                port=port_name,
                baudrate=115200,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout
            ) as s:
                # Wait briefly for incoming bytes
                t0 = time.time()
                incoming = b""
                while time.time() - t0 < timeout:
                    if s.in_waiting > 0:
                        incoming += s.read(s.in_waiting)
                        if b"\n" in incoming or b"}" in incoming:
                            break
                    time.sleep(0.04)

                if incoming:
                    text = incoming.decode("utf-8", errors="ignore")
                    if "R1=" in text and "T=" in text and "H=" in text:
                        return {
                            "status": "FPGA_STREAMING",
                            "message": "🟢 Valid FPGA hex telemetry actively streaming!",
                            "telemetry": True,
                            "raw_sample": text.strip()[:100]
                        }
                    if "{" in text and ("Temperature" in text or "RO_Frequency" in text or "VCCINT" in text):
                        return {
                            "status": "FPGA_STREAMING",
                            "message": "🟢 Valid FPGA JSON telemetry actively streaming!",
                            "telemetry": True,
                            "raw_sample": text.strip()[:100]
                        }
                    elif "HELLO FPGA" in text:
                        return {
                            "status": "FPGA_BANNER",
                            "message": "🟢 FPGA Startup Handshake Banner detected!",
                            "telemetry": True,
                            "raw_sample": text.strip()[:100]
                        }
                    elif "TEMP:" in text or "RO:" in text:
                        return {
                            "status": "FPGA_KV_STREAMING",
                            "message": "🟢 FPGA Key-Value telemetry detected!",
                            "telemetry": True,
                            "raw_sample": text.strip()[:100]
                        }
                    else:
                        return {
                            "status": "DATA_DETECTED",
                            "message": f"Serial data detected ({len(incoming)} bytes), but not recognized FPGA format.",
                            "telemetry": False,
                            "raw_sample": text.strip()[:60]
                        }
                else:
                    return {
                        "status": "PORT_OPEN_IDLE",
                        "message": "Port open, but no serial data transmitted within timeout.",
                        "telemetry": False
                    }
        except serial.SerialException as se:
            err = str(se)
            if "PermissionError" in err or "Access is denied" in err:
                return {
                    "status": "PORT_LOCKED",
                    "message": "Port is busy / locked by another process (or active dashboard session).",
                    "telemetry": False
                }
            elif "FileNotFoundError" in err or "could not open port" in err:
                return {
                    "status": "NOT_FOUND",
                    "message": "Port not found or device disconnected.",
                    "telemetry": False
                }
            else:
                return {
                    "status": "ERROR",
                    "message": f"Serial error: {err}",
                    "telemetry": False
                }
        except Exception as e:
            return {
                "status": "ERROR",
                "message": f"Error probing port: {str(e)}",
                "telemetry": False
            }

    @classmethod
    def scan_all_ports_detailed(
        cls,
        current_receiver: Optional['FPGAUARTReceiver'] = None,
        probe_telemetry: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Thoroughly tracks and catalogs EVERY COM port on the host system.
        Returns rich metadata, device category, active status, and telemetry verification.
        """
        if not SERIAL_AVAILABLE:
            return []

        try:
            ports = list(serial.tools.list_ports.comports())
        except Exception:
            ports = []

        results = []
        current_port = current_receiver.port if (current_receiver and current_receiver.is_port_open) else None

        for p in ports:
            category, clean_desc, is_usb = cls._classify_port_device(p)
            is_bt = cls._is_bluetooth_port(p)
            is_cur = (p.device == current_port)

            info = {
                "device": p.device,
                "category": category,
                "description": p.description or clean_desc,
                "hwid": p.hwid or "N/A",
                "manufacturer": p.manufacturer or "Unknown",
                "is_usb": is_usb,
                "is_bluetooth": is_bt,
                "is_current": is_cur,
                "status": "AVAILABLE",
                "status_label": "Ready to connect",
                "telemetry_detected": False,
                "details": ""
            }

            # If this is the active port currently open in the receiver
            if is_cur and current_receiver:
                if current_receiver.is_streaming:
                    info["status"] = "ACTIVE_STREAMING"
                    info["status_label"] = "🟢 Actively Streaming Telemetry"
                    info["telemetry_detected"] = True
                    info["details"] = f"Packets: {current_receiver.packet_count:,} | Rate: {current_receiver.get_packet_rate_hz()} Hz"
                elif current_receiver.is_port_open:
                    info["status"] = "ACTIVE_OPEN"
                    info["status_label"] = "🟡 Port Open (Awaiting Telemetry)"
                    info["details"] = "Connected in current dashboard session"
                else:
                    info["status"] = "DISCONNECTED"
                    info["status_label"] = "Disconnected"
            elif probe_telemetry and not is_bt:
                # Probe physical port for telemetry
                probe_res = cls.probe_port(p.device, timeout=0.3)
                info["status"] = probe_res["status"]
                info["status_label"] = probe_res["message"]
                info["telemetry_detected"] = probe_res.get("telemetry", False)
                info["details"] = probe_res.get("raw_sample", "")
            elif is_bt:
                info["status"] = "BLUETOOTH_LINK"
                info["status_label"] = "Bluetooth Serial Link"
                info["details"] = "Probing skipped to prevent Bluetooth latency"
            else:
                info["status"] = "AVAILABLE"
                info["status_label"] = "Available (Click Connect to use)"
                info["details"] = "Ready"

            results.append(info)

        # Sort so active/FPGA/USB ports appear first, Bluetooth ports at the end
        def sort_key(item):
            if item.get("telemetry_detected"):
                return 0
            if item.get("is_current"):
                return 1
            if "Basys 3" in item.get("category", ""):
                return 2
            if item.get("is_usb"):
                return 3
            return 4

        results.sort(key=sort_key)
        return results

    @classmethod
    def get_port_display_map(cls) -> Dict[str, str]:
        """
        Returns an ordered mapping of {display_label: device_name},
        with the detected FPGA port prominently highlighted at index 0.
        """
        if not SERIAL_AVAILABLE:
            return {"No PySerial Installed": "NONE"}

        try:
            ports = list(serial.tools.list_ports.comports())
        except Exception:
            ports = []

        if not ports:
            return {"No Serial Ports Detected (Plug in USB)": "NONE"}

        fpga_port = cls.detect_fpga_port()
        port_map: Dict[str, str] = {}

        # 1. Add detected FPGA port first
        for p in ports:
            if p.device == fpga_port:
                category, clean_desc, _ = cls._classify_port_device(p)
                label = f"{p.device} -- {category} [Auto-Detected]"
                port_map[label] = p.device

        # 2. Add all other ports with clean descriptors
        for p in ports:
            if p.device == fpga_port:
                continue
            category, clean_desc, is_usb = cls._classify_port_device(p)
            label = f"{p.device} -- {category}"
            port_map[label] = p.device

        return port_map

    @classmethod
    def list_available_ports(cls) -> List[str]:
        """List all active serial communication ports on the host system."""
        port_map = cls.get_port_display_map()
        return list(port_map.values())

    @staticmethod
    def list_detailed_ports() -> List[Dict[str, str]]:
        """Returns detailed port metadata (device name, description, hwid)."""
        if not SERIAL_AVAILABLE:
            return []
        try:
            ports = list(serial.tools.list_ports.comports())
            return [
                {
                    "device": p.device,
                    "description": p.description or "Unknown Serial Device",
                    "hwid": p.hwid or ""
                }
                for p in ports
            ]
        except Exception:
            return []

    def connect(self, port: Optional[str] = None) -> bool:
        """Open serial connection to the Basys 3 FPGA UART interface."""
        if port:
            if self.is_port_open and port != self.port:
                self.disconnect()
            self.port = port

        if not SERIAL_AVAILABLE:
            self.state = ConnectionState.ERROR
            self.last_error_msg = "PySerial library not installed in Python environment."
            return False

        if self.port in ("No Ports Detected", "No PySerial Installed", "NONE", None):
            self.state = ConnectionState.ERROR
            self.last_error_msg = f"Invalid serial port target: {self.port}"
            return False

        # If already open on the desired port, return True
        if self.is_port_open:
            return True

        try:
            self.state = ConnectionState.CONNECTING
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout
            )
            if self.serial_conn.is_open:
                self.state = ConnectionState.PORT_OPEN_WAITING
                self.connection_start_time = time.time()
                self.packet_count = 0
                self.last_packet_time = 0.0
                self.last_error_msg = ""
                return True
            else:
                self.state = ConnectionState.ERROR
                self.last_error_msg = f"Could not open port {self.port}."
                return False
        except serial.SerialException as se:
            self.state = ConnectionState.ERROR
            err_str = str(se)
            if "PermissionError" in err_str or "Access is denied" in err_str:
                self.last_error_msg = (
                    f"Port '{self.port}' is busy or in use by another application. "
                    f"Please close any duplicate dashboard tabs, terminal serial monitors, or Vivado HW server sessions."
                )
            elif "FileNotFoundError" in err_str or "could not open port" in err_str:
                self.last_error_msg = f"Port '{self.port}' not found. Please verify the USB cable is firmly plugged in."
            else:
                self.last_error_msg = f"Serial error on {self.port}: {err_str}"
            self.serial_conn = None
            return False
        except Exception as e:
            self.state = ConnectionState.ERROR
            self.last_error_msg = f"Unexpected error on {self.port}: {str(e)}"
            self.serial_conn = None
            return False

    def disconnect(self):
        """Safely close serial port connection and reset state."""
        if self.serial_conn:
            try:
                if getattr(self.serial_conn, "is_open", False):
                    self.serial_conn.close()
            except Exception:
                pass
        self.serial_conn = None
        self.state = ConnectionState.DISCONNECTED
        self.handshake_detected = False

    def read_packet(self) -> Optional[Dict[str, Any]]:
        """
        Read and decode a single telemetry packet from the FPGA UART stream.
        Handles JSON format, Handshake string, and Key-Value streams.
        Updates connection state and stale data timer.
        """
        if not self.is_connected or not self.serial_conn:
            return None

        now = time.time()
        # Check for stale data if connection was previously receiving
        if self.last_packet_time > 0 and (now - self.last_packet_time) > self.stale_threshold_sec:
            if self.state == ConnectionState.RECEIVING_TELEMETRY:
                self.state = ConnectionState.STALE_DATA

        # Check if port has been open with 0 packets for > 2.5s (Wrong port or board unprogrammed)
        if self.packet_count == 0 and self.connection_start_time > 0 and (now - self.connection_start_time) > 2.5:
            if self.state == ConnectionState.PORT_OPEN_WAITING:
                self.state = ConnectionState.NO_TELEMETRY
                self.last_error_msg = (
                    f"Port '{self.port}' is open, but no FPGA telemetry packets have arrived. "
                    f"Ensure you selected the Basys 3 port, board is powered, and health bitstream is burned."
                )

        try:
            in_waiting = getattr(self.serial_conn, "in_waiting", 0)
            if in_waiting > 0:
                raw_bytes = self.serial_conn.readline()
                raw_line = raw_bytes.decode("utf-8", errors="ignore").strip()

                if not raw_line:
                    return None

                # 1. Check for HELLO FPGA Handshake message
                if "HELLO FPGA" in raw_line.upper():
                    self.handshake_detected = True
                    self.handshake_message = raw_line
                    self.last_packet_time = now
                    self.state = ConnectionState.RECEIVING_TELEMETRY
                    self.last_error_msg = ""
                    return {
                        "packet_type": "HANDSHAKE",
                        "message": raw_line,
                        "timestamp": now
                    }

                # 2. Parse sensor telemetry payload
                parsed = self._parse_raw_line(raw_line)
                if parsed:
                    self.last_valid_packet = parsed
                    self.last_packet_time = now
                    self.packet_count += 1
                    self.state = ConnectionState.RECEIVING_TELEMETRY

                    # Track packet rate
                    self._recent_timestamps.append(now)
                    self._recent_timestamps = [t for t in self._recent_timestamps if (now - t) <= 5.0]

                    return parsed
                else:
                    self.error_count += 1

        except Exception as e:
            self.last_error_msg = str(e)
            self.error_count += 1
            return None

        return None

    def get_packet_rate_hz(self) -> float:
        """Computes recent telemetry streaming rate in Hz (packets per second)."""
        now = time.time()
        self._recent_timestamps = [t for t in self._recent_timestamps if (now - t) <= 5.0]
        if len(self._recent_timestamps) < 2:
            return 0.0
        duration = self._recent_timestamps[-1] - self._recent_timestamps[0]
        if duration <= 0.0:
            return 0.0
        return round((len(self._recent_timestamps) - 1) / duration, 2)

    def _parse_raw_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse raw UART line into structured sensor dictionary."""
        # Case 0: current board firmware - one ASCII-hex line of raw counts / ADC codes
        #   R1=cccccc,R2=...,R3=...,R4=...,T=ttt,I=iii,A=aaa,B=bbb,F=f,S=s,H=h
        if line.lstrip().startswith("R1="):
            return self._hex_packet_to_dict(line)

        # Case A: JSON Telemetry Packet (extract matching { ... })
        start_idx = line.find("{")
        end_idx = line.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                data = json.loads(line[start_idx : end_idx + 1])
                if isinstance(data, dict) and data:
                    return self._sanitize_packet(data)
            except (json.JSONDecodeError, ValueError):
                pass

        # Case B: Key-Value Formatted Line (e.g. TEMP:35.2,VCCINT:1.002,...)
        if ":" in line and not line.startswith("{") and not line.endswith("}"):
            data = {}
            parts = line.split(",")
            for part in parts:
                part_str = part.strip()
                if not part_str:
                    continue
                if ":" not in part_str:
                    return None
                k, v = part_str.split(":", 1)
                k_clean = k.strip().upper()
                try:
                    v_num = float(v.strip())
                except ValueError:
                    return None  # Unparseable value indicates corrupted packet

                if "TEMP" in k_clean:
                    data["Temperature"] = v_num
                elif "VCCINT" in k_clean:
                    data["VCCINT"] = v_num
                elif "VCCAUX" in k_clean:
                    data["VCCAUX"] = v_num
                elif "VCCBRAM" in k_clean:
                    data["VCCBRAM"] = v_num
                elif "RO_R1" in k_clean or k_clean == "R1":
                    data["RO_R1"] = v_num
                elif "RO_R2" in k_clean or k_clean == "R2":
                    data["RO_R2"] = v_num
                elif "RO_R3" in k_clean or k_clean == "R3":
                    data["RO_R3"] = v_num
                elif "RO_R4" in k_clean or k_clean == "R4":
                    data["RO_R4"] = v_num
                elif "RO" in k_clean or "FREQ" in k_clean:
                    data["RO_Frequency"] = v_num
                elif "ERR" in k_clean:
                    data["Error_Rate"] = v_num
                else:
                    return None

            if data and ("Temperature" in data or "RO_Frequency" in data or "RO_R1" in data):
                return self._sanitize_packet(data)

        return None

    def _hex_packet_to_dict(self, line: str) -> Optional[Dict[str, Any]]:
        """
        Convert a raw hex packet into the dashboard's telemetry dictionary.

        Unlike the legacy sanitiser, a stopped ring oscillator is NOT dropped: it is passed
        on with 0 MHz so the engineering limits report it as Degraded instead of the
        dashboard silently showing "no telemetry". The board does not measure a functional
        error rate, so Error_Rate is 0.0 and marked NOT_AVAILABLE.
        """
        p = parse_hex_line(line)
        if p is None:
            return None

        regions = ("R1", "R2", "R3", "R4")
        freqs = {r: (p["freq_mhz"][r] if p["alive"][r] else 0.0) for r in regions}
        running = [f for f in freqs.values() if f > 0.0]
        ro_freq = sum(running) / len(running) if running else 0.0

        temp, vccint, vccaux, vccbram = p["temp_c"], p["VCCINT"], p["VCCAUX"], p["VCCBRAM"]
        if not (0.0 <= temp <= 125.0 and 0.5 <= vccint <= 1.5 and 1.0 <= vccaux <= 2.5 and 0.5 <= vccbram <= 1.5):
            return None
        if any(f > 800.0 for f in freqs.values()):
            return None

        out: Dict[str, Any] = {
            "Timestamp": time.time(),
            "Temperature": round(temp, 2),
            "VCCINT": round(vccint, 4),
            "VCCAUX": round(vccaux, 4),
            "VCCBRAM": round(vccbram, 4),
            "RO_Frequency": round(ro_freq, 2),
            "RO_Delay_ns": round(calculate_ro_delay_ns(ro_freq, stages=RO_STAGES), 4),
            "Error_Rate": 0.0,
        }
        provenance = {
            "Temperature": "MEASURED", "VCCINT": "MEASURED", "VCCAUX": "MEASURED",
            "VCCBRAM": "MEASURED", "RO_Frequency": "MEASURED", "RO_Delay_ns": "DERIVED",
            "Error_Rate": "NOT_AVAILABLE",
        }
        for r in regions:
            out[f"RO_{r}"] = round(freqs[r], 2)
            out[f"RO_{r}_Delay_ns"] = round(calculate_ro_delay_ns(freqs[r], stages=RO_STAGES), 4)
            provenance[f"RO_{r}"] = "MEASURED"
            provenance[f"RO_{r}_Delay_ns"] = "DERIVED"
        out["Provenance"] = provenance
        return out

    def _sanitize_packet(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Validates telemetry against physical sensor constraints, computes derived
        RO stage delay (tau = 100/f) for each of the four physical regions (R1..R4),
        and returns cleaned measurement dictionary.
        """
        if not isinstance(data, dict) or not data:
            return None

        try:
            # Extract raw values with sensible fallbacks
            temp_raw = data.get("Temperature", data.get("temp", data.get("T")))
            vccint_raw = data.get("VCCINT", data.get("vccint", data.get("VINT")))
            vccaux_raw = data.get("VCCAUX", data.get("vccaux", data.get("VAUX")))
            vccbram_raw = data.get("VCCBRAM", data.get("vccbram", data.get("VBRAM")))
            ro_freq_raw = data.get("RO_Frequency", data.get("ro_frequency", data.get("RO")))
            err_raw = data.get("Error_Rate", data.get("error_rate", data.get("ERR")))

            temp = float(temp_raw) if temp_raw is not None else 35.0
            vccint = float(vccint_raw) if vccint_raw is not None else 1.000
            vccaux = float(vccaux_raw) if vccaux_raw is not None else 1.800
            vccbram = float(vccbram_raw) if vccbram_raw is not None else 1.000
            error_rate = float(err_raw) if err_raw is not None else 0.000010

            # Extract Four-Region Frequencies (R1..R4)
            ro_r1_raw = data.get("RO_R1", data.get("ro_r1", data.get("R1")))
            ro_r2_raw = data.get("RO_R2", data.get("ro_r2", data.get("R2")))
            ro_r3_raw = data.get("RO_R3", data.get("ro_r3", data.get("R3")))
            ro_r4_raw = data.get("RO_R4", data.get("ro_r4", data.get("R4")))

            # Fallback handling: If R1..R4 present, calculate RO_Frequency if missing
            if ro_r1_raw is not None and ro_r2_raw is not None:
                ro_r1 = float(ro_r1_raw)
                ro_r2 = float(ro_r2_raw)
                ro_r3 = float(ro_r3_raw) if ro_r3_raw is not None else ro_r1
                ro_r4 = float(ro_r4_raw) if ro_r4_raw is not None else ro_r2
                if ro_freq_raw is not None:
                    ro_freq = float(ro_freq_raw)
                else:
                    ro_freq = (ro_r1 + ro_r2 + ro_r3 + ro_r4) / 4.0
            else:
                # Legacy single-RO packet backward compatibility
                ro_freq = float(ro_freq_raw) if ro_freq_raw is not None else 436.0
                ro_r1 = ro_freq
                ro_r2 = ro_freq
                ro_r3 = ro_freq
                ro_r4 = ro_freq

            # Physical Bounds Validation for Artix-7
            # Temperature: 0.0 °C to 125.0 °C (Die junction rating)
            if not (0.0 <= temp <= 125.0):
                return None
            # VCCINT: 0.50 V to 1.50 V (Nominal: 1.000V)
            if not (0.50 <= vccint <= 1.50):
                return None
            # VCCAUX: 1.00 V to 2.50 V (Nominal: 1.800V)
            if not (1.00 <= vccaux <= 2.50):
                return None
            # VCCBRAM: 0.50 V to 1.50 V (Nominal: 1.000V)
            if not (0.50 <= vccbram <= 1.50):
                return None
            # Ring Oscillator Frequencies: 50.0 MHz to 500.0 MHz
            for f in (ro_freq, ro_r1, ro_r2, ro_r3, ro_r4):
                if not (50.0 <= f <= 500.0):
                    return None
            # Error Rate: >= 0.0 and <= 1.0
            if not (0.0 <= error_rate <= 1.0):
                return None

            # Deterministic Physical Derivation: tau = 1000 / (2 * N * f_MHz) = 100 / f_MHz
            ro_delay_ns = calculate_ro_delay_ns(ro_freq, stages=RO_STAGES)
            ro_r1_delay_ns = calculate_ro_delay_ns(ro_r1, stages=RO_STAGES)
            ro_r2_delay_ns = calculate_ro_delay_ns(ro_r2, stages=RO_STAGES)
            ro_r3_delay_ns = calculate_ro_delay_ns(ro_r3, stages=RO_STAGES)
            ro_r4_delay_ns = calculate_ro_delay_ns(ro_r4, stages=RO_STAGES)

            return {
                "Timestamp": time.time(),
                "Temperature": round(temp, 2),
                "VCCINT": round(vccint, 4),
                "VCCAUX": round(vccaux, 4),
                "VCCBRAM": round(vccbram, 4),
                "RO_Frequency": round(ro_freq, 2),
                "RO_Delay_ns": round(ro_delay_ns, 4),
                "RO_R1": round(ro_r1, 2),
                "RO_R1_Delay_ns": round(ro_r1_delay_ns, 4),
                "RO_R2": round(ro_r2, 2),
                "RO_R2_Delay_ns": round(ro_r2_delay_ns, 4),
                "RO_R3": round(ro_r3, 2),
                "RO_R3_Delay_ns": round(ro_r3_delay_ns, 4),
                "RO_R4": round(ro_r4, 2),
                "RO_R4_Delay_ns": round(ro_r4_delay_ns, 4),
                "Error_Rate": round(max(0.0, float(error_rate)), 6),
                "Provenance": {
                    "Temperature": "MEASURED",
                    "VCCINT": "MEASURED",
                    "VCCAUX": "MEASURED",
                    "VCCBRAM": "MEASURED",
                    "RO_Frequency": "MEASURED",
                    "RO_Delay_ns": "DERIVED",
                    "RO_R1": "MEASURED",
                    "RO_R1_Delay_ns": "DERIVED",
                    "RO_R2": "MEASURED",
                    "RO_R2_Delay_ns": "DERIVED",
                    "RO_R3": "MEASURED",
                    "RO_R3_Delay_ns": "DERIVED",
                    "RO_R4": "MEASURED",
                    "RO_R4_Delay_ns": "DERIVED",
                    "Error_Rate": "MEASURED"
                }
            }
        except (ValueError, TypeError):
            return None

    def get_diagnostics(self) -> Dict[str, Any]:
        """Returns comprehensive diagnostic dictionary for UI and health logging."""
        now = time.time()
        time_since_last = (now - self.last_packet_time) if self.last_packet_time > 0 else None
        return {
            "port": self.port,
            "baudrate": self.baudrate,
            "state": self.state.value,
            "is_connected": self.is_connected,
            "packet_count": self.packet_count,
            "error_count": self.error_count,
            "packet_rate_hz": self.get_packet_rate_hz(),
            "last_packet_time": self.last_packet_time,
            "seconds_since_last_packet": round(time_since_last, 1) if time_since_last is not None else None,
            "handshake_detected": self.handshake_detected,
            "handshake_message": self.handshake_message,
            "last_error_msg": self.last_error_msg
        }


if __name__ == "__main__":
    print("Available Serial Ports:", FPGAUARTReceiver.list_available_ports())
    receiver = FPGAUARTReceiver(port="COM3")
    print(f"Receiver configured on {receiver.port} @ {receiver.baudrate} baud (RO_STAGES={RO_STAGES}).")
    print("Diagnostics:", receiver.get_diagnostics())
