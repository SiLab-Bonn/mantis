import toml
from pathlib import Path
from tjmonopix2.scans.scan_ext_trigger import ExtTriggerScan

BASE_DIR = Path(__file__).resolve().parent

FIXED_CONFIG_FILE = BASE_DIR / "fixed_configuration.toml"
USER_CONFIG_FILE = BASE_DIR / "user_configuration.toml"

scan_type = ExtTriggerScan


def load_merged_config(fixed_file, user_file):
    fixed = toml.load(fixed_file)
    user = toml.load(user_file)

    cfg = fixed.copy()

    # Shallow-merge user config (user overrides fixed)
    for key, value in user.items():
        if isinstance(value, dict) and key in cfg:
            cfg[key].update(value)
        else:
            cfg[key] = value

    # Apply chip defaults
    chip_defaults = cfg.get("chip_defaults", {})
    modules = cfg.get("modules", {})

    for module in modules.values():
        for name, chip in module.items():
            if name.startswith("chip_"):
                for k, v in chip_defaults.items():
                    chip.setdefault(k, v)

    return cfg


class TJ_Control:
    def __init__(self, user_config_file=None, scan_type=ExtTriggerScan):
        # Always resolve the main config file ONCE
        if user_config_file is None:
            self.main_config_file = USER_CONFIG_FILE
        else:
            self.main_config_file = user_config_file

        # Never let chip config fields overwrite this
        self.user_config_file = self.main_config_file

        self.scan_type = scan_type
        self.scan_ext = None

        self.load_config()

    def load_config(self):
        self.testbench = load_merged_config(FIXED_CONFIG_FILE, self.user_config_file)
        self.scan_conf = self.testbench["scan_configuration"]
        self.daq_conf = self.testbench["general"]["daq_conf"]

    def initialize(self):
        self.shutdown()
        self.load_config()

        try:
            self.scan_ext = self.scan_type(
                bench_config=self.testbench,
                scan_config=self.scan_conf,
                daq_conf=self.daq_conf,
            )
        except Exception as e:
            print("Initialization failed:", e)
            self.scan_ext = None
            raise

    def configure(self):
        self.initialize()

        if self.scan_ext is None:
            print("Configuration failed: no scan object")
            return

        try:
            if hasattr(self.scan_ext, "_init_environment"):
                self.scan_ext._init_environment()

            print("DEBUG: Initialized DAQ:", self.scan_ext.daq)

            print("DEBUG: _init_environment complete")

            if hasattr(self.scan_ext, "_init_hardware"):
                self.scan_ext._init_hardware(force=False)

            print("DEBUG: _init_hardware complete")

            self.scan_ext.initialized = True

            if hasattr(self.scan_ext, "configuration"):
                self.scan_ext.configuration["scan"] = self.scan_conf

            print("DEBUG: configuration complete")

            if hasattr(self.scan_ext, "configure"):
                self.scan_ext.configure()

            print("DEBUG: configure complete")

        except Exception as e:
            print("Configuration failed:", e)

    # need to shut down before initializing (again) to clear occupied socket connections
    def shutdown(self):
        if not self.scan_ext:
            return

        try:
            try:
                self.scan_ext.stop_scan.set()
            except Exception:
                pass

            try:
                self.scan_ext.close()
            except Exception as e:
                print("Warning: close failed:", e)

        except Exception as e:
            print("Shutdown error:", e)

        self.scan_ext = None

    def start_scan(self):
        if not self.scan_ext:
            print("Not initialized")
            return

        if hasattr(self.scan_ext, "_init_files"):
            self.scan_ext._init_files()

        if hasattr(self.scan_ext, "stop_scan"):
            self.scan_ext.stop_scan.clear()

        self.scan_ext.scan()
        self.scan_ext.analyze()

    def stop_scan(self):
        if self.scan_ext:
            self.scan_ext.stop_scan.set()
