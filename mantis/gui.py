# Graphical user interface

# pyQT6 similar to online monitor
# buttons to click (start, configure, stop, restart, power cycle) and live plots to admire (hitmap, correlation...)
# data is should be handled separately to gui in some kind of interpreter

import sys
import toml
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QWidget,
)
from tj_interface import TJ_Control


class ScanControl(QWidget):
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

        layout.addWidget(self.initialize_btn)
        layout.addWidget(self.conf_btn)
        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)

        # Terminal
        self.terminal = QPlainTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setMaximumBlockCount(5000)
        layout.addWidget(self.terminal)

        self.setLayout(layout)

        self._stdout = sys.stdout
        sys.stdout = self

        # Status label
        self.status_label = QLabel("Progress Bar")
        layout.addWidget(self.status_label)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        layout.addWidget(self.progress)

        # Connect buttons
        self.initialize_btn.clicked.connect(self.initialize)
        self.conf_btn.clicked.connect(self.configure)
        self.start_btn.clicked.connect(self.start_scan)
        self.stop_btn.clicked.connect(self.stop_scan)

        # Timer to update GUI
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_gui)
        self.timer.start(200)

    # Def actions for buttons
    def initialize(self):
        self.TJ.initialize()
        self.log("Initialization complete")

    def start_scan(self):
        self.TJ.start_scan()

    def stop_scan(self):
        self.TJ.stop_scan()

    def configure(self):
        # filename, _ = QFileDialog.getOpenFileName(
        #     self, "Select new config file", "", "TOML Files (*.toml)"
        # )
        # if filename:
        #     self.TJ.configure(filename)
        self.TJ.configure()
        self.log("Configuration complete")

    # GUI update loop
    def update_gui(self):
        # Update status
        if self.TJ.thread and self.TJ.thread.is_alive():
            self.status_label.setText("Scan running")
        else:
            self.status_label.setText("")

        # Update progress bar
        if self.TJ.scan_ext and hasattr(self.TJ.scan_ext, "pbar"):
            try:
                total = self.TJ.scan_ext.pbar.total
                current = self.TJ.scan_ext.pbar.n
                self.progress.setMaximum(total)
                self.progress.setValue(current)
            except Exception:
                pass

    def log(self, text):
        self.terminal.appendPlainText(text)

    def write(self, text):
        if text.strip():
            self.log(text)

    def flush(self):
        pass


class OnlineMonitor(QWidget):  # tbc
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Online Monitor"))
        self.setLayout(layout)


class Configuration(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()

        # Buttons
        self.btn_load = QPushButton("Load Configuration")
        self.btn_save = QPushButton("Save Configuration")
        self.btn_revert = QPushButton("Revert Changes")

        # Text editor
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Load a TOML file to begin editing...")

        layout.addWidget(self.btn_load)
        layout.addWidget(self.btn_save)
        layout.addWidget(self.btn_revert)
        layout.addWidget(self.editor)

        self.setLayout(layout)

        self.btn_load.clicked.connect(self.load_file)
        self.btn_save.clicked.connect(self.save_file)
        self.btn_revert.clicked.connect(self.revert)

        self.current_path = None
        self.original_text = None

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select TOML file", "", "TOML Files (*.toml)"
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
                "Configuration saved successfully. \n Please Configure again to apply new Configuration.",
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

        # Create pages
        self.page1 = ScanControl(controller)
        self.page2 = OnlineMonitor()
        self.page3 = Configuration()

        # Stacked widget
        self.stack = QStackedWidget()
        self.stack.addWidget(self.page1)
        self.stack.addWidget(self.page2)
        self.stack.addWidget(self.page3)

        # Sidebar buttons
        self.btn_SC = QPushButton("Scan Control")
        self.btn_OM = QPushButton("Online Monitor")
        self.btn_conf = QPushButton("Configuration")

        self.btn_SC.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        self.btn_OM.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        self.btn_conf.clicked.connect(lambda: self.stack.setCurrentIndex(2))

        # Collapsible toggle button
        self.toggle_btn = QPushButton("⮜")
        self.toggle_btn.setFixedHeight(30)
        self.toggle_btn.clicked.connect(self.toggle_sidebar)

        # Sidebar layout
        self.sidebar_layout = QVBoxLayout()
        self.sidebar_layout.addWidget(self.toggle_btn)
        self.sidebar_layout.addWidget(self.btn_SC)
        self.sidebar_layout.addWidget(self.btn_OM)
        self.sidebar_layout.addWidget(self.btn_conf)
        self.sidebar_layout.addStretch()

        self.sidebar_widget = QWidget()
        self.sidebar_widget.setLayout(self.sidebar_layout)

        self.sidebar_widget.setFixedWidth(150)

        # Vertical separator line
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

        # Track collapsed state
        self.sidebar_collapsed = False

    # Collapse / Expand Sidebar
    def toggle_sidebar(self):
        if self.sidebar_collapsed:
            # Expand
            self.sidebar_widget.setFixedWidth(self.sidebar_width)
            self.toggle_btn.setText("⮜")
            self.btn_SC.show()
            self.btn_OM.show()
            self.btn_conf.show()
            self.sidebar_collapsed = False
        else:
            # Collapse
            self.sidebar_widget.setFixedWidth(40)
            self.toggle_btn.setText("⮞")
            self.btn_SC.hide()
            self.btn_OM.hide()
            self.btn_conf.hide()
            self.sidebar_collapsed = True


if __name__ == "__main__":
    app = QApplication(sys.argv)

    TJ = TJ_Control()

    gui = MainWindow(TJ)
    gui.show()

    sys.exit(app.exec())
