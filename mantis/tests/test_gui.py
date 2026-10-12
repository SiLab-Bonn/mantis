import sys
from PyQt6.QtWidgets import QApplication
from mantis.gui import MainWindow
from mantis.tests.utils import Scan_Mock
from mantis.interface.tj_interface import TJ_Control


def main():
    app = QApplication(sys.argv)

    TJ = TJ_Control(scan_type=Scan_Mock)
    PowerMock = None

    gui = MainWindow(TJ, PowerMock)
    gui.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
