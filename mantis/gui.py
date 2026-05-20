# Graphical user interface

# pyQT6 similar to online monitor
# buttons to click (start, configure, stop, restart, power cycle) and live plots to admire (hitmap, correlation...)
# data is should be handled separately to gui in some kind of interpreter

import numpy as np
import math
import sys
import os
import toml
import time
import logging
import ast
from PyQt6.QtCore import pyqtSignal, QTimer, QThread, QObject, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from mantis.tj_interface import TJ_Control
from mantis.online_monitor import OnlineMonitor
from mantis.power_interface import PowerSupplyManager
import pyqtgraph as pg

from tjmonopix2.scans.scan_ext_trigger import ExtTriggerScan
from tjmonopix2.scans.scan_analog import AnalogScan
from tjmonopix2.scans.scan_source import SourceScan


class ButtonManager:
    class StyledButton(QPushButton):
        def __init__(self, text, color="green"):
            super().__init__(text)
            self.default_color = color
            self.set_color(color)

        # viridis colors
        def set_color(self, color):
            themes = {
                "yellow": "rgba(253, 231, 37, 0.5)",
                "green": "rgba(122, 209, 81, 0.5)",
                "mint": "rgba(34, 168, 132, 0.5)",
                "lightblue": "rgba(42, 120, 142, 0.5)",
                "darkblue": "rgba(65, 68, 135, 0.5)",
                "purple": "rgba(68, 1, 84, 0.5)",
                "gray": "rgba(159, 161, 164, 0.5)",
            }

            bg = themes.get(color, color)
            self.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {bg};
                    color: black;
                    border: 2px solid black;
                    border-radius: 4px;
                    padding: 6px;
                }}
                """
            )

        def set_busy(self):
            self.set_color("gray")
            QApplication.processEvents()

        def set_ready(self):
            self.set_color(self.default_color)
            QApplication.processEvents()

    # ----- StyledButton end -----

    def make(self, button_specs, target, layout, thread_manager=None):
        for attr_name, label, color, callback, message, threaded in button_specs:
            btn = self.StyledButton(label, color)

            # message optional
            if message:
                btn.message = message
            setattr(target, attr_name, btn)

            if threaded and thread_manager is not None:
                btn.clicked.connect(
                    lambda _, f=callback, b=btn: thread_manager.run_in_thread(f, b)
                )
            else:
                btn.clicked.connect(callback)

            layout.addWidget(btn)


class QtLogHandler(logging.Handler):
    def __init__(self, gui):
        super().__init__()
        self.gui = gui

    def emit(self, record):
        if self.gui.debugging():
            self.gui.append_text.emit(self.format(record))


class Messages:
    def __init__(self, append_text_signal, debug_flag_callable):
        self.append_text = append_text_signal
        self.debugging = debug_flag_callable

    def log(self, text):
        self.append_text.emit(text)

    def route_stdout_like(self, text):
        # Filter empty lines
        if not text.strip():
            return

        # If debugging mode is ON → show EVERYTHING
        if self.debugging():
            self.append_text.emit(text)
            return

        # If debugging mode is OFF → only show selected messages
        important = [
            "ERROR",
            "DEBUG",
            "Warning",
            "failed",
            "Scan started",
            "Scan stopped",
            "Scan complete",
            "Initialization complete",
            "Configuration complete",
        ]

        if any(key in text for key in important):
            self.append_text.emit(text)


class ThreadManager:
    class Worker(QObject):
        finished = pyqtSignal()
        error = pyqtSignal(Exception)

        def __init__(self, fn):
            super().__init__()
            self.fn = fn

        def run(self):
            try:
                self.fn()
            except Exception as e:
                self.error.emit(e)
                return
            self.finished.emit()

    # ----- Worker end -----

    def __init__(self, messages):
        self.messages = messages
        self.threads = []
        self.workers = []

    def run_in_thread(self, fn, button=None, finished_callback=None):
        thread = QThread()
        worker = self.Worker(fn)

        self.threads.append(thread)
        self.workers.append(worker)

        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        # Button handling
        if button is not None:
            button.set_busy()

            worker.error.connect(lambda e, b=button: self._handle_error(e, b))
            worker.finished.connect(lambda b=button: b.set_ready())
            worker.finished.connect(lambda b=button: self.messages.log(b.message))

        # Optional callback
        if finished_callback is not None:
            worker.finished.connect(finished_callback)

        # Cleanup
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda w=worker: self.workers.remove(w))
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self.threads.remove(t))

        thread.start()

    def _handle_error(self, e, button):
        button.set_ready()
        self.messages.log(f"ERROR: {e}")


class ScanControl(QWidget):
    append_text = pyqtSignal(str)

    def __init__(self, controller, monitor_view=None, powering_view=None):
        super().__init__()
        self.TJ = controller
        self.monitor_view = monitor_view
        self.powering_view = powering_view
        self.button_manager = ButtonManager()
        self.messages = Messages(self.append_text, self.debugging)
        self.thread_manager = ThreadManager(self.messages)

        layout = QVBoxLayout()

        # Scan type selector
        self.SCAN_TYPES = {
            "Analog Scan": AnalogScan,
            "Source Scan": SourceScan,
            "External Trigger Scan": ExtTriggerScan,
        }

        self.scan_selector = QComboBox()
        self.scan_selector.addItems(self.SCAN_TYPES.keys())
        layout.addWidget(self.scan_selector)

        # fmt: off
        # Button specification format:
        # (
        #   Internal attribute name:    # how the button is stored on the class (self.btn_start)
        #   Visible label:              # text shown on the button
        #   Color:                      # passed to StyledButton for theming
        #   Callback Function:          # function executed when the button is clicked
        #   Message:                    # message to be shown after operation is completed
        #   Threading:                  # indicates whether the task should be threaded or not
        # )
        button_specs = [
            ("btn_initialize","Initialize","green", self.initialize_clicked, "Initialization complete", True),
            ("btn_conf","Configure","green", self.configure_clicked, "Configuration complete", False),
            ("btn_start","Start Scan","green", self.start_scan_clicked, "Scan complete", True),
            ("btn_stop","Stop Scan","green", self.stop_scan_clicked, None, False),
        ]
        # fmt: on

        self.button_manager.make(
            button_specs, target=self, layout=layout, thread_manager=self.thread_manager
        )

        # Debugging checkbox
        self.cb_debugging = QCheckBox("Debug Level")
        self.cb_debugging.stateChanged.connect(self.debugging)
        layout.addWidget(self.cb_debugging)

        # Terminal
        self.terminal = QPlainTextEdit()
        self.terminal.setReadOnly(True)
        layout.addWidget(self.terminal)

        # Logging handler for Debugging
        self.log_handler = QtLogHandler(self)
        self.log_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] - %(levelname)s %(message)s")
        )

        # Remove all default handlers (otherwise messages appear twice)
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        root_logger.addHandler(self.log_handler)
        root_logger.setLevel(logging.DEBUG)

        # Progress bar
        self.status_label = QLabel("Progress Bar")
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress.setStyleSheet(
            """QProgressBar::chunk {background-color: lightblue;}"""
        )
        layout.addWidget(self.progress)

        self.setLayout(layout)

        self.append_text.connect(self.terminal.appendPlainText)
        sys.stdout = self

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_gui)
        self.timer.start(200)

    def update_gui(self):
        scan = self.TJ.scan_ext

        if scan and hasattr(scan, "pbar"):
            try:
                total = scan.pbar.total
                current = scan.pbar.n
                self.progress.setMaximum(total)
                self.progress.setValue(current)
            except Exception:
                pass

        if scan and hasattr(scan, "stop_scan") and scan.stop_scan.is_set():
            self.status_label.setText("")
        elif scan and hasattr(scan, "pbar"):
            self.status_label.setText("Scan running")
        else:
            self.status_label.setText("")

    def initialize_clicked(self):
        selected = self.scan_selector.currentText()
        self.TJ.scan_type = self.SCAN_TYPES[selected]
        self.TJ.initialize()

    def configure_clicked(self):
        self.TJ.load_config()
        self.thread_manager.run_in_thread(
            self.TJ.configure,
            self.btn_conf,
            finished_callback=lambda: (
                self.monitor_view.reload_monitor(),
                self.powering_view.reload_powering(),
            ),
        )

    def start_scan_clicked(self):
        self.TJ.start_scan()

    def stop_scan_clicked(self):
        if hasattr(self.TJ.scan_ext, "stop_scan"):
            self.TJ.stop_scan()
            self.messages.log(
                "Scan stopped, wait until Scan complete before starting next scan"
            )
            self.btn_start.set_ready()
        else:
            self.messages.log("Stop Scan not available for this scan type")

    def write(self, text):
        self.messages.route_stdout_like(text)

    def debugging(self):
        return self.cb_debugging.isChecked()


class Powering(QWidget):
    append_text = pyqtSignal(str)

    def __init__(self, controller):
        super().__init__()
        self.TJ = controller
        self.button_manager = ButtonManager()
        self.messages = Messages(self.append_text, lambda: False)
        self.thread_manager = ThreadManager(self.messages)

        self.timers = []
        self.readback_labels = {}

        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # Terminal
        self.terminal = QPlainTextEdit()
        self.terminal.setReadOnly(True)
        main_layout.addWidget(self.terminal)

        # self.append_text.connect(self.terminal.appendPlainText)
        self.append_text.connect(self._handle_append_text)

        # Build UI from config
        self.reload_powering()
        # Start unified background polling
        self.thread_manager.run_in_thread(self._poll_all_devices)

    def make_device_panel(self, device):
        page = QWidget()
        hbox = QHBoxLayout()
        vbox = QVBoxLayout(page)

        if device.meta.get("comment"):
            lbl_comment = QLabel(device.meta["comment"])
            lbl_comment.setStyleSheet("color: gray")
            vbox.addWidget(lbl_comment)

        for channel_id in device.channels.keys():
            ch_box = self.make_channel_panel(device, channel_id)
            hbox.addWidget(ch_box)

        hbox.addStretch()
        vbox.addLayout(hbox)
        vbox.addStretch()

        return page

    def make_channel_panel(self, device, channel_id):
        box = QGroupBox(f"Channel {channel_id}")
        outer = QVBoxLayout(box)

        # Add channel comment if present
        comment = device.meta["channel_comments"].get(channel_id, "")
        if comment:
            lbl = QLabel(comment)
            lbl.setStyleSheet("color: gray")
            outer.addWidget(lbl)

        # Settings
        settings_frame = QFrame()
        settings_frame.setFrameShape(QFrame.Shape.Box)
        settings_layout = QGridLayout(settings_frame)

        vset = QLineEdit("0.0")
        iset = QLineEdit("0.0")

        settings_layout.addWidget(QLabel("Voltage [V]"), 0, 0)
        settings_layout.addWidget(vset, 0, 1)

        settings_layout.addWidget(QLabel("Current Limit [A]"), 1, 0)
        settings_layout.addWidget(iset, 1, 1)

        outer.addWidget(QLabel("Settings"))
        outer.addWidget(settings_frame)

        # Readback
        read_frame = QFrame()
        read_frame.setFrameShape(QFrame.Shape.Box)
        read_layout = QGridLayout(read_frame)

        read_v = QLabel("—")
        read_i = QLabel("—")
        read_ilim = QLabel("—")

        for lbl in (read_v, read_i, read_ilim):
            lbl.setStyleSheet("font-weight: bold; font-size: 14px;")

        read_layout.addWidget(QLabel("Measured Voltage"), 0, 0)
        read_layout.addWidget(read_v, 0, 1)

        read_layout.addWidget(QLabel("Measured Current"), 1, 0)
        read_layout.addWidget(read_i, 1, 1)

        read_layout.addWidget(QLabel("Compliance"), 2, 0)
        read_layout.addWidget(read_ilim, 2, 1)

        self.readback_labels[(device.device_id, channel_id)] = (
            read_v,
            read_i,
            read_ilim,
        )

        outer.addWidget(QLabel("Live Readback"))
        outer.addWidget(read_frame)

        # Buttons
        # fmt: off
        # Button specification format:
        # (
        #   Internal attribute name:    # how the button is stored on the class (self.btn_start)
        #   Visible label:              # text shown on the button
        #   Color:                      # passed to StyledButton for theming
        #   Callback Function:          # function executed when the button is clicked
        #   Message:                    # message to be shown after operation is completed
        #   Threading:                  # indicates whether the task should be threaded or not
        # )
        button_specs = [
            ("btn_apply", "Apply Settings", "green", lambda: self._apply_settings(device.device_id, channel_id, vset, iset), f"[{device.name, channel_id}]: Settings applied", True),
            ("btn_on", "Output ON", "green",  lambda d=device.device_id, c=channel_id: self._set_output(d, c, 1), f"[{device.name, channel_id}]: Output enabled", True),
            ("btn_off", "Output OFF", "green",  lambda d=device.device_id, c=channel_id: self._set_output(d, c, 0), f"[{device.name, channel_id}]: Output disabled", True),
        ]
        # fmt: on

        self.button_manager.make(
            button_specs, target=self, layout=outer, thread_manager=self.thread_manager
        )

        return box

    def _apply_settings(self, device_id, channel_id, vset, iset):
        voltage = float(vset.text())
        current = float(iset.text())
        self.manager.apply_settings(device_id, channel_id, voltage, current)

    # reload after configuration change
    def reload_powering(self):
        for t in self.timers:
            t.stop()
            t.deleteLater()
        self.timers.clear()

        self.manager = PowerSupplyManager(self.TJ.user_config_file)
        self.manager.load()

        self.tabs.clear()
        for device in self.manager.devices.values():
            self.tabs.addTab(
                self.make_device_panel(device), f"{device.device_id} – {device.name}"
            )

    # Formatting
    def format_value(self, val, unit=""):
        if val is None:
            return "—"

        absval = abs(val)

        if unit == "A":
            if absval >= 1:
                return f"{val:.3f} A"
            elif absval >= 1e-3:
                return f"{val * 1e3:.3f} mA"
            elif absval >= 1e-6:
                return f"{val * 1e6:.3f} µA"
            else:
                return f"{val * 1e9:.3f} nA"

        if unit == "V":
            if absval >= 1:
                return f"{val:.3f} V"
            elif absval >= 1e-3:
                return f"{val * 1e3:.3f} mV"
            else:
                return f"{val * 1e6:.3f} µV"

        return f"{val:.6f} {unit}"

    def _set_output(self, device_id, channel_id, state):
        ch = self.manager.devices[device_id].channels[channel_id]
        if isinstance(ch, tuple):
            drv, idx = ch
            drv.set_enable(state, idx)
        else:
            (ch.on if state else ch.off)()

    def _poll_all_devices(self):
        data = {
            dev_id: {
                ch_id: self.manager.readback(dev_id, ch_id)
                for ch_id in dev.channels.keys()
            }
            for dev_id, dev in self.manager.devices.items()
        }

        self.append_text.emit("__UPDATE_READBACK__" + repr(data))

        time.sleep(0.5)
        self.thread_manager.run_in_thread(self._poll_all_devices)

    def _handle_append_text(self, text):
        if text.startswith("__UPDATE_READBACK__"):
            payload = text.replace("__UPDATE_READBACK__", "")
            data = ast.literal_eval(payload)
            self._update_all_readbacks(data)
        else:
            self.terminal.appendPlainText(text)

    def _update_all_readbacks(self, data):
        for dev_id, channels in data.items():
            for ch_id, rb in channels.items():
                lbl_v, lbl_i, lbl_ilim = self.readback_labels[(dev_id, ch_id)]
                lbl_v.setText(self.format_value(rb["voltage"], "V"))
                lbl_i.setText(self.format_value(rb["current"], "A"))
                lbl_ilim.setText(self.format_value(rb["current_limit"], "A"))
        if hasattr(self.TJ, "main_window") and self.TJ.main_window is not None:
            summary = []

            for (dev_id, ch_id), (
                lbl_v,
                lbl_i,
                lbl_ilim,
            ) in self.readback_labels.items():
                device = self.manager.devices[dev_id]

                rb = self.manager.readback(dev_id, ch_id)
                v = self.format_value(rb["voltage"], "V")
                i = self.format_value(rb["current"], "A")

                summary.append(f"{device.name} / {ch_id}\n  V={v}\n  I={i}\n")

            self.TJ.main_window.currentbar_readback.setText("\n".join(summary))


class MonitorView(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.TJ = controller
        self.button_manager = ButtonManager()
        self.thread_manager = ThreadManager(Messages(lambda text: None, lambda: False))

        layout = QVBoxLayout()
        self.setLayout(layout)

        # Reset button
        btn_reset = ButtonManager.StyledButton("Reset", color="green")
        btn_reset.clicked.connect(self.reset)
        layout.addWidget(btn_reset)

        # Masking checkbox
        self.cb_mask = QCheckBox("Mask noisy pixels")
        self.cb_mask.stateChanged.connect(self.masking)
        layout.addWidget(self.cb_mask)

        # Backend
        self.monitor = OnlineMonitor(self.TJ.user_config_file)
        chip_names = self.monitor.chip_sn

        # Tabs
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # -------------------------
        # PAGE 1: Hitmaps
        # -------------------------
        page_hits = QWidget()
        self.page_hits_layout = QVBoxLayout(page_hits)
        self.counter_row = QHBoxLayout()
        self.page_hits_layout.addLayout(self.counter_row)

        tabs.addTab(page_hits, "Hitmaps")

        # -------------------------
        # PAGE 2: Correlations
        # -------------------------
        page_corr = QWidget()
        self.page_corr_layout = QVBoxLayout(page_corr)

        # Detector selector
        selector_row = QHBoxLayout()
        self.detA = QComboBox()
        self.detB = QComboBox()
        selector_row.addWidget(QLabel("Detector A:"))
        selector_row.addWidget(self.detA)
        selector_row.addWidget(QLabel("Detector B:"))
        selector_row.addWidget(self.detB)

        # fmt: off
        button_specs = [
            ("btn_apply_corr", "Apply", "green", self.update_corr_key, "", True),
        ]
        # fmt: on
        self.button_manager.make(
            button_specs,
            target=self,
            layout=selector_row,
            thread_manager=self.thread_manager,
        )
        self.page_corr_layout.addLayout(selector_row)

        # Correlation plots
        corr_layout, corr_imgs = self.create_pg_grid(2, ["Col–Col", "Row–Row"])
        self.col_img, self.row_img = corr_imgs
        self.page_corr_layout.addLayout(corr_layout)

        self.corr_counter_row = QHBoxLayout()
        self.page_corr_layout.addLayout(self.corr_counter_row)

        tabs.addTab(page_corr, "Correlations")

        self.make_hitmaps(chip_names)
        self.make_correlators(chip_names)

        # Initialize correlation key
        self.current_corr_key = (0, 1) if len(chip_names) > 1 else (0, 0)
        self.update_corr_key()

        # Backend thread
        self.thread_manager.run_in_thread(self.monitor_loop)

        # GUI refresh timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_all)
        self.timer.start(500)

    def create_pg_grid(self, nplots, titles):
        pg.setConfigOption("background", "w")  # white background
        pg.setConfigOption("foreground", "k")  # black axes, ticks, labels

        ncols = math.ceil(math.sqrt(nplots))

        layout = QGridLayout()
        images = []

        for i in range(nplots):
            view = pg.GraphicsLayoutWidget()
            plot = view.addPlot()

            plot.setXRange(0, 512)
            plot.setYRange(0, 512)

            img = pg.ImageItem()
            plot.addItem(img)

            cmap = pg.colormap.get("viridis")
            img.setLookupTable(cmap.getLookupTable())

            plot.setTitle(titles[i])

            layout.addWidget(view, i // ncols, i % ncols)
            images.append(img)

        return layout, images

    def make_hitmaps(self, chip_names):
        num = len(chip_names)

        # Remove old grid if present
        if hasattr(self, "imgs"):
            old_item = self.page_hits_layout.takeAt(0)
            if old_item:
                while old_item.count():
                    child = old_item.takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

        # Create new grid
        grid_layout, self.imgs = self.create_pg_grid(num, chip_names)
        self.page_hits_layout.insertLayout(0, grid_layout)

        # Rebuild counters
        for lbl in getattr(self, "hit_labels", []):
            lbl.deleteLater()

        self.hit_labels = []
        for name in chip_names:
            lbl = QLabel(f"{name}: 0 hits")
            lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
            self.hit_labels.append(lbl)
            self.counter_row.addWidget(lbl)

    def make_correlators(self, chip_names):
        self.detA.blockSignals(True)
        self.detB.blockSignals(True)

        self.detA.clear()
        self.detB.clear()

        for i, name in enumerate(chip_names):
            self.detA.addItem(f"{i} – {name}", i)
            self.detB.addItem(f"{i} – {name}", i)

        self.detA.blockSignals(False)
        self.detB.blockSignals(False)

        self.update_corr_key()

        # Rebuild counters
        for self.corr_lbl in getattr(self, "corr_hit_labels", []):
            self.corr_lbl.deleteLater()

        self.corr_hit_labels = []
        self.corr_lbl = QLabel("0 correlated hits")
        self.corr_lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.corr_hit_labels.append(self.corr_lbl)
        self.corr_counter_row.addWidget(self.corr_lbl)

    def update_corr_key(self):
        a = self.detA.currentData()
        b = self.detB.currentData()
        if a is None or b is None or a == b:
            return

        new_key = (min(a, b), max(a, b))

        if new_key != self.current_corr_key:
            self.current_corr_key = new_key
            self.monitor.active_corr_key = new_key

            h = self.monitor.hit_corr[new_key]
            h["col_col"].fill(0)
            h["row_row"].fill(0)

            self.monitor.total_correlations[new_key] = 0

    def monitor_loop(self):
        while self.monitor._running:
            for i in range(self.monitor.num_chips):
                self.monitor.process_receiver(i)
            time.sleep(0.01)

    def update_all(self):
        # Hitmaps + counters
        for i, (img, occ, lbl, name) in enumerate(
            zip(
                self.imgs,
                self.monitor.total_occupancy,
                self.hit_labels,
                self.monitor.chip_sn,
            )
        ):
            if occ is not None:
                mask = self.monitor.mask[i]
                if mask is not None:
                    display_occ = occ.copy()
                    display_occ[mask] = 0
                else:
                    display_occ = occ

                display_rot = np.fliplr(np.rot90(display_occ, k=1).T)

                img.setImage(display_rot, autoLevels=False)
                img.setLevels([0, max(1, display_occ.max())])

                # Update hit counter
                hits = self.monitor.total_hits[i]
                lbl.setText(f"{name}: {hits} hits")

        # Correlations
        key = self.current_corr_key
        if key in self.monitor.hit_corr:
            col_corr = self.monitor.hit_corr[key]["col_col"]
            row_corr = self.monitor.hit_corr[key]["row_row"]

            self.col_img.setImage(col_corr, autoLevels=False)
            self.col_img.setLevels([0, 20])

            self.row_img.setImage(row_corr, autoLevels=False)
            self.row_img.setLevels([0, 20])

            # Update hit counter
            corr_hits = self.monitor.total_correlations[self.current_corr_key]
            self.corr_lbl.setText(f"{corr_hits} correlated hits")

    def reset(self):
        self.monitor.reset_occupancy()

        zero = np.zeros((512, 512))
        for img in self.imgs:
            img.setImage(zero)

        self.col_img.setImage(zero)
        self.row_img.setImage(zero)

        for lbl, name in zip(self.hit_labels, self.monitor.chip_sn):
            lbl.setText(f"{name}: 0 hits")
        self.monitor.total_correlations[self.current_corr_key] = 0

    def masking(self):
        if self.cb_mask.isChecked():
            # Recompute mask for all chips
            for i in range(self.monitor.num_chips):
                self.monitor.mask[i] = self.monitor.masking(i)
        else:
            # Disable masking
            self.monitor.mask = [None] * self.monitor.num_chips

    # reload after configuration change
    def reload_monitor(self):
        if hasattr(self, "monitor") and self.monitor is not None:
            self.monitor.stop_receivers()
            self.monitor._running = False
            time.sleep(0.05)

        self.monitor = OnlineMonitor(self.TJ.user_config_file)
        self.monitor.start_receivers()

        chip_names = self.monitor.chip_sn

        self.make_hitmaps(chip_names)
        self.make_correlators(chip_names)

        self.thread_manager.run_in_thread(self.monitor_loop)


class Configuration(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.TJ = controller
        layout = QVBoxLayout()
        self.button_manager = ButtonManager()

        # fmt: off
        # Button specification format:
        # (
        #   Internal attribute name:    # how the button is stored on the class (self.btn_start)
        #   Visible label:              # text shown on the button
        #   Color:                      # passed to StyledButton for theming
        #   Callback Function:          # function executed when the button is clicked
        #   Message:                    # message to be shown after operation is completed
        #   Threading:                  # indicates whether the task should be threaded or not
        # )
        button_specs = [
            ("btn_load", "Load Configuration", "green", self.load_file, None, False),
            ("btn_save", "Save Configuration", "green", self.save_file, None, False),
            ("btn_revert", "Revert Changes", "green", self.revert, None, False),
        ]
        # fmt: on

        self.button_manager.make(button_specs, target=self, layout=layout)

        # Text editor
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Load a TOML file to begin editing...")
        layout.addWidget(self.editor)

        self.setLayout(layout)

        self.current_path = None
        self.original_text = None

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select configuration file", "", "TOML Files (*.toml)"
        )

        if not path:
            return
        try:
            with open(path, "r") as f:
                text = f.read()

            self.editor.setPlainText(text)
            self.current_path = path
            self.original_text = text

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load file:\n{e}")

    def save_file(self):
        if not self.current_path:
            QMessageBox.warning(self, "No file", "Load a TOML file first.")
            return

        text = self.editor.toPlainText()

        try:
            toml.loads(text)
        except Exception as e:
            QMessageBox.critical(self, "Invalid TOML", f"Error in configuration:\n{e}")
            return

        try:
            with open(self.current_path, "w") as f:
                f.write(text)
            self.original_text = text
            QMessageBox.information(
                self,
                "Saved",
                "Configuration saved successfully. \nPlease Configure again to apply new Configuration.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file:\n{e}")

    def revert(self):
        if self.original_text is None:
            QMessageBox.warning(self, "Nothing to revert", "Load a TOML file first.")
            return
        self.editor.setPlainText(self.original_text)


class MainWindow(QWidget):
    def __init__(self, controller, power_manager):
        super().__init__()
        self.TJ = controller
        controller.main_window = self
        self.power_manager = power_manager
        self.button_manager = ButtonManager()

        self.page_configuration = Configuration(self.TJ)
        self.page_powering = Powering(self.TJ)
        self.page_monitor = MonitorView(self.TJ)
        self.page_scancontrol = ScanControl(
            self.TJ, monitor_view=self.page_monitor, powering_view=self.page_powering
        )

        # fmt: off
        # Page specification format:
        # (
        #   Internal name:          # internal attribute name for the sidebar button
        #   Sidebar label:          # text shown on the sidebar button
        #   Color:                  # color passed to StyledButton for theming
        #   Navigation Callback:    # function executed when the button is clicked
        #   Message:                # None, needed to use button manager logic
        #   Threading:              # False, same again
        #   Widget Instance:        # QWidget displayed in the QStackedWidget
        # )
        pages = [
            ("Powering", "Powering", "green", lambda: self.stack.setCurrentIndex(0), None, False, self.page_powering),
            ("Configuration", "Configuration", "green", lambda: self.stack.setCurrentIndex(1), None, False, self.page_configuration),
            ("ScanControl", "Scan Control", "green", lambda: self.stack.setCurrentIndex(2), None, False, self.page_scancontrol),
            ("MonitorView", "Online Monitor", "green", lambda: self.stack.setCurrentIndex(3), None, False, self.page_monitor),
        ]
        # fmt: on

        self.stack = QStackedWidget()
        self.sidebar_layout = QVBoxLayout()

        # Sidebar buttons
        for *_, widget in pages:
            self.stack.addWidget(widget)

        # Slicing out the widget
        self.button_manager.make(
            [page[0:-1] for page in pages], target=self, layout=self.sidebar_layout
        )

        self.sidebar_widget = QWidget()
        self.sidebar_widget.setLayout(self.sidebar_layout)
        self.sidebar_widget.setFixedWidth(150)

        self.currentbar_readback = QLabel()
        self.currentbar_readback.setFixedWidth(150)

        self.sidebar_layout.addSpacing(20)
        self.sidebar_layout.addWidget(self.currentbar_readback)
        self.sidebar_layout.addStretch()

        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)

        layout = QHBoxLayout()
        layout.addWidget(self.sidebar_widget)
        layout.addWidget(line)
        layout.addWidget(self.stack)

        self.setLayout(layout)
        self.setWindowTitle("MANTIS Control")


def main():
    app = QApplication(sys.argv)

    TJ = TJ_Control()
    cfg = TJ.user_config_file

    if cfg is not None:
        cfg = os.path.abspath(cfg)
        TJ.user_config_file = cfg
        TJ.load_config()

        if not os.path.isfile(cfg):
            print(f"[Startup] WARNING: Config file not found: {cfg}")
            print("[Startup] Using fallback: powering disabled.")
            TJ.user_config_file = None
    else:
        print("[Startup] No config file set at all.")
        TJ.user_config_file = None

    power_manager = PowerSupplyManager(TJ.user_config_file)
    power_manager.load()

    gui = MainWindow(TJ, power_manager)

    sys.stdout = gui.page_scancontrol
    sys.stderr = gui.page_scancontrol

    gui.show()
    sys.exit(app.exec())
