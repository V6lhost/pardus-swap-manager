import os
import sys
from pathlib import Path
import psutil
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QTableWidgetItem
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QTimer, Qt, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPainterPath

from custom_widgets import CircularStatusWidget
from helper_functions import *

# Custom ui loader class and function to make the code cleaner
class UiLoader(QUiLoader):
    def __init__(self, baseinstance):
        super().__init__()
        self.baseinstance = baseinstance

    def createWidget(self, class_name, parent=None, name=""):
        if parent is None and self.baseinstance:
            return self.baseinstance
        return super().createWidget(class_name, parent, name)

def load_ui(ui_path, baseinstance):
    loader = UiLoader(baseinstance)
    ui_file = QFile(ui_path)
    if not ui_file.open(QFile.ReadOnly):
        print(f"Error while loading ui file: {ui_path}")
        return None
    widget = loader.load(ui_file)
    ui_file.close()
    return widget

class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()

        current_dir = Path(__file__).resolve().parent
        ui_path = current_dir.parent / "ui" / "MainWindow.ui"

        load_ui(ui_path, self)
        self.setWindowTitle("Pardus SWAP Manager")

        # Force fixed size
        self.setMinimumSize(400, 600)
        self.setMaximumSize(400, 600)

        # Import custom widgets
        self.ram_graph = CircularStatusWidget()

        layout = QVBoxLayout(self.boxRamStatus)
        layout.addWidget(self.ram_graph)

        self.swap_graph = CircularStatusWidget()

        layout = QVBoxLayout(self.boxSwapStatus)
        layout.addWidget(self.swap_graph)

        # Set up the swap table
        self.tableSwap.setColumnCount(5)
        self.tableSwap.setHorizontalHeaderLabels(["Path", "Type", "Size", "Priority", "Actions"])
        
        header = self.tableSwap.horizontalHeader()
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        header.setSectionResizeMode(1, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, header.ResizeMode.ResizeToContents)

        # Disable editing
        self.tableSwap.setEditTriggers(self.tableSwap.EditTrigger.NoEditTriggers)
        
        # Call update functions manually for first time
        self.update_information_periodically()
        self.update_information_once()

        # Timer for autoupdate
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_information_periodically)
        self.timer.start(500)



    def update_information_periodically(self):
        # Update RAM status
        ram_status = get_memory_status()       
        self.ram_graph.set_values(ram_status['percentage'], ram_status['used'], ram_status['total'])

        # Update SWAP status
        swap_status = get_memory_status("swap")
        self.swap_graph.set_values(swap_status['percentage'], swap_status['used'], swap_status['total'])

    def update_information_once(self):

        # Update SWAP table
        swaps = get_swap_information()
        
        self.tableSwap.setRowCount(0) # Clean the table

        for index, swap in enumerate(swaps):
            self.tableSwap.insertRow(index)

            self.tableSwap.setItem(index, 0, QTableWidgetItem(swap["path"]))
            self.tableSwap.setItem(index, 1, QTableWidgetItem(swap["swap_type"]))
            self.tableSwap.setItem(index, 2, QTableWidgetItem(f"{swap['size']} GiB"))
            self.tableSwap.setItem(index, 3, QTableWidgetItem(swap["priority"]))
            self.tableSwap.setItem(index, 4, QTableWidgetItem("Placeholder"))
        
        # Update SWAP suggestion
        swap_suggestion = check_swap_requirement()
        self.labelSwapSuggested.setText(f"{swap_suggestion} suggested")

        # Update suggested compression algorithm based on AVX support status of CPU
        avx_support = check_cpu_avx_support()

        if avx_support:
            self.labelSuggestedAlgorithm.setText("ZSTD")
        else:
            self.labelSuggestedAlgorithm.setText("LZ4")
        
        # Update disk type
        disk = get_disk_type()
        self.labelDiskType.setText(disk)






if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())