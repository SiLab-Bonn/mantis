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
        self.frontends, self.rx_ids, self.chip_sn = self.load_config()
        self.num_chips = len(self.frontends)

        # Per-receiver buffers
        self.received_data = [[] for _ in range(self.num_chips)]
        self.total_occupancy = [None] * self.num_chips
        self.last_processed = [-1] * self.num_chips

        # Per-receiver last packet timestamp
        self.last_packet_timestamp = [None] * self.num_chips

        # Receivers
        self.receivers = []
        self.setup_receivers()

        # Correlation histograms
        self.hit_corr = {}
        for i in range(self.num_chips):
            for j in range(i + 1, self.num_chips):
                self.hit_corr[(i, j)] = {
                    "col_col": np.zeros((512, 512), dtype=np.uint32),
                    "row_row": np.zeros((512, 512), dtype=np.uint32),
                }

        self.last_event = [None] * self.num_chips
        self.last_hits = [None] * self.num_chips

    def load_config(self):
        cfg = toml.load(self.config_file)

        frontends = []
        rx_ids = []
        self.chip_sn = []

        modules = cfg.get("modules", {})

        for module_name, module_data in modules.items():
            for key, entry in module_data.items():
                if key.startswith("chip_"):
                    fe = entry.get("send_data")
                    rx_str = entry.get("receiver")
                    csn = entry.get("chip_sn")

                    if isinstance(rx_str, str) and rx_str.startswith("rx"):
                        rx_id = int(rx_str[2:])
                    else:
                        rx_id = None

                    if fe is not None:
                        frontends.append(fe)
                        rx_ids.append(rx_id)
                        self.chip_sn.append(csn)

        return frontends, rx_ids, self.chip_sn

    def setup_receivers(self):
        from functools import partial

        for list_index, fe in enumerate(self.frontends):
            receiver = TJReceiver(frontend=fe)
            receiver.worker.data.connect(partial(self.handle_data, list_index))
            receiver.start()
            self.receivers.append(receiver)

    def handle_data(self, list_index, data):
        self.received_data[list_index].append(data)

    def make_hitmap(self, raw_data, rx_id):
        interpreter = RawDataInterpreter(rx_id=rx_id)
        hit_buffer = np.zeros(4 * len(raw_data), dtype=hit_dtype)
        interpreter.interpret(raw_data, hit_buffer)

        occ = interpreter.hist_occ.sum(axis=2)
        hits = hit_buffer
        return occ, hits

    def process_receiver(self, list_index):
        data_list = self.received_data[list_index]

        if not data_list:
            return None

        if self.last_processed[list_index] == len(data_list) - 1:
            return None

        self.last_processed[list_index] = len(data_list) - 1
        packet = data_list[self.last_processed[list_index]]

        raw_data = packet["raw"].astype(np.uint32)

        meta = packet.get("meta", {})
        ts = meta.get("timestamp_start", meta.get("timestamp_stop", None))
        self.last_packet_timestamp[list_index] = ts

        occ, hits = self.make_hitmap(raw_data, self.rx_ids[list_index])

        self.last_event[list_index] = occ
        self.last_hits[list_index] = hits

        if self.total_occupancy[list_index] is None:
            self.total_occupancy[list_index] = np.zeros_like(occ)

        self.total_occupancy[list_index] += occ

        # Correlations
        for other in range(self.num_chips):
            if other == list_index:
                continue

            other_ts = self.last_packet_timestamp[other]
            other_hits = self.last_hits[other]

            if ts is None or other_ts is None:
                continue
            if other_hits is None:
                continue
            if abs(ts - other_ts) > 1:
                continue

            key = (min(list_index, other), max(list_index, other))
            h = self.hit_corr[key]

            self.correlate_hits(
                hits["col"],
                hits["row"],
                hits["timestamp"],
                other_hits["col"],
                other_hits["row"],
                other_hits["timestamp"],
                h["col_col"],
                h["row_row"],
            )

        return self.total_occupancy[list_index]

    def reset_occupancy(self):
        self.total_occupancy = [None] * self.num_chips
        self.last_processed = [-1] * self.num_chips
        self.last_packet_timestamp = [None] * self.num_chips
        for key in self.hit_corr:
            self.hit_corr[key]["col_col"].fill(0)
            self.hit_corr[key]["row_row"].fill(0)

    def correlate_hits(
        self,
        ref_cols,
        ref_rows,
        ref_ts,
        dut_cols,
        dut_rows,
        dut_ts,
        x_hist,
        y_hist,
        dt=50,
    ):
        if len(ref_cols) == 0 or len(dut_cols) == 0:
            return

        time_match = np.abs(ref_ts[:, None] - dut_ts[None, :]) <= dt
        ref_idx, dut_idx = np.where(time_match)

        np.add.at(x_hist, (ref_cols[ref_idx], dut_cols[dut_idx]), 1)
        np.add.at(y_hist, (ref_rows[ref_idx], dut_rows[dut_idx]), 1)
