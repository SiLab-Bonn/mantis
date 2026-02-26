class Scan_Mock:
    def __init__(self, testbench=None, scan_config=None):
        self.testbench = testbench
        self.scan_config = scan_config
        self.user_config_file = "../user_configuration.toml"

    def _init_environment(self):
        pass

    def _init_hardware(self, force=False):
        pass

    def configure(self):
        pass

    def close(self):
        pass

    def _init_files(self):
        pass

    def scan(self):
        pass

    def analyze(self):
        pass

    def stop_scan(self):
        pass
