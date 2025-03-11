import os
import sys
import traceback
import concurrent.futures
import numpy as np
from PIL import Image
import cv2
import pillow_heif
from pillow_heif import register_heif_opener
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                              QHBoxLayout, QPushButton, QLabel, QComboBox,
                              QFileDialog, QProgressBar, QCheckBox, QLineEdit,
                              QSpinBox, QGroupBox, QMessageBox, QTextEdit)
from PySide6.QtCore import Qt, QThreadPool, QRunnable, Signal, QObject, Slot

register_heif_opener()

# PIL uses "JPEG" instead of "JPG" internally
FORMAT_MAPPING = {
    'JPG': 'JPEG',
    'PNG': 'PNG',
    'BMP': 'BMP',
    'TIFF': 'TIFF',
    'WEBP': 'WEBP',
    'HEIC': 'HEIC'  # We'll handle this specially
}

# Formats we can save to
SUPPORTED_OUTPUT_FORMATS = ['JPG', 'PNG', 'BMP', 'TIFF', 'WEBP', 'HEIC']

# Formats we can read from
SUPPORTED_INPUT_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.heic', '.heif',
                             '.tiff', '.tif', '.webp')

class WorkerSignals(QObject):
    progress = Signal(int)
    completed = Signal(int)
    finished = Signal()
    error = Signal(str)
    log = Signal(str)

class ImageConverter(QRunnable):
    def __init__(self, files, output_format, output_dir, append_suffix,
                 max_workers, heic_quality=90):
        super().__init__()
        self.files = files
        self.output_format = output_format
        self.output_dir = output_dir
        self.append_suffix = append_suffix
        self.max_workers = max_workers
        self.heic_quality = heic_quality
        self.signals = WorkerSignals()
        self._is_cancelled = False

    def save_as_heic(self, image, output_path):
        """Save image as HEIC using pillow_heif directly"""
        self.signals.log.emit("Using pillow_heif for HEIC output")

        # Convert PIL image to numpy array for OpenCV
        img_array = np.array(image)

        # Convert RGB to BGR (OpenCV uses BGR)
        if len(img_array.shape) == 3 and img_array.shape[2] == 3:
            img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        elif len(img_array.shape) == 3 and img_array.shape[2] == 4:
            img_array = cv2.cvtColor(img_array, cv2.COLOR_RGBA2BGRA)

        # Determine mode
        if len(img_array.shape) == 2:
            mode = "L"
        elif img_array.shape[2] == 3:
            mode = "BGR"
        elif img_array.shape[2] == 4:
            mode = "BGRA"
        else:
            raise ValueError(f"Unsupported image shape: {img_array.shape}")

        # Create HEIF file
        heif_file = pillow_heif.from_bytes(
            mode=mode,
            size=(img_array.shape[1], img_array.shape[0]),
            data=bytes(img_array)
        )

        # Save the file
        quality = max(0, min(100, self.heic_quality))
        heif_file.save(output_path, quality=quality)

    def convert_image(self, input_path):
        try:
            if self._is_cancelled:
                return False

            # Normalize path separators
            input_path = os.path.normpath(input_path)

            base_name, ext = os.path.splitext(os.path.basename(input_path))
            if self.append_suffix:
                base_name += "_out"

            # Ensure output directory exists
            os.makedirs(self.output_dir, exist_ok=True)

            output_path = os.path.join(self.output_dir,
                                        f"{base_name}.{self.output_format.lower()}")

            # Log the conversion attempt
            self.signals.log.emit(f"Converting: {input_path} to {output_path}")

            # Open image with Pillow
            image = Image.open(input_path)

            # Convert to RGB for formats that don't support RGBA
            if self.output_format.upper() in ['JPG', 'JPEG'] and image.mode in ['RGBA', 'P']:
                image = image.convert("RGB")
                self.signals.log.emit(
                    f"Converting image to RGB mode for {self.output_format}")

            # Special handling for HEIC output
            if self.output_format.upper() == 'HEIC':
                self.save_as_heic(image, output_path)
            else:
                # Get the correct format name for PIL
                pil_format = FORMAT_MAPPING.get(self.output_format,
                                                  self.output_format)

                # Save with proper format
                image.save(output_path, format=pil_format)

            self.signals.log.emit(f"Successfully converted: {input_path}")
            return True
        except Exception as e:
            error_details = traceback.format_exc()
            error_msg = f"Error converting {input_path}: {str(e)}\n{error_details}"
            self.signals.error.emit(error_msg)
            return False

    def cancel(self):
        self._is_cancelled = True
        self.signals.log.emit("Conversion cancelled")

    @Slot()
    def run(self):
        completed = 0
        total_files = len(self.files)

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.max_workers) as executor:
            futures = {executor.submit(self.convert_image, file): file
                       for file in self.files}

            for future in concurrent.futures.as_completed(futures):
                if self._is_cancelled:
                    break
                completed += 1
                self.signals.progress.emit(
                    int(completed * 100 / total_files))
                self.signals.completed.emit(completed)

        self.signals.finished.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Format Converter")
        self.setMinimumWidth(700)
        self.setMinimumHeight(600)

        self.files_to_convert = []
        self.setup_ui()
        self.converter = None

    def setup_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)

        # Input selection
        input_group = QGroupBox("Input")
        input_layout = QVBoxLayout(input_group)

        input_file_layout = QHBoxLayout()
        self.input_path_edit = QLineEdit()
        self.input_path_edit.setReadOnly(True)
        select_file_btn = QPushButton("Select File")
        select_file_btn.clicked.connect(self.select_input_file)
        select_dir_btn = QPushButton("Select Directory")
        select_dir_btn.clicked.connect(self.select_input_dir)

        input_file_layout.addWidget(self.input_path_edit)
        input_file_layout.addWidget(select_file_btn)
        input_file_layout.addWidget(select_dir_btn)

        input_layout.addLayout(input_file_layout)

        self.recursive_check = QCheckBox("Process subdirectories recursively")
        input_layout.addWidget(self.recursive_check)

        # Output settings
        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(output_group)

        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Output format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(SUPPORTED_OUTPUT_FORMATS)
        format_layout.addWidget(self.format_combo)

        # HEIC Quality setting
        self.heic_quality_layout = QHBoxLayout()
        self.heic_quality_layout.addWidget(QLabel("HEIC Quality:"))
        self.heic_quality_spin = QSpinBox()
        self.heic_quality_spin.setMinimum(0)
        self.heic_quality_spin.setMaximum(100)
        self.heic_quality_spin.setValue(90)
        self.heic_quality_layout.addWidget(self.heic_quality_spin)
        self.heic_quality_layout.addStretch()

        output_layout.addLayout(format_layout)
        output_layout.addLayout(self.heic_quality_layout)

        # Connect format combo to show/hide HEIC quality setting
        self.format_combo.currentTextChanged.connect(self.toggle_heic_quality)

        output_dir_layout = QHBoxLayout()
        output_dir_layout.addWidget(QLabel("Output directory:"))
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setText(os.path.join(os.getcwd(), "converted"))
        output_dir_btn = QPushButton("Browse")
        output_dir_btn.clicked.connect(self.select_output_dir)
        output_dir_layout.addWidget(self.output_dir_edit)
        output_dir_layout.addWidget(output_dir_btn)
        output_layout.addLayout(output_dir_layout)

        self.append_suffix_check = QCheckBox("Append '_out' to filenames")
        self.append_suffix_check.setChecked(True)
        output_layout.addWidget(self.append_suffix_check)

        # Performance settings
        perf_group = QGroupBox("Performance")
        perf_layout = QHBoxLayout(perf_group)

        perf_layout.addWidget(QLabel("Parallel workers:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setMinimum(1)
        self.workers_spin.setMaximum(16)
        self.workers_spin.setValue(min(4, os.cpu_count() or 4))
        perf_layout.addWidget(self.workers_spin)
        perf_layout.addStretch()

        # Progress
        progress_layout = QVBoxLayout()
        progress_info_layout = QHBoxLayout()
        self.progress_label = QLabel("Ready")
        self.files_processed_label = QLabel("0/0 files processed")
        progress_info_layout.addWidget(self.progress_label)
        progress_info_layout.addStretch()
        progress_info_layout.addWidget(self.files_processed_label)

        self.progress_bar = QProgressBar()
        progress_layout.addLayout(progress_info_layout)
        progress_layout.addWidget(self.progress_bar)

        # Log window
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)

        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(self.clear_log)
        log_layout.addWidget(clear_log_btn)

        # Buttons
        buttons_layout = QHBoxLayout()
        self.convert_btn = QPushButton("Convert")
        self.convert_btn.clicked.connect(self.start_conversion)
        self.convert_btn.setEnabled(False)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_conversion)
        self.cancel_btn.setEnabled(False)

        buttons_layout.addStretch()
        buttons_layout.addWidget(self.convert_btn)
        buttons_layout.addWidget(self.cancel_btn)

        # Add all layouts to main layout
        main_layout.addWidget(input_group)
        main_layout.addWidget(output_group)
        main_layout.addWidget(perf_group)
        main_layout.addLayout(progress_layout)
        main_layout.addWidget(log_group)
        main_layout.addLayout(buttons_layout)

        self.setCentralWidget(main_widget)

        # Initial log message
        self.log_text.append("Image Converter ready.")
        self.log_text.append("Supported input formats: " + ", ".join(
            [ext[1:].upper() for ext in SUPPORTED_INPUT_EXTENSIONS]))
        self.log_text.append("Supported output formats: " + ", ".join(
            SUPPORTED_OUTPUT_FORMATS))

        # Initial state for HEIC quality
        self.toggle_heic_quality(self.format_combo.currentText())

    def toggle_heic_quality(self, format_text):
        """Show or hide HEIC quality settings based on selected format"""
        show_quality = format_text.upper() == 'HEIC'
        for i in range(self.heic_quality_layout.count()):
            item = self.heic_quality_layout.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(show_quality)

    def clear_log(self):
        self.log_text.clear()
        self.log_text.append("Log cleared.")

    def select_input_file(self):
        file_filter = f"Image Files ({' '.join(['*' + ext for ext in SUPPORTED_INPUT_EXTENSIONS])})"
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Image File", "", file_filter
        )
        if file_path:
            self.input_path_edit.setText(file_path)
            self.files_to_convert = [file_path]
            self.convert_btn.setEnabled(True)
            self.log_text.append(f"Selected file: {file_path}")

    def select_input_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory")
        if dir_path:
            self.input_path_edit.setText(dir_path)
            self.collect_files(dir_path)
            self.log_text.append(f"Selected directory: {dir_path}")

    def select_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_dir_edit.setText(dir_path)
            self.log_text.append(f"Output directory set to: {dir_path}")

    def collect_files(self, dir_path):
        self.files_to_convert = []

        try:
            if self.recursive_check.isChecked():
                for root, _, files in os.walk(dir_path):
                    for file in files:
                        if file.lower().endswith(SUPPORTED_INPUT_EXTENSIONS):
                            # Normalize path
                            file_path = os.path.normpath(os.path.join(root, file))
                            self.files_to_convert.append(file_path)
            else:
                for file in os.listdir(dir_path):
                    if file.lower().endswith(SUPPORTED_INPUT_EXTENSIONS):
                        # Normalize path
                        file_path = os.path.normpath(os.path.join(dir_path, file))
                        self.files_to_convert.append(file_path)

            self.log_text.append(
                f"Found {len(self.files_to_convert)} image files to convert")
            self.files_processed_label.setText(
                f"0/{len(self.files_to_convert)} files processed")
            self.convert_btn.setEnabled(len(self.files_to_convert) > 0)
        except Exception as e:
            self.log_text.append(f"Error collecting files: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to scan directory: {str(e)}")

    def start_conversion(self):
        output_dir = self.output_dir_edit.text()
        try:
            os.makedirs(output_dir, exist_ok=True)

            self.progress_bar.setValue(0)
            self.progress_label.setText("Converting...")
            self.convert_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)

            # Create and start worker
            self.converter = ImageConverter(
                self.files_to_convert,
                self.format_combo.currentText(),
                output_dir,
                self.append_suffix_check.isChecked(),
                self.workers_spin.value(),
                self.heic_quality_spin.value()
            )

            self.converter.signals.progress.connect(self.update_progress)
            self.converter.signals.completed.connect(self.update_files_processed)
            self.converter.signals.finished.connect(self.conversion_finished)
            self.converter.signals.error.connect(self.show_error)
            self.converter.signals.log.connect(self.add_log)

            self.log_text.append(
                f"Starting conversion of {len(self.files_to_convert)} files to "
                f"{self.format_combo.currentText()} format")
            QThreadPool.globalInstance().start(self.converter)
        except Exception as e:
            self.log_text.append(f"Error starting conversion: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to start conversion: {str(e)}")
            self.convert_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)

    def cancel_conversion(self):
        if self.converter:
            self.converter.cancel()
        self.cancel_btn.setEnabled(False)
        self.convert_btn.setEnabled(True)
        self.progress_label.setText("Conversion cancelled.")

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_files_processed(self, completed):
        total = len(self.files_to_convert)
        self.files_processed_label.setText(
            f"{completed}/{total} files processed")

    def conversion_finished(self):
        self.progress_label.setText("Conversion completed")
        self.convert_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.log_text.append("Conversion process completed")
        QMessageBox.information(self, "Success",
                                "Image conversion completed successfully!")

    def show_error(self, error_msg):
        self.log_text.append(f"ERROR: {error_msg}")

    def add_log(self, message):
        self.log_text.append(message)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
