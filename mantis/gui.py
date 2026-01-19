# Graphical user interface

# pyQT6 similar to online monitor
# buttons to click (start, configure, stop, restart, power cycle) and live plots to admire (hitmap, correlation...)
# data is should be handled separately to gui in some kind of interpreter

import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from tj_interface import TJ_Control


class ScanGUI(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.TJ = controller

        self.setWindowTitle("TJ Scan Control")

        layout = QVBoxLayout()

        # Buttons
        self.initialize_btn = QPushButton("Initialize")
        self.conf_btn = QPushButton("Configure")
        self.start_btn = QPushButton("Start Scan")
        self.stop_btn = QPushButton("Stop Scan")
        self.reconf_btn = QPushButton("Reconfigure")

        layout.addWidget(self.initialize_btn)
        layout.addWidget(self.conf_btn)
        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.reconf_btn)

        # Status label
        self.status_label = QLabel("Progress Bar")
        layout.addWidget(self.status_label)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        layout.addWidget(self.progress)

        self.setLayout(layout)

        # Connect buttons
        self.initialize_btn.clicked.connect(self.initialize)
        self.conf_btn.clicked.connect(self.configure)
        self.start_btn.clicked.connect(self.start_scan)
        self.stop_btn.clicked.connect(self.stop_scan)
        self.reconf_btn.clicked.connect(self.reconfigure)

        # Timer to update GUI
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_gui)
        self.timer.start(200)

    # Def actions for buttons
    def initialize(self):
        self.TJ.initialize()
        print("Initialization complete")

    def configure(self):
        self.TJ.configure()
        print("Configuration complete")

    def start_scan(self):
        self.TJ.start_scan()

    def stop_scan(self):
        self.TJ.stop_scan()

    def reconfigure(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select new config file", "", "TOML Files (*.toml)"
        )
        if filename:
            self.TJ.reconfigure(filename)
        print("Reconfiguration complete")

    # GUI update loop
    def update_gui(self):
        # Update status
        if self.TJ.thread and self.TJ.thread.is_alive():
            self.status_label.setText("Scan running")
        else:
            self.status_label.setText("Idle")

        # Update progress bar
        if self.TJ.scan_ext and hasattr(self.TJ.scan_ext, "pbar"):
            try:
                total = self.TJ.scan_ext.pbar.total
                current = self.TJ.scan_ext.pbar.n
                self.progress.setMaximum(total)
                self.progress.setValue(current)
            except Exception:
                pass


if __name__ == "__main__":
    app = QApplication(sys.argv)

    TJ = TJ_Control()

    gui = ScanGUI(TJ)
    gui.show()

    sys.exit(app.exec())
