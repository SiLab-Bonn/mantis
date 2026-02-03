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
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
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
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from mpl_toolkits.axes_grid1 import make_axes_locatable
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas


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
        btn = StyledButton("Reset", color="green")
        btn.clicked.connect(self.reset)
        layout.addWidget(btn)

        # Custom viridis with grey zero
        vir = plt.cm.get_cmap("viridis", 256)
        vir_colors = vir(np.linspace(0, 1, 256))
        vir_colors[0] = [0.624, 0.631, 0.643, 1.0]
        self.viridis_custom = mcolors.ListedColormap(vir_colors)

        # Backend
        self.monitor = OnlineMonitor(self.TJ.user_config_file)
        num = self.monitor.num_chips
        chip_names = self.monitor.chip_sn

        # Hitmap grid
        self.fig, self.axes, self.imgs = self.create_grid(
            nplots=num, title_prefix="Hitmap", chip_names=chip_names, transpose=True
        )
        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

        # Detector selection dropdowns
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

        # Correlation grid
        self.corr_fig, self.corr_axes, corr_imgs = self.create_grid(
            nplots=2, title_prefix="Correlation"
        )
        self.col_img, self.row_img = corr_imgs

        self.corr_canvas = FigureCanvas(self.corr_fig)
        layout.addWidget(self.corr_canvas)

        # Initialize correlation key
        self.current_corr_key = (0, 1) if num > 1 else (0, 0)
        self.update_corr_key()

        # Start backend thread
        self.run_in_thread(self.monitor_loop)

        # GUI refresh timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_all)
        self.timer.start(500)

    def update_corr_key(self):
        a = self.detA.currentData()
        b = self.detB.currentData()

        if a is None or b is None:
            return
        if a == b:
            return

        self.current_corr_key = (min(a, b), max(a, b))

        k = self.current_corr_key
        self.corr_axes[0].set_title(f"Col–Col {k[0]} ↔ {k[1]}")
        self.corr_axes[1].set_title(f"Row–Row {k[0]} ↔ {k[1]}")
        self.corr_canvas.draw_idle()

    def monitor_loop(self):
        while True:
            for i in range(self.monitor.num_chips):
                self.monitor.process_receiver(i)
            time.sleep(0.001)

    def update_all(self):
        # Hitmaps
        for i in range(self.monitor.num_chips):
            occ = self.monitor.total_occupancy[i]
            if occ is not None:
                self.imgs[i].set_data(occ.T)
                self.imgs[i].set_clim(0, max(1, occ.max()))

        # Correlations
        key = self.current_corr_key
        if key in self.monitor.hit_corr:
            col_corr = self.monitor.hit_corr[key]["col_col"]
            row_corr = self.monitor.hit_corr[key]["row_row"]

            self.col_img.set_data(col_corr)
            self.col_img.set_clim(0, max(1, 20))  # col_corr.max()))
            # -> quick fix, needs to be worked on
            self.row_img.set_data(row_corr)
            self.row_img.set_clim(0, max(1, 20))  # row_corr.max()))

        self.canvas.draw_idle()
        self.corr_canvas.draw_idle()

    def reset(self):
        self.monitor.reset_occupancy()

        for img in self.imgs:
            img.set_data(np.zeros((512, 512)).T)
            img.set_clim(0, 1)

        self.col_img.set_data(np.zeros((512, 512)))
        self.col_img.set_clim(0, 1)

        self.row_img.set_data(np.zeros((512, 512)))
        self.row_img.set_clim(0, 1)

        self.canvas.draw_idle()
        self.corr_canvas.draw_idle()

    def create_grid(self, nplots, title_prefix, chip_names=None, transpose=False):
        ncols = math.ceil(math.sqrt(nplots))
        nrows = math.ceil(nplots / ncols)

        fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 6 * nrows))
        axes = np.array(axes).reshape(-1)

        imgs = []
        for i, ax in enumerate(axes[:nplots]):
            data = np.zeros((512, 512))
            if transpose:
                data = data.T

            img = ax.imshow(
                data,
                cmap=self.viridis_custom,
                origin="lower",
                interpolation="nearest",
                extent=[1, 512, 1, 512],
                aspect="equal",
            )

            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="5%", pad=0.1)
            fig.colorbar(img, cax=cax)

            ax.set_xticks([1, 112, 224, 336, 448, 512])
            ax.set_yticks([1, 112, 224, 336, 448, 512])

            if chip_names:
                ax.set_title(f"{title_prefix} – {chip_names[i]}")
            else:
                ax.set_title(f"{title_prefix} {i}")

            imgs.append(img)

        for ax in axes[nplots:]:
            ax.set_visible(False)

        return fig, axes, imgs


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
            # ("Tuning", Tuning(self.TJ), "Tuning", "green"),
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
