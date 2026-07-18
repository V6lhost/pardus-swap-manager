import signal, sys
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QMainWindow,
    QTableWidgetItem,
    QVBoxLayout
)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import (
    QFile,
    QThread,
    QTimer,
    Qt,
    Signal,
)

from custom_widgets import * # CircularStatusWidget, SpinnerWidget, ProgressbarWidget
from helper_functions import * # get_memory_status, get_swap_information, check_cpu_avx_support, get_disk_type, check_swap_requirement, prepare_silesia_benchmark_data, benchmark_disk, benchmark_algorithm, clear_cache, check_and_disable_cow, score_by_threshold
from calibration import * # calculate_disk_score

# Custom ui loader class and function to make the code cleaner
class UiLoader(QUiLoader):
    def __init__(self, baseinstance):
        super().__init__()
        self.baseinstance = baseinstance

    def createWidget(self, class_name, parent=None, name=""):
        if parent is None and self.baseinstance:
            return self.baseinstance
        return super().createWidget(class_name, parent, name)

def load_ui(ui_path, baseinstance=None):
    loader = UiLoader(baseinstance)
    ui_file = QFile(ui_path)
    if not ui_file.open(QFile.ReadOnly):
        print(f"Error while loading ui file: {ui_path}")
        return None
    widget = loader.load(ui_file)
    ui_file.close()
    return widget

class BenchmarkThread(QThread):
    prepare_progress = Signal(int)
    benchmark_result = Signal(str, dict)
    process_status = Signal(str)

    def __init__(self, parent=None, disk_test_path="/srv"):
        super().__init__(parent)
        self.disk_test_path = disk_test_path
    
    def run(self):
        try:
            self.process_status.emit("prepare")
            prepare_silesia_benchmark_data(self.prepare_progress.emit)

            self.process_status.emit("disk")
            disk_benchmark_data = benchmark_disk(self.disk_test_path)
            self.benchmark_result.emit("disk", disk_benchmark_data)

            self.process_status.emit("lz4")
            lz4_benchmark_data = benchmark_algorithm("lz4")
            self.benchmark_result.emit("lz4", lz4_benchmark_data)

            self.process_status.emit("zstd")
            zstd_benchmark_data = benchmark_algorithm("zstd")
            self.benchmark_result.emit("zstd", zstd_benchmark_data)

            self.process_status.emit("done")
            
        except Exception as e:
            print(f"Error while running benchmark thread: {e}")
            self.process_status.emit("error")

class BenchmarkWindow(QDialog):
    def __init__(self, parent=None):
        super(BenchmarkWindow, self).__init__()
        current_dir = Path(__file__).resolve().parent
        ui_path = current_dir.parent / "ui" / "BenchmarkWindow.ui"

        load_ui(ui_path, self)

        # Force fixed size
        self.setFixedSize(400, 600)

        self.setWindowTitle("Benchmark")

        self.stackedWidget.setCurrentIndex(0) # Switch to stack index 0. I used stacked widget to create a loading screen. Index 0: Loading page, Index 1: Results page
        self.spinner_widget = SpinnerWidget() # Custom spinning widget for loading screen
        self.progressbar_widget = ProgressbarWidget() # Custom progressbar widget for loading screen

        self.loading_box = QVBoxLayout(self.groupBoxLoading)

        # Add custom widgets into loading box
        self.loading_box.addWidget(self.spinner_widget, alignment=Qt.AlignmentFlag.AlignCenter) # Center the spinner
        self.loading_box.addWidget(self.progressbar_widget) # Not needed to center progressbar. It already calculates the window size and draws itself

        # Hide widgets. We will show them again when they are needed
        self.progressbar_widget.hide()
        self.spinner_widget.hide()

        # Define dialog buttons
        self.ok_button = self.buttonBox.button(QDialogButtonBox.Ok)
        self.cancel_button = self.buttonBox.button(QDialogButtonBox.Cancel)
        self.reset_button = self.buttonBox.button(QDialogButtonBox.Reset)

        # Hide buttons
        self.ok_button.hide()
        self.reset_button.hide()
        self.cancel_button.hide()

        # Connect buttons to functions
        self.reset_button.clicked.connect(self.reset_process)
        self.cancel_button.clicked.connect(self.closeEvent)

        # Benchmark Thread
        self.benchmark_thread = BenchmarkThread(self, disk_test_path="/home") # to-do: add support for user-given paths

        self.benchmark_thread.prepare_progress.connect(self.update_prepare_progressbar)
        self.benchmark_thread.benchmark_result.connect(self.update_stats)
        self.benchmark_thread.process_status.connect(self.update_process_status)

        self.benchmark_thread.start()


    def update_prepare_progressbar(self, data):
        self.progressbar_widget.setValue(data)

        if data == 100: # Change the process message to preparing after download is finished
            self.labelProcessMessage.setText("Preparing")

    def update_stats(self, result_type, result):
        if result_type == "disk":
            # Update labels with collected data
            self.labelDiskSpeed.setText(f"R: {result['read_speed']} MB/s\nW: {result['write_speed']} MB/s")
            self.labelDiskLatency.setText(f"R: {result['read_latency']} ms\nW: {result['write_latency']} ms")
            self.labelDiskIOPS.setText(f"R: {result['read_iops']}\nW: {result['write_iops']}")

            # Give the scores using calibration data
            rs = result['read_speed']
            score_read = score_by_threshold(rs, read_speed_score_table)
            
            ws = result['write_speed']
            score_write = score_by_threshold(ws, write_speed_score_table)
            speed_score = int((score_read + score_write) / 2)

            rl = result['read_latency']
            score_read = score_by_threshold(rl, read_latency_score_table)

            wl = result['write_latency']
            score_write = score_by_threshold(wl, write_latency_score_table)
            latency_score = int((score_read + score_write) / 2)
            
            ri = result['read_iops']
            score_read = score_by_threshold(ri, read_iops_score_table)

            wi = result['write_iops']
            score_write = score_by_threshold(wi, write_iops_score_table)
            iops_score = int((score_read + score_write) / 2)

            overall_score = int(calculate_disk_score(latency_score, iops_score))

            # Update score labels
            self.labelSpeedScore.setText(f"{speed_score}/100")
            self.labelLatencyScore.setText(f"{latency_score}/100")
            self.labelIOPSScore.setText(f"{iops_score}/100")
            self.labelOverallScore.setText(f"{overall_score}/100")

        elif result_type == "zstd":
            self.labelZstdSpeed.setText(f"C: {result['compress_speed']} MB/s\nD: {result['decompress_speed']} MB/s")
            
            score_compress = score_by_threshold(result['compress_speed'], zstd_compress_score_table)
            score_decompress = score_by_threshold(result['decompress_speed'], zstd_decompress_score_table)
            
            zstd_score = int((score_compress + score_decompress) / 2)

            self.labelZstdScore.setText(f"{zstd_score}/100")

        elif result_type == "lz4":
            self.labelLz4Speed.setText(f"C: {result['compress_speed']} MB/s\nD: {result['decompress_speed']} MB/s")

            score_compress = score_by_threshold(result['compress_speed'], lz4_compress_score_table)
            score_decompress = score_by_threshold(result['decompress_speed'], lz4_decompress_score_table)
            
            lz4_score = int((score_compress + score_decompress) / 2)
            self.labelLz4Score.setText(f"{lz4_score}/100")

    def update_process_status(self, data):
        titles = {
            "error": "Error",
            "prepare": "Downloading",
            "disk": "Benchmarking",
            "lz4": "Benchmarking",
            "zstd": "Benchmarking"
        }

        messages = {
            "prepare": "Downloading the Silesia benchmark data\n(~200 MB)",
            "disk": "Benchmarking disk",
            "lz4": "Benchmarking LZ4 Performance",
            "zstd": "Benchmarking ZSTD Performance"
        }

        if data == "prepare":
            self.setFixedSize(300, 200)
            self.updateGeometry()
            self.groupBoxLoading.setTitle(titles[data])

            # Set widget visibilities
            self.progressbar_widget.show()
            self.cancel_button.show()

            self.labelProcessMessage.setText(messages[data])

        elif data in ("disk", "lz4", "zstd"):
            self.setFixedSize(300, 200)
            self.updateGeometry()
            self.groupBoxLoading.setTitle(titles[data])

            # Set widget visibilities
            self.progressbar_widget.hide()
            self.spinner_widget.show()
            self.spinner_widget.start()
            self.cancel_button.show()

            self.labelProcessMessage.setText(messages[data])

        elif data == "done":
            self.stackedWidget.setCurrentIndex(1) # Switch to results page
            self.setFixedSize(400, 600) # Update fixed size to big window.
            self.updateGeometry()
        
            # Set widget visibilities
            self.cancel_button.hide()
            self.ok_button.show()
            self.reset_button.show()
            
            # Delete widgets safely
            self.loading_box.removeWidget(self.spinner_widget)
            self.loading_box.removeWidget(self.progressbar_widget)
            self.spinner_widget.deleteLater()
            self.progressbar_widget.deleteLater()

        else:
            # Error case
            self.groupBoxLoading.setTitle(titles[data])
            self.progressbar_widget.hide()
            self.spinner_widget.hide()

            # Set widget visibilities
            self.cancel_button.hide()
            self.ok_button.show()
            self.reset_button.show()

            # Terminate the benchmark thread safely
            if self.benchmark_thread.isRunning():
                self.benchmark_thread.terminate()
                self.benchmark_thread.wait()
            
    def reset_process(self):
        if self.benchmark_thread.isRunning():
            self.benchmark_thread.terminate()
            self.benchmark_thread.wait()
        clear_cache()
        self.done(2) # Reset call
    
    def closeEvent(self, event): # Used by both window close button and cancel button
        if self.benchmark_thread.isRunning():
            self.benchmark_thread.terminate()
            self.benchmark_thread.wait()
        self.done(0)

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

        # Connect the buttonBenchmark into open_benchmark_window function
        self.buttonBenchmark.clicked.connect(self.open_benchmark_window)

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

    def open_benchmark_window(self):
        benchmark_window = BenchmarkWindow(self)

        # Make the window modal so it will block the events on main window
        benchmark_window.setWindowModality(Qt.WindowModality.ApplicationModal)
        result = benchmark_window.exec()
        if result == 2:
            self.open_benchmark_window()




if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL) # Handle CTRL+C interrupt
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())