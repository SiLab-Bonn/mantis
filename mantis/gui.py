# Graphical user interface

# pyQT6 similar to online monitor
# buttons to click (start, configure, stop, restart, power cycle) and live plots to admire (hitmap, correlation...)
# data is should be handled separately to gui in some kind of interpreter

import numpy as np
import math
import sys
import toml
import time
from PyQt6.QtCore import QTimer, QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QCheckBox,
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
    QGridLayout,
    QPushButton,
    QPlainTextEdit,
    QLabel,
    QProgressBar,
    QFileDialog,
    QMessageBox,
    QStackedWidget,
    QFrame,
)
from mantis.tj_interface import TJ_Control
from mantis.online_monitor import OnlineMonitor
import pyqtgraph as pg


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
            "grey": "rgba(159, 161, 164, 0.5)",
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
        self.set_color("grey")
        QApplication.processEvents()

    def set_ready(self):
        self.set_color(self.default_color)
        QApplication.processEvents()


# Run functions in background - threading
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


class ThreadHelper:
    def run_in_thread(self, fn, button=None):
        thread = QThread()
        worker = Worker(fn)

        if not hasattr(self, "threads"):
            self.threads = []
        self.threads.append(thread)
        self.threads.append(worker)

        worker.moveToThread(thread)

        thread.started.connect(worker.run)

        if button is not None:
            worker.error.connect(lambda e: button.set_ready())
            worker.finished.connect(lambda: button.set_ready())

        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self.threads.remove(thread))

        thread.start()


class ScanControl(QWidget, ThreadHelper):
    def __init__(self, controller):
        super().__init__()
        self.TJ = controller

        layout = QVBoxLayout()

        # fmt: off
        # Button specification format:
        # (
        #   Internal attribute name:    # how the button is stored on the class (self.btn_start)
        #   Visible label:              # text shown on the button
        #   Color name:                 # passed to StyledButton for theming
        #   Callback Function:          # function executed when the button is clicked, including threading if necessary
        #   Message:                    # Message to be shown after operation is completed
        # )
        button_specs = [
            ("btn_initialize","Initialize","green",lambda: self.run_in_thread(self.TJ.initialize, self.btn_initialize), "Initialization complete"),
            ("btn_conf","Configure","green",lambda: self.configure_clicked(), "Configuration complete"), # threading separately, because config loading, which cannot be threaded
            ("btn_start","Start Scan","green",lambda: self.run_in_thread(self.TJ.start_scan, self.btn_start), "Scan complete"),
            ("btn_stop", "Stop Scan", "green", lambda: (self.TJ.stop_scan(), self.log("Scan stopped")), ""), # message printed separately, because no threading
        ]
        # fmt: on

        self.buttons = {}

        for attr_name, label, color, callback, message in button_specs:
            btn = StyledButton(label, color=color)
            btn.message = message
            self.buttons[attr_name] = btn
            setattr(self, attr_name, btn)
            btn.clicked.connect(callback)
            layout.addWidget(btn)

        # Terminal
        self.terminal = QPlainTextEdit()
        self.terminal.setReadOnly(True)
        layout.addWidget(self.terminal)

        # Progress bar
        self.status_label = QLabel("Progress Bar")
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        layout.addWidget(self.progress)

        self.setLayout(layout)

        self._stdout = sys.stdout
        sys.stdout = self

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_gui)
        self.timer.start(200)

    def update_gui(self):
        if self.TJ.scan_ext and hasattr(self.TJ.scan_ext, "pbar"):
            try:
                total = self.TJ.scan_ext.pbar.total
                current = self.TJ.scan_ext.pbar.n
                self.progress.setMaximum(total)
                self.progress.setValue(current)
            except Exception:
                pass

        if self.TJ.scan_ext and self.TJ.scan_ext.stop_scan.is_set():
            self.status_label.setText("")
        elif self.TJ.scan_ext and hasattr(self.TJ.scan_ext, "pbar"):
            self.status_label.setText("Scan running")
        else:
            self.status_label.setText("")

    def configure_clicked(self):
        self.TJ.load_config()

        self.run_in_thread(self.TJ.configure, self.btn_conf)

    def handle_error(self, e, button):
        self.log(f"ERROR: {e}")
        button.set_ready()

    def log(self, text):
        self.terminal.appendPlainText(text)

    def write(self, text):
        if text.strip():
            self.log(text)

    def flush(self):
        pass


# class Powering(QWidget):
#     def __init__(self):
#         super().__init__()
#         layout = QVBoxLayout()
#         self.setLayout(layout)
class MonitorView(QWidget, ThreadHelper):
    def __init__(self, controller):
        super().__init__()
        self.TJ = controller

        layout = QVBoxLayout()
        self.setLayout(layout)

        # Reset button
        btn_reset = StyledButton("Reset", color="green")
        btn_reset.clicked.connect(self.reset)
        layout.addWidget(btn_reset)

        # # Masking button
        self.cb_mask = QCheckBox("Mask noisy pixels")
        self.cb_mask.stateChanged.connect(self.masking)
        layout.addWidget(self.cb_mask)

        # Backend
        self.monitor = OnlineMonitor(self.TJ.user_config_file)
        num = self.monitor.num_chips
        chip_names = self.monitor.chip_sn

        # Hitmap
        grid_layout, self.imgs = self.create_pg_grid(num, chip_names)
        layout.addLayout(grid_layout)

        # Counter
        self.hit_labels = []
        counter_row = QHBoxLayout()
        for name in chip_names:
            lbl = QLabel(f"{name}: 0 hits")
            lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
            self.hit_labels.append(lbl)
            counter_row.addWidget(lbl)
        layout.addLayout(counter_row)

        selector_row = QHBoxLayout()
        self.detA = QComboBox()
        self.detB = QComboBox()

        for i, name in enumerate(chip_names):
            self.detA.addItem(f"{i} – {name}", i)
            self.detB.addItem(f"{i} – {name}", i)

        self.detA.setCurrentIndex(0)
        self.detB.setCurrentIndex(1 if num > 1 else 0)

        self.detA.currentIndexChanged.connect(self.update_corr_key)
        self.detB.currentIndexChanged.connect(self.update_corr_key)

        selector_row.addWidget(QLabel("Detector A:"))
        selector_row.addWidget(self.detA)
        selector_row.addWidget(QLabel("Detector B:"))
        selector_row.addWidget(self.detB)
        layout.addLayout(selector_row)

        # Correlation
        corr_layout, corr_imgs = self.create_pg_grid(2, ["Col–Col", "Row–Row"])
        self.col_img, self.row_img = corr_imgs
        layout.addLayout(corr_layout)

        self.current_corr_key = (0, 1) if num > 1 else (0, 0)
        self.update_corr_key()

        # Backend thread
        self.run_in_thread(self.monitor_loop)

        # GUI refresh timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_all)
        self.timer.start(200)

    def create_pg_grid(self, nplots, titles):
        pg.setConfigOption("background", "w")  # white background
        pg.setConfigOption("foreground", "k")  # black axes, ticks, labels

        ncols = math.ceil(math.sqrt(nplots))
        # nrows = math.ceil(nplots / ncols)

        layout = QGridLayout()
        images = []

        ticks = [0, 112, 224, 336, 448, 512]

        for i in range(nplots):
            view = pg.GraphicsLayoutWidget()
            plot = view.addPlot()

            plot.getAxis("bottom").setTicks([[(t, str(t)) for t in ticks]])
            plot.getAxis("left").setTicks([[(t, str(t)) for t in ticks]])

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

    def update_corr_key(self):
        a = self.detA.currentData()
        b = self.detB.currentData()
        if a is None or b is None or a == b:
            return

        self.current_corr_key = (min(a, b), max(a, b))

    def monitor_loop(self):
        while True:
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
                occ_rot = np.rot90(occ, k=1).T
                img.setImage(occ_rot, autoLevels=False)
                img.setLevels([0, max(1, occ.max())])

                hits = self.monitor.total_hits[i]  # int(occ.sum())

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

    def reset(self):
        self.monitor.reset_occupancy()

        zero = np.zeros((512, 512))
        for img in self.imgs:
            img.setImage(zero)

        self.col_img.setImage(zero)
        self.row_img.setImage(zero)

        for lbl, name in zip(self.hit_labels, self.monitor.chip_sn):
            lbl.setText(f"{name}: 0 hits")

    def masking(self):
        if self.cb_mask.isChecked():
            # Recompute mask for all chips
            for i in range(self.monitor.num_chips):
                self.monitor.mask[i] = self.monitor.masking(i)
        else:
            # Disable masking
            self.monitor.mask = [None] * self.monitor.num_chips


class Configuration(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.TJ = controller
        layout = QVBoxLayout()

        # fmt: off
        # Button specification format:
        # (
        #   Internal attribute name:    # how the button is stored on the class (self.btn_start)
        #   Visible label:              # text shown on the button
        #   Color name:                 # passed to StyledButton for theming
        #   Callback Function:          # function executed when the button is clicked
        # )
        button_specs = [
            ("btn_load", "Load Configuration", "green", self.load_file),
            ("btn_save", "Save Configuration", "green", self.save_file),
            ("btn_revert", "Revert Changes", "green", self.revert),
        ]
        # fmt: on

        self.buttons = {}

        for attr_name, label, color, callback in button_specs:
            btn = StyledButton(label, color=color)
            self.buttons[attr_name] = btn
            setattr(self, attr_name, btn)
            btn.clicked.connect(callback)
            layout.addWidget(btn)

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
            self.TJ.user_config_file = path

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
    def __init__(self, controller):
        super().__init__()
        self.TJ = controller

        # fmt: off
        # Page specification format:
        # (
        #   Internal name:      # key used to store the page's button (optional)
        #   Widget Instance:    # the actual QWidget that will be shown in the stack
        #   Sidebar label:      # text shown on the sidebar button
        #   ButtonColor:        # color passed to StyledButton for theming
        # )
        pages = [
            # ("Powering", Powering(), "Powering", "green"),
            ("Configuration", Configuration(self.TJ), "Configuration", "green"),
            ("ScanControl", ScanControl(self.TJ), "Scan Control", "green"),
            ("MonitorView", MonitorView(self.TJ), "Online Monitor", "green"),
        ]
        #  fmt: on

        self.stack = QStackedWidget()

        self.sidebar_layout = QVBoxLayout()

        # Toggle button
        self.toggle_btn = StyledButton("⮜", color="lightblue")
        self.toggle_btn.setFixedHeight(30)
        self.toggle_btn.clicked.connect(self.toggle_sidebar)
        self.sidebar_layout.addWidget(self.toggle_btn)

        # sidebar buttons and pages
        self.sidebar_buttons = {}

        for index, (attr_name, widget, label, color) in enumerate(pages):
            self.stack.addWidget(widget)

            btn = StyledButton(label, color=color)
            self.sidebar_buttons[attr_name] = btn
            btn.clicked.connect(lambda _, i=index: self.stack.setCurrentIndex(i))

            self.sidebar_layout.addWidget(btn)

        self.sidebar_layout.addStretch()

        self.sidebar_widget = QWidget()
        self.sidebar_widget.setLayout(self.sidebar_layout)
        self.sidebar_widget.setFixedWidth(150)

        # Vertical separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)

        # Main layout
        layout = QHBoxLayout()
        layout.addWidget(self.sidebar_widget)
        layout.addWidget(line)
        layout.addWidget(self.stack)

        self.setLayout(layout)
        self.setWindowTitle("MANTIS Control")

        self.sidebar_collapsed = False
        self.sidebar_width = 150

    def toggle_sidebar(self):
        if self.sidebar_collapsed:
            self.sidebar_widget.setFixedWidth(self.sidebar_width)
            self.toggle_btn.setText("⮜")

            for btn in self.sidebar_buttons.values():
                btn.show()

            self.sidebar_collapsed = False

        else:
            self.sidebar_widget.setFixedWidth(40)
            self.toggle_btn.setText("⮞")

            for btn in self.sidebar_buttons.values():
                btn.hide()

            self.sidebar_collapsed = True


def main():
    app = QApplication(sys.argv)

    TJ = TJ_Control()

    gui = MainWindow(TJ)
    gui.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
