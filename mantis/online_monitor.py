# %gui qt
from receiver import TJReceiver
from mantis.mini_interpreter import RawDataInterpreter
from PyQt6 import QtCore
from PyQt6.QtWidgets import QApplication
import numpy as np
import matplotlib.pyplot as plt
# %matplotlib qt

hit_dtype = np.dtype(
    [
        ("col", "<i2"),
        ("row", "<i2"),
        ("timestamp", "<i8"),
        ("rx_id", "<i2"),
    ]
)

frontends = ["tcp://127.0.0.1:5501", "tcp://127.0.0.1:6501"]
# frontends need to be taken from config file

app = QApplication.instance() or QApplication([])

num_chips = len(frontends)

fig, axes = plt.subplots(1, num_chips, figsize=(6 * num_chips, 6))

imgs = []
for ax in axes:
    img = ax.imshow(np.zeros((100, 100)), cmap="hot", interpolation="nearest")
    imgs.append(img)
    fig.colorbar(img, ax=ax)
    ax.set_title("TJ-Monopix2 Hitmap")
    ax.set_xlabel("Column")
    ax.set_ylabel("Row")
    fig.show()


class OnlineMonitor:
    def __init__(self, img, rx_id):
        self.img = img
        self.rx_id = rx_id
        self.received_data = []
        self.total_occupancy = None
        self.last_processed = -1

    def handle_data(self, data):
        self.received_data.append(data)

    def make_hitmap(self, raw_data, rx_id=0):
        interpreter = RawDataInterpreter(rx_id=self.rx_id)
        hit_buffer = np.zeros(4 * len(raw_data), dtype=hit_dtype)
        hits = interpreter.interpret(raw_data, hit_buffer)  # noqa: F841
        occupancy = interpreter.hist_occ.sum(axis=2)
        return occupancy

    def update_hitmap(self, occupancy):
        self.img.set_data(occupancy)
        self.img.set_clim(vmin=0, vmax=occupancy.max())
        fig.canvas.draw_idle()

    def process_latest_packet(self):
        if len(self.received_data) == 0:
            return

        if self.last_processed == len(self.received_data) - 1:
            return

        self.last_processed = len(self.received_data) - 1
        packet = self.received_data[self.last_processed]
        raw_data = packet["raw"].astype(np.uint32)

        occ = self.make_hitmap(raw_data)

        if self.total_occupancy is None:
            self.total_occupancy = np.zeros_like(occ)

        self.total_occupancy += occ

        self.update_hitmap(self.total_occupancy)


monitors = []
receivers = []

for i, fe in enumerate(frontends):
    monitor = OnlineMonitor(imgs[i], rx_id=i)
    # rx_id stuff is a quick fix, needs to be updated and connected to config file
    monitors.append(monitor)

    tj_receiver = TJReceiver(frontend=fe)
    tj_receiver.worker.data.connect(monitor.handle_data)
    tj_receiver.start()
    receivers.append(tj_receiver)


def update_all():
    for m in monitors:
        m.process_latest_packet()


timer = QtCore.QTimer()
timer.timeout.connect(update_all)
timer.start(500)  # run every x ms

app.exec()
