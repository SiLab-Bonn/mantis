# Interface to the power supplies

# Control the power supplies of the telescope
# read current, set voltage of low voltage and high voltage perhaps
# use basil or from scratch with pyserial similar to motor stage ui

import yaml
import toml
from basil.dut import Dut


class PowerSupplyManager:
    def __init__(self, config_file):
        self.config_file = config_file
        self.devices = []

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
        devices = cfg.get("powering", {}).get("devices", {})

        self.devices = []

        for entry in devices.values():
            # Load Basil YAML
            with open(entry["yaml"], "r") as f:
                yaml_data = yaml.safe_load(f)

            # Parse TOML overrides
            conn = self.parse_connection_string(entry.get("connection", ""))

            # Override transfer_layer.init fields
            if "transfer_layer" in yaml_data:
                tl = yaml_data["transfer_layer"][0]
                for k, v in conn.items():
                    tl["init"][k] = v

            # Instantiate DUT
            dut = Dut(yaml_data)
            dut.init()

            # Extract the YAML device name (e.g. "Sourcemeter")
            device_name = dut._conf["hw_drivers"][0]["name"]
            driver = dut[device_name]

            # Patch Keithley 2400 current readback (BASIL bug)
            if device_name == "Keithley2400":
                serial_tl = dut._transfer_layer["Serial"]

                def fixed_get_current():
                    try:
                        # Send SCPI READ? and read back the full line
                        serial_tl.write("READ?\n")
                        raw = serial_tl.read()
                        # Example raw: "+1.000196E-01,+5.282799E-11,+9.91E+37,..."
                        fields = raw.split(",")
                        return float(fields[1])  # correct field for current
                    except Exception as e:
                        print("Current readback error:", repr(e))
                        return float("nan")

                driver.get_current = fixed_get_current

            nch = entry.get("channels", 1)

            # Single-channel SCPI device
            if nch == 1:
                dut_dict = {"CH0": driver}

            # Multi-channel device
            else:
                dut_dict = {}
                for ch in range(nch):
                    try:
                        block = driver[ch]
                    except Exception:
                        try:
                            block = driver.channel(ch)
                        except Exception:
                            raise RuntimeError(
                                f"Device '{entry['name']}' declares {nch} channels "
                                f"but driver '{device_name}' does not support channel indexing."
                            )
                    dut_dict[f"CH{ch}"] = block

            self.devices.append(
                {
                    "name": entry["name"],
                    "dut": dut_dict,
                    "comment": entry.get("comment", ""),
                    "max_voltage": entry.get("max_voltage"),
                    "max_current": entry.get("max_current"),
                    "ocp": entry.get("ocp"),
                    "channels": nch,
                    "channel_comments": entry.get("channel_comments", {}),
                }
            )
