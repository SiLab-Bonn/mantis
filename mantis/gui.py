# Graphical user interface

# pyQT6 similar to online monitor
# buttons to click (start, configure, stop, restart, power cycle) and live plots to admire (hitmap, correlation...)
# data is should be handled separately to gui in some kind of interpreter


import sys
import toml
from PyQt6.QtCore import QTimer, QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QPlainTextEdit,
    QLabel,
    QProgressBar,
    QFileDialog,
    QMessageBox,
    QStackedWidget,
    QFrame,
)
from tj_interface import TJ_Control


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


class ScanControl(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.TJ = controller

        layout = QVBoxLayout()

        # fmt: off
        # Button specification format:
        # (
        #     "Internal attribute name",   # how the button is stored on the class (self.btn_start)
        #     "Visible label",             # text shown on the button
        #     "Color name",                # passed to StyledButton for theming
        #     CallbackFunction             # function executed when the button is clicked, including threading if necessary
        #     Message                      # Message to be shown after operation is completed
        # )
        button_specs = [
            ("btn_initialize","Initialize","green",lambda: self.run_in_thread(self.TJ.initialize, self.btn_initialize), "Initialization complete"),
            ("btn_conf","Configure","green",lambda: self.configure_clicked(), "Configuration complete"), # threading separately, because config loading, which cannot be threaded
            ("btn_start","Start Scan","green",lambda: self.run_in_thread(self.TJ.start_scan, self.btn_start), "Scan complete"),
            ("btn_stop", "Stop Scan", "green", lambda: (self.TJ.stop_scan(), self.terminal.appendPlainText("Scan stopped")), ""), # message printed separately, because no threading
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

    def run_in_thread(self, fn, button):
        button.set_busy()

        thread = QThread()
        worker = Worker(fn)

        if not hasattr(self, "threads"):
            self.threads = []
        self.threads.append(thread)
        self.threads.append(worker)

        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.error.connect(lambda e: self.handle_error(e, button))
        worker.finished.connect(lambda: button.set_ready())
        worker.finished.connect(lambda: self.terminal.appendPlainText(button.message))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self.threads.remove(thread))
        thread.start()

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
            self.status_label.setText("Scan stopped")
        elif self.TJ.scan_ext and hasattr(self.TJ.scan_ext, "pbar"):
            self.status_label.setText("Scan running")
        else:
            self.status_label.setText("")

    def configure_clicked(self):
        self.TJ.load_config()

        self.run_in_thread(self.TJ.configure, self.btn_conf)

    def handle_error(self, e, button):
        self.terminal.appendPlainText(f"ERROR: {e}")
        button.set_ready()

    def log(self, text):
        self.terminal.appendPlainText(text)

    def write(self, text):
        if text.strip():
            self.log(text)

    def flush(self):
        pass


class OnlineMonitor(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Online Monitor"))
        self.setLayout(layout)


class Configuration(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.TJ = controller
        layout = QVBoxLayout()

        # fmt: off
        # Button specification format:
        # (
        #     "Internal attribute name",   # how the button is stored on the class (self.btn_load)
        #     "Visible label",             # text shown on the button
        #     "Color name",                # passed to StyledButton for theming
        #     CallbackFunction             # function executed when the button is clicked
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
        #     "Internal name",     # key used to store the page's button (optional)
        #     WidgetInstance,      # the actual QWidget that will be shown in the stack
        #     "Sidebar label",     # text shown on the sidebar button
        #     "ButtonColor"        # color passed to StyledButton for theming
        # )
        pages = [
            ("Configuration", Configuration(self.TJ), "Configuration", "green"),
            ("ScanControl", ScanControl(self.TJ), "Scan Control", "green"),
            ("OnlineMonitor", OnlineMonitor(), "Online Monitor", "green"),
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


if __name__ == "__main__":
    app = QApplication(sys.argv)

    TJ = TJ_Control()

    gui = MainWindow(TJ)
    gui.show()

    sys.exit(app.exec())
