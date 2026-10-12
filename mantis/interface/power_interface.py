import yaml
import toml
from basil.dut import Dut
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

POWER_CONFIGS = BASE_DIR / "power_devices"


class PowerDevice:
    def __init__(self, device_id, name, dut, channels, meta):
        self.device_id = device_id
        self.name = name
        self.dut = dut
        self.channels = channels
        self.meta = meta


class PowerSupplyManager:
    def __init__(self, config_file):
        self.config_file = config_file
        self.devices = {}

    def parse_connection_string(self, s):
        conn = {}
        if not s:
            return conn
        for part in s.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                conn[k.strip()] = v.strip()
        return conn

    def load(self):
        cfg = toml.load(self.config_file)
        entries = cfg.get("powering", {}).get("devices", {})

        for device_id, entry in entries.items():
            try:
                with open(entry["yaml"], "r") as f:
                    yaml_data = yaml.safe_load(f)
            except KeyError:
                default_path = POWER_CONFIGS / str(device_id + ".yaml")
                with open(default_path, "r") as f:
                    yaml_data = yaml.safe_load(f)

            conn = self.parse_connection_string(entry.get("connection", ""))
            if "transfer_layer" in yaml_data:
                tl = yaml_data["transfer_layer"][0]
                for k, v in conn.items():
                    tl["init"][k] = v

            channels = {}
            initialized = False

            try:  # still start mantis, when devices are turned off
                dut = Dut(yaml_data)
                dut.init()
                driver_name = dut._conf["hw_drivers"][0]["name"]
                driver_type = dut._conf["hw_drivers"][0]["type"]
                driver = dut[driver_name]
                initialized = True
            except Exception as e:
                print(f"[Powering] Device {device_id} failed to initialize: {e}")
                dut = None
                driver = None

            nch = entry.get("channels", 1)
            if driver is not None:
                driver_type = dut._conf["hw_drivers"][0]["type"].lower()

                if driver_type.startswith("tti"):
                    for ch in range(nch):
                        channels[f"CH{ch}"] = (driver, ch + 1)
                else:
                    if nch == 1:
                        channels["CH0"] = driver
                    else:
                        for ch in range(nch):
                            try:
                                block = driver[ch]
                            except Exception:
                                block = driver.channel(ch)
                            channels[f"CH{ch}"] = block
            else:
                for ch in range(nch):
                    channels[f"CH{ch}"] = None

            meta = {
                "max_voltage": entry.get("max_voltage"),
                "max_current": entry.get("max_current"),
                "ocp": entry.get("ocp"),
                "comment": entry.get("comment", ""),
                "initialized": initialized,
                "channel_comments": entry.get("channel_comments", {}),
            }

            device = PowerDevice(
                device_id=device_id,
                name=entry["name"],
                dut=dut,
                channels=channels,
                meta=meta,
            )

            self.devices[device_id] = device

    def apply_settings(self, device_id, channel_id, voltage, current):
        dev = self.devices[device_id]
        ch = dev.channels[channel_id]

        if isinstance(ch, tuple):
            drv, idx = ch  # TTi
        else:
            drv, idx = ch, None  # Keithley

        if dev.meta["max_voltage"] and voltage > dev.meta["max_voltage"]:
            raise ValueError(f"Voltage exceeds limit for {device_id}")
        if dev.meta["max_current"] and current > dev.meta["max_current"]:
            raise ValueError(f"Current exceeds limit for {device_id}")

        # Keithley: optional range selection
        if idx is None and hasattr(drv, "source_volt"):
            drv.source_volt()

        if idx is None and hasattr(drv, "set_voltage_range"):
            abs_v = abs(voltage)
            if abs_v <= 0.2:
                drv.set_voltage_range(0.2)
            elif abs_v <= 2:
                drv.set_voltage_range(2)
            elif abs_v <= 20:
                drv.set_voltage_range(20)
            else:
                drv.set_voltage_range(200)

        # Apply settings
        if idx is None:
            # Keithley
            drv.set_voltage(voltage)
            drv.set_current_limit(current)
        else:
            # TTi
            drv.set_voltage(voltage, channel=idx)
            drv.set_current_limit(current, channel=idx)

    def readback(self, device_id, channel_id):
        ch = self.devices[device_id].channels[channel_id]

        if self._get_on(ch) == 0:
            return {"voltage": None, "current": None, "current_limit": None}

        # TTi
        if isinstance(ch, tuple):
            drv, idx = ch
            v = drv.get_voltage(idx)
            i = drv.get_current(idx)
            ilim = drv.get_current_limit(idx)
            return {"voltage": v, "current": i, "current_limit": ilim}

        # Keithley
        try:
            raw = ch.get_current()
            parts = str(raw).split(",")
            val_i = float(parts[1]) if parts else None
            val_v = float(parts[0]) if parts else None
        except Exception:
            val_i = None
            val_v = None

        try:
            raw_ilim = ch.get_current_limit()
            parts_ilim = str(raw_ilim).split(",")
            val_ilim = float(parts_ilim[0]) if parts_ilim else None
        except Exception:
            val_ilim = None

        return {"voltage": val_v, "current": val_i, "current_limit": val_ilim}

    def _get_on(self, ch):
        if not isinstance(ch, tuple):
            try:
                return int(ch.get_on())
            except Exception:
                return 0

        drv, idx = ch
        ret = drv.ask(f"OP{idx}?")
        try:
            return int(ret.strip())
        except Exception:
            return 0
