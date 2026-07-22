import signal, sys
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
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
from helper_functions import * # get_memory_status, get_swap_information, check_cpu_avx_support, get_disk_type, check_swap_requirement, prepare_silesia_benchmark_data, benchmark_disk, benchmark_algorithm, clear_cache, check_and_disable_cow, score_by_threshold, get_swappiness, get_usable_compression_algorithms, get_partitions
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

class ManagerWindow(QDialog):
    def __init__(self, parent=None, page="swap"):
        super(ManagerWindow, self).__init__()

        pages = {
            "swap": 0,
            "zram": 1
        }
    
        self.swappiness = get_swappiness()

        self.usable_algorithms = get_usable_compression_algorithms()
        self.partitions = get_partitions()

        self.swaps = get_swap_information()

        current_dir = Path(__file__).resolve().parent
        ui_path = current_dir.parent / "ui" / "ManageSwapZram.ui"

        load_ui(ui_path, self)
        
        self.stackedWidget.setCurrentIndex(pages[page])
        self.apply_button = self.buttonBox.button(QDialogButtonBox.Apply)

        self.set_size_limits()
        self.connect_ui_interactions()
        self.load_current_configuration()

    def load_current_configuration(self):

        zram = self.swaps["zram"]
        swap = self.swaps["swap"]

        self.comboBoxSwapType.addItem("File")
        self.comboBoxSwapType.addItem("Partition")

        self.spinBoxSwappiness.setValue(self.swappiness)

        for algorithm in self.usable_algorithms:
            self.comboBoxZramAlgorithm.addItem(algorithm)
            self.comboBoxZswapAlgorithm.addItem(algorithm)
        
        for partition in self.partitions:
            self.comboBoxSwapPartitionPath.addItem(partition)

        if zram["enabled"]:
            self.doubleSpinBoxZramSize.setValue(zram["size"])
            self.spinBoxZramPriority.setValue(zram["priority"])
            self.comboBoxZramAlgorithm.setCurrentText(zram["algorithm"])

        else:
            self.doubleSpinBoxZramSize.setValue(0.0)
            self.spinBoxZramPriority.setValue(0)
        
        if swap["enabled"]:
            self.doubleSpinBoxSwapSize.setValue(swap["size"])
            self.spinBoxSwapPriority.setValue(swap["priority"])
            if swap["type"] == "partition":
                self.comboBoxSwapType.setCurrentText("Partition")
                self.comboBoxSwapPartitionPath.setCurrentText(swap["path"])
                self.stackedWidgetSwapPath.setCurrentIndex(1)
            else:
                self.comboBoxSwapType.setCurrentText("File")
                self.lineEditSwapFilePath.setText(swap["path"])
                self.stackedWidgetSwapPath.setCurrentIndex(0)
            
            self.radioButtonZswapEnabled.setChecked(swap["zswap_enabled"])
            self.comboBoxZswapAlgorithm.setEnabled(swap["zswap_enabled"])
            self.comboBoxZswapAlgorithm.setCurrentText(swap["zswap_algorithm"])
        
        else:
            self.doubleSpinBoxSwapSize.setValue(0.0)
            self.spinBoxSwapPriority.setValue(0)
            self.comboBoxSwapType.setCurrentText("File")
            self.lineEditSwapFilePath.setText("/swapfile")
            self.stackedWidgetSwapPath.setCurrentIndex(0)
            self.radioButtonZswapEnabled.setChecked(swap["zswap_enabled"])
            self.comboBoxZswapAlgorithm.setEnabled(swap["zswap_enabled"])
            self.comboBoxZswapAlgorithm.setCurrentText(swap["zswap_algorithm"])
    
    def set_size_limits(self):
        ram = get_memory_status()
        ram_size = ram["total"]

        # Limit the maximum allowed swap and zram size. 2x for swap, 1.5x for zram. we have to limit it before loading current status otherwise it may cause bugs
        self.doubleSpinBoxSwapSize.setMaximum(ram_size*2)
        self.sliderSwapSize.setMaximum(ram_size*2*10)

        self.doubleSpinBoxZramSize.setMaximum(round(ram_size*1.5))
        self.sliderZramSize.setMaximum(round(ram_size*1.5*10))

    def connect_ui_interactions(self):
        # Connect size sliders and double spin boxes. can not be done in the ui side because slider takes integer values and double spin box takes float values. we have to convert them first. there its done with lambda functions. sliders scaled as 10x for proper sync
        self.sliderSwapSize.valueChanged.connect(
            lambda value: self.doubleSpinBoxSwapSize.setValue(value / 10) 
            if abs(self.doubleSpinBoxSwapSize.value() - (value / 10)) > 1e-5 else None # Check if its already synced before syncing again. use 1e-5 for float calculating error tolerance
        )
        self.doubleSpinBoxSwapSize.valueChanged.connect(
            lambda value: self.sliderSwapSize.setValue(int(value * 10)) 
            if abs(self.sliderSwapSize.value() - int(value * 10)) > 0 else None
        )

        self.sliderZramSize.valueChanged.connect(
            lambda value: self.doubleSpinBoxZramSize.setValue(value / 10) 
            if abs(self.doubleSpinBoxZramSize.value() - (value / 10)) > 1e-5 else None
        )
        self.doubleSpinBoxZramSize.valueChanged.connect(
            lambda value: self.sliderZramSize.setValue(int(value * 10)) 
            if abs(self.sliderZramSize.value() - int(value * 10)) > 0 else None
        )

        # Set checked button using current widget
        current_index = self.stackedWidget.currentIndex()
        if current_index == 0:
            self.buttonSwap.setChecked(True)
        else:
            self.buttonZram.setChecked(True)

        # Make the page switch when one of the buttons toggled. TODO: buttonZram.toggled.connect returns bool, but setCurrentIndex function requires integer normally. it works for now and probably will work forever, at least until we add a new page. but its not planned so lets left it as it was. fix if it may cause a problem in the future
        self.buttonZram.toggled.connect(lambda page_id: self.stackedWidget.setCurrentIndex(page_id))

        # Enable the zswap algorithm combo box if radio button is checked
        self.radioButtonZswapEnabled.toggled.connect(self.comboBoxZswapAlgorithm.setEnabled)

        # Change swap path stacked widget index when swaptype value changed
        self.comboBoxSwapType.currentIndexChanged.connect(lambda value: self.stackedWidgetSwapPath.setCurrentIndex(value))

        # Swappiness value reset button. now it just sets the vaule to last saved. TODO: make it set a fixed default level when right clicked
        self.buttonSwappinessReset.clicked.connect(lambda: self.sliderSwappiness.setValue(self.swappiness))

        self.buttonOpenFilePicker.clicked.connect(self.open_file_picker)

        self.apply_button.clicked.connect(lambda: self.open_apply_configuration_dialog(diff=self.get_diff()))

    def open_file_picker(self):
        path, _ = QFileDialog.getOpenFileName( # 'path, _' because _ takes the second variable and left a cleaner output to path variable
            self, "Choose swapfile", "/"
        )

        if path:
            self.lineEditSwapFilePath.setText(path)

    def get_diff(self):
        zram = self.swaps["zram"]
        swap = self.swaps["swap"]
        diff = []

        swappiness_new = self.spinBoxSwappiness.value()
        if swappiness_new != self.swappiness:
            diff.append({"swappiness": swappiness_new})
        
        current_page = self.stackedWidget.currentIndex()
        if current_page:
            zram_size_new = self.doubleSpinBoxZramSize.value()
            if zram_size_new != zram["size"]:
                diff.append({"zram_size": zram_size_new})
            
            zram_priority_new = self.spinBoxZramPriority.value()
            if zram_priority_new != zram["priority"]:
                diff.append({"zram_priority": zram_priority_new})

            zram_algorithm_new = self.comboBoxZramAlgorithm.currentText()
            if zram_algorithm_new != zram["algorithm"]:
                diff.append({"zram_algorithm": zram_algorithm_new})
        
        else:
            swap_size_new = self.doubleSpinBoxSwapSize.value()
            if swap_size_new != swap["size"]:
                diff.append({"swap_size": swap_size_new})
            
            swap_priority_new = self.spinBoxSwapPriority.value()
            if swap_priority_new != swap["priority"]:
                diff.append({"swap_priority": swap_priority_new})
            
            swap_type_new = self.comboBoxSwapType.currentText()

            if swap_type_new != swap["type"]:
                diff.append({"swap_type": swap_type_new})

            if swap_type_new == "File":
                swap_path_new = self.lineEditSwapFilePath.text()
            else:
                swap_path_new = self.comboBoxSwapPartitionPath.currentText()

            if swap_path_new != swap["path"]:
                    diff.append({"swap_path": swap_path_new})
            
            zswap_enabled_new = self.radioButtonZswapEnabled.isChecked()
            if zswap_enabled_new != swap["zswap_enabled"]:
                diff.append({"zswap_enabled": zswap_enabled_new})
            
            zswap_algorithm_new = self.comboBoxZswapAlgorithm.currentText()
            if zswap_algorithm_new != swap["zswap_algorithm"]:
                diff.append({"zswap_algorithm": zswap_algorithm_new})

        return diff

    def open_apply_configuration_dialog(self, diff=None):
        if diff is None:
            self.done(0)
        else:
            configuration_check_dialog = ConfigurationCheckDialog(self)
            configuration_check_dialog.exec()

        print(diff)

class ConfigurationCheckDialog(QDialog):
    def __init__(self, parent=None):
        super(ConfigurationCheckDialog, self).__init__()

        current_dir = Path(__file__).resolve().parent
        ui_path = current_dir.parent / "ui" / "checkConfiguration.ui"

        load_ui(ui_path, self)

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
        
        # Call update functions manually for first time
        self.update_information_periodically()
        self.update_information_once()
        self.update_swap_table()

        # Timer for autoupdate
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_information_periodically)
        self.timer.start(500)

        self.buttonZramEdit.clicked.connect(lambda: self.open_manager_window(page="zram"))
        self.buttonSwapEdit.clicked.connect(lambda: self.open_manager_window(page="swap"))

        self.buttonBenchmark.clicked.connect(self.open_benchmark_window)

    def update_information_periodically(self):
        # Update RAM status
        ram_status = get_memory_status()
        self.ram_graph.set_values(ram_status['percentage'], f"{ram_status['used']} GiB", f"{ram_status['total']} GiB")

        # Update SWAP status
        swap_status = get_memory_status("swap")
        self.swap_graph.set_values(swap_status['percentage'], f"{swap_status['used']} GiB", f"{swap_status['total']} GiB")

    def update_information_once(self):
        
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

    def update_swap_table(self):
        swaps = get_swap_information()
        
        zram = swaps["zram"]
        swap = swaps["swap"]

        if zram["enabled"]:
            self.labelZramPath.setText(zram["path"])
            self.labelZramType.setText("zram")
            self.labelZramSize.setText(str(zram["size"]))
            self.labelZramPriority.setText(str(zram["priority"]))
        else:
            self.labelZramPath.setText("-")
            self.labelZramType.setText("-")
            self.labelZramSize.setText("-")
            self.labelZramPriority.setText("-")
        
        if swap["enabled"]:
            self.labelSwapPath.setText(swap["path"])
            self.labelSwapType.setText(swap["type"])
            self.labelSwapSize.setText(str(swap["size"]))
            self.labelSwapPriority.setText(str(swap["priority"]))
        else:
            self.labelSwapPath.setText("-")
            self.labelSwapType.setText("-")
            self.labelSwapSize.setText("-")
            self.labelSwapPriority.setText("-")

    def open_benchmark_window(self):
        benchmark_window = BenchmarkWindow(self)

        # Make the window modal so it will block the events on main window
        benchmark_window.setWindowModality(Qt.WindowModality.ApplicationModal)
        result = benchmark_window.exec()
        if result == 2:
            self.open_benchmark_window()
    
    def open_manager_window(self, page="swap"):
        manager_window = ManagerWindow(self, page=page)
        result = manager_window.exec()




if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL) # Handle CTRL+C interrupt
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())