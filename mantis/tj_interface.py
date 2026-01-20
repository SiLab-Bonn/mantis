import threading
import toml
from tjmonopix2.scans.scan_ext_trigger import ExtTriggerScan

DEFAULT_CONFIG_FILE = "/home/wiebke/git/mantis/mantis/configuration.toml"


class TJ_Control:
    def __init__(self, config_file=None):
        if config_file is None:
            config_file = DEFAULT_CONFIG_FILE

        self.config_path = config_file

        with open(self.config_path) as f:
            tab = toml.load(f)

        self.testbench = tab
        self.scan_conf = tab["scan_configuration"]

        self.thread = None
        self.scan_ext = None

    def configure(self):
        # reload file to apply possible changes in between
        with open(self.config_path) as f:
            tab = toml.load(f)

        self.testbench = tab
        self.scan_conf = tab["scan_configuration"]

        # print("Updated Configuration:", tab["scan_configuration"], tab["modules"])

        if self.scan_ext is not None:
            self.scan_ext.configuration["scan"] = self.scan_conf
            self.scan_ext.configure()

    def initialize(self):
        # TJ.stop()
        self.scan_ext = ExtTriggerScan(
            bench_config=self.testbench, scan_config=self.scan_conf
        )
        self.scan_ext.init()

    def start_scan(self):
        if self.thread and self.thread.is_alive():
            print("Scan already running")
            return

        self.scan_ext.stop_scan.clear()
        self.thread = threading.Thread(target=self.scan_ext.scan, daemon=True)
        self.thread.start()

    def stop_scan(self):
        if self.scan_ext:
            self.scan_ext.stop_scan.set()

        if self.thread:
            self.thread.join()
            self.thread = None
