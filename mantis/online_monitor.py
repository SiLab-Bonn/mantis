# %gui qt
from mantis.receiver import TJReceiver
from mantis.mini_interpreter import RawDataInterpreter
import numpy as np
import toml

hit_dtype = np.dtype(
    [
        ("col", "<i2"),
        ("row", "<i2"),
        ("timestamp", "<i8"),
        ("rx_id", "<i2"),
    ]
)

USER_CONFIG_FILE = "/home/wiebke/git/mantis/mantis/user_configuration.toml"


class OnlineMonitor:
    def __init__(self, config_file):
        self.config_file = config_file

        # Load frontends + rx_ids
        self.frontends, self.rx_ids = self.load_config()
        self.num_chips = len(self.frontends)

        # Per-receiver buffers
        self.received_data = [[] for _ in range(self.num_chips)]
        self.total_occupancy = [None] * self.num_chips
        self.last_processed = [-1] * self.num_chips

        # Receivers
        self.receivers = []
        self.setup_receivers()

    def load_config(self):
        cfg = toml.load(self.config_file)

        frontends = []
        rx_ids = []

        modules = cfg.get("modules", {})

        for module_name, module_data in modules.items():
            for key, entry in module_data.items():
                if key.startswith("chip_"):
                    fe = entry.get("send_data")
                    rx_str = entry.get("receiver")

                    if isinstance(rx_str, str) and rx_str.startswith("rx"):
                        rx_id = int(rx_str[2:])
                    else:
                        rx_id = None

                    if fe is not None:
                        frontends.append(fe)
                        rx_ids.append(rx_id)

        return frontends, rx_ids

    def setup_receivers(self):
        for list_index, fe in enumerate(self.frontends):
            receiver = TJReceiver(frontend=fe)
            receiver.worker.data.connect(
                lambda data, idx=list_index: self.handle_data(idx, data)
            )
            receiver.start()
            self.receivers.append(receiver)

    def handle_data(self, list_index, data):
        self.received_data[list_index].append(data)

    def make_hitmap(self, raw_data, rx_id):
        interpreter = RawDataInterpreter(rx_id=rx_id)
        hit_buffer = np.zeros(4 * len(raw_data), dtype=hit_dtype)
        interpreter.interpret(raw_data, hit_buffer)
        return interpreter.hist_occ.sum(axis=2)

    def process_receiver(self, list_index):
        data_list = self.received_data[list_index]

        if not data_list:
            return None

        if self.last_processed[list_index] == len(data_list) - 1:
            return None

        self.last_processed[list_index] = len(data_list) - 1
        packet = data_list[self.last_processed[list_index]]

        raw_data = packet["raw"].astype(np.uint32)
        occ = self.make_hitmap(raw_data, self.rx_ids[list_index])

        if self.total_occupancy[list_index] is None:
            self.total_occupancy[list_index] = np.zeros_like(occ)

        self.total_occupancy[list_index] += occ
        return self.total_occupancy[list_index]
