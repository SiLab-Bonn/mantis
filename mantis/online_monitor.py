# %gui qt
import toml
import numpy as np
from numba import njit

from mantis.receiver import TJReceiver
from mantis.mini_interpreter import RawDataInterpreter

hit_dtype = np.dtype(
    [
        ("col", "<i2"),
        ("row", "<i2"),
        ("timestamp", "<i8"),
    ]
)


@njit(cache=True)
def correlate_hits_numba(
    ref_cols, ref_rows, ref_ts, dut_cols, dut_rows, dut_ts, x_hist, y_hist, dt
):
    # n_ref = ref_cols.shape[0]
    n_dut = dut_cols.shape[0]

    j_start = 0
    i = 0
    # for i in range(n_ref):
    for ts_ref in ref_ts:
        # ts_ref = ref_ts[i]

        # Move j_start forward until DUT timestamps are within [ts_ref - dt, ...]
        while j_start < n_dut and dut_ts[j_start] < ts_ref - dt:
            j_start += 1

        # From j_start, walk forward while within [ts_ref - dt, ts_ref + dt]
        j = j_start
        while j < n_dut and dut_ts[j] <= ts_ref + dt:
            x_hist[ref_cols[i], dut_cols[j]] += 1
            y_hist[ref_rows[i], dut_rows[j]] += 1
            j += 1
        i += 1


class OnlineMonitor:
    def __init__(self, config_file):
        self.config_file = config_file

        self.frontends, self.rx_ids, self.chip_sn = self.load_config()
        self.num_chips = len(self.frontends)

        self.received_data = [None] * self.num_chips

        self.total_occupancy = [None] * self.num_chips
        self.last_packet_timestamp = [None] * self.num_chips
        self.last_hits = [None] * self.num_chips
        self.total_hits = [0] * self.num_chips
        self.mask = [None] * self.num_chips

        self.last_correlated_pairs = set()

        self.interpreters = [RawDataInterpreter(rx_id=rx_id) for rx_id in self.rx_ids]
        [interpreter.reset() for interpreter in self.interpreters]
        # Correlation histograms: one pair per chip combination (i < j)
        self.hit_corr = {}
        for i in range(self.num_chips):
            for j in range(i + 1, self.num_chips):
                self.hit_corr[(i, j)] = {
                    "col_col": np.zeros((512, 512), dtype=np.uint32),
                    "row_row": np.zeros((512, 512), dtype=np.uint32),
                }

        self.setup_receivers()

    def load_config(self):
        cfg = toml.load(self.config_file)

        frontends = []
        rx_ids = []
        chip_sn = []

        modules = cfg.get("modules", {})
        for _, module_data in modules.items():
            for key, entry in module_data.items():
                if not key.startswith("chip_"):
                    continue

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
                    chip_sn.append(csn)

        return frontends, rx_ids, chip_sn

    def setup_receivers(self):
        from functools import partial

        self.receivers = []
        for list_index, fe in enumerate(self.frontends):
            receiver = TJReceiver(frontend=fe)
            receiver.worker.data.connect(partial(self.handle_data, list_index))
            receiver.start()
            self.receivers.append(receiver)

    def handle_data(self, list_index, data):
        self.received_data[list_index] = data

    def make_hitmap(self, raw_data, rx_id, interpreter):
        raw_data = raw_data.astype(np.uint32, copy=False)

        # interpreter.reset()
        hit_buffer = np.zeros(4 * len(raw_data), dtype=hit_dtype)

        hits = interpreter.interpret(raw_data, hit_buffer)
        occ = interpreter.get_occ()

        # hits = hit_buffer
        return occ, hits

    def process_receiver(self, list_index):
        packet = self.received_data[list_index]
        if packet is None:
            return None

        self.received_data[list_index] = None

        raw_data = packet["raw"]
        meta = packet.get("meta", {})

        ts = meta.get("timestamp_start", meta.get("timestamp_stop", None))
        self.last_packet_timestamp[list_index] = ts

        interpreter = self.interpreters[list_index]
        occ, hits = self.make_hitmap(raw_data, self.rx_ids[list_index], interpreter)

        if self.total_occupancy[list_index] is None:
            self.total_occupancy[list_index] = np.zeros_like(occ, dtype=np.uint32)

        self.total_occupancy[list_index] = occ
        self.last_hits[list_index] = hits
        self.total_hits[list_index] += hits.shape[0]

        # # Apply mask only if mask exists and checkbox is active
        # if self.mask[list_index] is not None:
        #     mask = self.mask[list_index]
        #     display_occ = occ.copy()
        #     display_occ[mask] = 0
        #     valid = ~mask[hits["col"], hits["row"]]
        #     hits = hits[valid]
        #     self.last_hits[list_index] = hits

        if ts is not None:
            for other in range(self.num_chips):
                if other == list_index:
                    continue

                other_ts = self.last_packet_timestamp[other]
                other_hits = self.last_hits[other]

                if other_ts is None or other_hits is None:
                    continue

                pair_id = (min(list_index, other), max(list_index, other), ts, other_ts)

                # skip already correlated pairs
                if pair_id in self.last_correlated_pairs:
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

                self.last_correlated_pairs.add(pair_id)

        return self.total_occupancy[list_index]

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
        if ref_cols.size == 0 or dut_cols.size == 0:
            return

        correlate_hits_numba(
            ref_cols, ref_rows, ref_ts, dut_cols, dut_rows, dut_ts, x_hist, y_hist, dt
        )

    def masking(self, chip_index):
        occ = self.total_occupancy[chip_index]
        if occ is None:
            return None

        mu = occ.mean()
        sigma = occ.std()
        threshold = mu + 3 * sigma

        # True = masked pixel
        mask = occ > threshold
        return mask

    def reset_occupancy(self):
        [interpreter.reset() for interpreter in self.interpreters]
        self.total_occupancy = [None] * self.num_chips
        self.last_packet_timestamp = [None] * self.num_chips
        self.last_hits = [None] * self.num_chips
        self.total_hits = [0] * self.num_chips
        self.last_correlated_pairs.clear()
        for key in self.hit_corr:
            self.hit_corr[key]["col_col"].fill(0)
            self.hit_corr[key]["row_row"].fill(0)
