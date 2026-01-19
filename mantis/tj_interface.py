# Interface to the TJ-monopix DAQ

# import tj monopix scanbase
# receives configurations from mantis and sent them to tjs start and stop scans
# obtain status, logs, online monitor data
# save data


import threading

import toml
from tjmonopix2.scans.scan_ext_trigger import ExtTriggerScan

DEFAULT_CONFIG_FILE = "/home/wiebke/git/mantis/mantis/configuration.toml"  # os.path.join(PROJECT_FOLDER, 'system', 'default.cfg.yaml')


class TJ_Control:
    def __init__(self, config_file=None):
        if config_file is None:
            config_file = DEFAULT_CONFIG_FILE

        with open(config_file) as f:
            tab = toml.load(f)

        self.testbench = tab
        self.scan_conf = tab["scan_configuration"]

        self.thread = None
        self.scan_ext = None

    def initialize(self):
        self.scan_ext = ExtTriggerScan(
            bench_config=self.testbench, scan_config=self.scan_conf
        )
        self.scan_ext.init()

    def configure(self):
        self.scan_ext.configure()

    def start_scan(self):
        if self.thread and self.thread.is_alive():
            print("Scan already running")
            return

        self.scan_ext.stop_scan.clear()
        self.thread = threading.Thread(target=self.scan_ext.scan, daemon=True)
        self.thread.start()

    def stop_scan(self):
        # Signal the scan loop to stop
        if self.scan_ext:
            self.scan_ext.stop_scan.set()

        # Wait for thread to finish
        if self.thread:
            self.thread.join()
            self.thread = None

    def reconfigure(self, new_config_file=None):
        if new_config_file:
            with open(new_config_file) as f:
                tab = toml.load(f)
            self.testbench = tab
            self.scan_conf = tab["scan_configuration"]

        self.scan_ext.configuration["scan"] = self.scan_conf
        self.scan_ext.configure()
