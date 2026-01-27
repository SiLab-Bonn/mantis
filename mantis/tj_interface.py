import toml
from tjmonopix2.scans.scan_ext_trigger import ExtTriggerScan

FIXED_CONFIG_FILE = "/home/wiebke/git/mantis/mantis/fixed_configuration.toml"
USER_CONFIG_FILE = "/home/wiebke/git/mantis/mantis/user_configuration.toml"


def load_config(fixed_file, user_file):
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
    def __init__(self, user_config_file=None):
        self.user_config_file = user_config_file or USER_CONFIG_FILE
        self.load_config()
        self.scan_ext = None

    def load_config(self):
        self.testbench = load_config(FIXED_CONFIG_FILE, self.user_config_file)
        self.scan_conf = self.testbench["scan_configuration"]

    def configure(self):
        # Reload config and reconfigure scan if needed.
        self.load_config()
        try:
            self.shutdown()
            self.scan_ext = ExtTriggerScan(
                bench_config=self.testbench, scan_config=self.scan_conf
            )
        except Exception as e:
            print("Configuration failed:", e)
            self.scan_ext = None
            return
        self.scan_ext._init_environment()
        self.scan_ext._init_hardware(force=False)
        self.scan_ext.initialized = True

        if self.scan_ext is not None:
            self.scan_ext.configuration["scan"] = self.scan_conf
            self.scan_ext.configure()

    def initialize(self):
        try:
            self.shutdown()
            self.scan_ext = ExtTriggerScan(
                bench_config=self.testbench, scan_config=self.scan_conf
            )
        except Exception as e:
            print("Initialization failed:", e)
            self.scan_ext = None
            raise

    # need to shut down before initializing (again) to clear occupied socket connections
    def shutdown(self):
        try:
            if self.scan_ext:
                try:
                    self.scan_ext.stop_scan.set()
                except Exception:
                    pass

                try:
                    self.scan_ext.close()
                except Exception as e:
                    print("Warning: close failed:", e)
            else:
                pass
        except Exception as e:
            print("Shutdown error:", e)

        self.scan_ext = None

    def start_scan(self):
        self.scan_ext._init_files()
        if not self.scan_ext:
            print("Not initialized")
            return

        self.scan_ext.stop_scan.clear()
        self.scan_ext.scan()

    def stop_scan(self):
        if self.scan_ext:
            self.scan_ext.stop_scan.set()
