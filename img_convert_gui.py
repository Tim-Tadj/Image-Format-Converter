import os
import sys
import traceback
import concurrent.futures
import numpy as np
from PIL import Image
import cv2
import pillow_heif
from pillow_heif import register_heif_opener
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QThreadPool, QRunnable, Signal, QObject, Slot

register_heif_opener()

# PIL uses "JPEG" instead of "JPG" internally
FORMAT_MAPPING = {
    "JPG": "JPEG",
    "PNG": "PNG",
    "BMP": "BMP",
    "TIFF": "TIFF",
    "WEBP": "WEBP",
    "HEIC": "HEIC",  # We'll handle this specially
}

# Formats we can save to
SUPPORTED_OUTPUT_FORMATS = ["JPG", "PNG", "BMP", "TIFF", "WEBP", "HEIC"]

# Formats we can read from
SUPPORTED_INPUT_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".heic",
    ".heif",
    ".tiff",
    ".tif",
    ".webp",
)


class WorkerSignals(QObject):
    progress = Signal(int)
    completed = Signal(int)
    finished = Signal()
    error = Signal(str)
    log = Signal(str)


class ImageConverter(QRunnable):
    def __init__(
        self,
        files,
        output_format,
        output_dir,
        append_suffix,
        max_workers,
        replace_files,
        heic_quality=90,
    ):
        super().__init__()
        self.files = files
        self.output_format = output_format
        self.output_dir = output_dir
        self.append_suffix = append_suffix
        self.max_workers = max_workers
        self.replace_files = replace_files
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
            data=bytes(img_array),
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

            # Check if file still exists
            if not os.path.exists(input_path):
                self.signals.log.emit(
                    f"Skipping: {input_path} - file no longer exists"
                )
                return False

            base_name, ext = os.path.splitext(os.path.basename(input_path))
            ext = ext[1:].upper()  # Remove the dot and uppercase it

            # Skip if converting to the same format
            if ext == self.output_format.upper():
                self.signals.log.emit(
                    f"Skipping: {input_path} - same format conversion"
                )
                return False

            if self.append_suffix and not self.replace_files:
                base_name += "_out"

            # Ensure output directory exists
            if not self.replace_files:
                os.makedirs(self.output_dir, exist_ok=True)

            output_dir = self.output_dir if not self.replace_files else os.path.dirname(
                input_path
            )
            output_path = os.path.join(
                output_dir, f"{base_name}.{self.output_format.lower()}"
            )

            # Log the conversion attempt
            self.signals.log.emit(f"Converting: {input_path} to {output_path}")

            # Open image with Pillow
            image = Image.open(input_path)

            # Convert to RGB for formats that don't support RGBA
            if (
                self.output_format.upper() in ["JPG", "JPEG"]
                and image.mode in ["RGBA", "P"]
            ):
                image = image.convert("RGB")
                self.signals.log.emit(
                    f"Converting image to RGB mode for {self.output_format}"
                )

            # Special handling for HEIC output
            if self.output_format.upper() == "HEIC":
                self.save_as_heic(image, output_path)
            else:
                # Get the correct format name for PIL
                pil_format = FORMAT_MAPPING.get(self.output_format, self.output_format)

                # Save with proper format
                image.save(output_path, format=pil_format)

            if self.replace_files:
                os.remove(input_path)

            self.signals.log.emit(f"Successfully converted: {input_path}")
            return True
        except FileNotFoundError:
            self.signals.log.emit(
                f"Skipping: {input_path} - file no longer exists"
            )
            return False
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
            max_workers=self.max_workers
        ) as executor:
            futures = {
                executor.submit(self.convert_image, file): file for file in self.files
            }

            for future in concurrent.futures.as_completed(futures):
                if self._is_cancelled:
                    break

                # Only count as completed if the conversion was successful
                if future.result():
                    completed += 1

                self.signals.progress.emit(int(completed * 100 / total_files))
                self.signals.completed.emit(completed)

        self.signals.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Format Converter")
        self.setMinimumWidth(700)
        self.setMinimumHeight(600)

        self.files_to_convert = []
        self.current_dir = None
        self.is_processing = False
        self.output_dir_set = False  # Flag to track if output dir is set

        # Prepare input formats for the combobox
        self.input_formats = {"Auto-detect": []} # Auto-detect maps to all extensions
        for ext in SUPPORTED_INPUT_EXTENSIONS:
            display_ext = ext[1:].upper()
            # Group extensions like JPG and JPEG under JPG
            if display_ext == "JPEG":
                display_ext = "JPG"
            if display_ext not in self.input_formats:
                self.input_formats[display_ext] = []
            self.input_formats[display_ext].append(ext)
        # For Auto-detect, gather all unique extensions
        all_exts = set()
        for ext_list in self.input_formats.values():
            all_exts.update(ext_list)
        self.input_formats["Auto-detect"] = sorted(list(all_exts))


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

        # Directory options
        dir_options_layout = QHBoxLayout()
        self.recursive_check = QCheckBox("Process subdirectories recursively")
        self.recursive_check.setChecked(True)  # Default to True
        self.recursive_check.stateChanged.connect(self.update_file_count)
        self.recursive_check.setToolTip("Process all subdirectories within the selected directory.")

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.update_file_count)
        refresh_btn.setToolTip("Re-scan the selected directory using the current input format and recursive settings.")

        dir_options_layout.addWidget(self.recursive_check)
        dir_options_layout.addStretch()
        dir_options_layout.addWidget(refresh_btn)

        input_layout.addLayout(dir_options_layout)

        # Input format selection
        input_format_layout = QHBoxLayout()
        input_format_layout.addWidget(QLabel("Input format:"))
        self.input_format_combo = QComboBox()
        
        # Populate input format combo box
        # Add "Auto-detect" first
        self.input_format_combo.addItem("Auto-detect")
        # Add other formats, ensuring JPG is favored over JPEG for display
        display_formats = sorted([fmt for fmt in self.input_formats.keys() if fmt != "Auto-detect"])
        
        # Custom sort to ensure specific order if needed, e.g. JPG before PNG
        # For now, alphabetical sort is fine for unique display names
        
        for fmt in display_formats:
            self.input_format_combo.addItem(fmt)
            
        self.input_format_combo.setCurrentText("Auto-detect")
        self.input_format_combo.currentTextChanged.connect(self.update_file_count)
        self.input_format_combo.setToolTip(
            "Select the input image format. 'Auto-detect' will try to identify supported images by their extension."
        )
        input_format_layout.addWidget(self.input_format_combo)
        input_format_layout.addStretch() # Add stretch to push combo box to the left
        input_layout.addLayout(input_format_layout)

        # File tree view
        self.file_tree_widget = QTreeWidget()
        self.file_tree_widget.setColumnCount(1)
        self.file_tree_widget.setHeaderLabels(["Files for Conversion"])
        self.file_tree_widget.setToolTip("Lists image files found. Check/uncheck files to include/exclude them from conversion.")
        input_layout.addWidget(self.file_tree_widget)
        
        # Active files count label (replaces old files_found_label functionality)
        self.active_files_label = QLabel("0 files selected for conversion")
        self.active_files_label.setStyleSheet("font-weight: bold;")
        input_layout.addWidget(self.active_files_label)


        # Output settings
        self.output_group = QGroupBox("Output")
        self.output_layout = QVBoxLayout(self.output_group)

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

        self.output_layout.addLayout(format_layout)
        self.output_layout.addLayout(self.heic_quality_layout)

        # Connect format combo to show/hide HEIC quality setting
        self.format_combo.currentTextChanged.connect(self.toggle_heic_quality)

        self.output_dir_group = QWidget()
        self.output_dir_layout = QVBoxLayout(self.output_dir_group)
        output_dir_layout = QHBoxLayout()
        output_dir_layout.addWidget(QLabel("Output directory:"))
        self.output_dir_edit = QLineEdit()
        # Set default text to an empty string
        self.output_dir_edit.setText("")
        output_dir_btn = QPushButton("Browse")
        output_dir_btn.clicked.connect(self.select_output_dir)
        output_dir_layout.addWidget(self.output_dir_edit)
        output_dir_layout.addWidget(output_dir_btn)
        self.output_dir_layout.addLayout(output_dir_layout)

        self.output_layout.addWidget(self.output_dir_group)

        self.append_suffix_check = QCheckBox("Append '_out' to filenames")
        self.append_suffix_check.setChecked(True)
        self.output_layout.addWidget(self.append_suffix_check)

        # Replace Files Checkbox - Moved to main layout
        self.replace_files_check = QCheckBox("Replace original files")
        self.replace_files_check.setChecked(False)
        self.replace_files_check.stateChanged.connect(self.toggle_output_group)
        # output_layout.addWidget(self.replace_files_check) # Removed from Output Group

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
        main_layout.addWidget(self.replace_files_check) # Add Replace check box to main layout
        main_layout.addWidget(self.output_group)  # The entire output group
        main_layout.addWidget(perf_group)
        main_layout.addLayout(progress_layout)
        main_layout.addWidget(log_group)
        main_layout.addLayout(buttons_layout)

        self.setCentralWidget(main_widget)

        # Initial log message
        self.log_text.append("Image Converter ready.")
        self.log_text.append(
            "Input formats: Select a specific format or 'Auto-detect' (checks: "
            + ", ".join([ext[1:].upper() for ext in SUPPORTED_INPUT_EXTENSIONS])
            + ")."
        )
        self.log_text.append(
            "Supported output formats: " + ", ".join(SUPPORTED_OUTPUT_FORMATS)
        )

        # Initial state for HEIC quality
        self.toggle_heic_quality(self.format_combo.currentText())

        # Initial state for output options
        self.toggle_output_group(self.replace_files_check.checkState())

        # Connect itemChanged signal for the tree widget
        if hasattr(self, 'file_tree_widget'):
            self.file_tree_widget.itemChanged.connect(self.update_active_file_count)


    def update_active_file_count(self, item=None): # item is passed by the signal but not always needed
        """Updates the active_files_label and convert_btn state based on checked items."""
        if not hasattr(self, 'file_tree_widget'):
            return

        checked_count = 0
        total_items = 0
        root = self.file_tree_widget.invisibleRootItem()
        
        # If current_dir is None, it means we are in single file mode or no dir selected
        # In this case, total_items should be the number of items currently in the tree.
        if self.current_dir is None:
            total_items = root.childCount()
        else:
            # If a directory is selected, total_items is len(self.files_to_convert)
            # which represents all files found by collect_files, not just what's in tree.
            # This needs to be from the tree itself for "X of Y" to make sense.
            total_items = root.childCount()


        for i in range(root.childCount()):
            tree_item = root.child(i)
            if tree_item.checkState(0) == Qt.Checked:
                checked_count += 1
        
        if hasattr(self, 'active_files_label'):
            self.active_files_label.setText(f"{checked_count} of {total_items} files selected")
        
        self.convert_btn.setEnabled(checked_count > 0)


    def toggle_heic_quality(self, format_text):
        """Show or hide HEIC quality settings based on selected format"""
        show_quality = format_text.upper() == "HEIC"
        for i in range(self.heic_quality_layout.count()):
            item = self.heic_quality_layout.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(show_quality)

    def toggle_output_group(self, state):
        """Show or hide the entire output group box based on the replace files checkbox"""
        replace_files = state == Qt.Checked
        self.output_group.setVisible(not replace_files)  # Hide output group when replacing files
        # Clear output directory when replacing files
        if replace_files:
            self.output_dir_edit.clear()
            self.output_dir_set = False  # Reset the output dir flag
        else:
            # Revert to previous output directory if available
            if hasattr(self, 'last_output_dir'):
                self.output_dir_edit.setText(self.last_output_dir)
                self.output_dir_set = True


    def clear_log(self):
        self.log_text.clear()
        self.log_text.append("Log cleared.")

    def select_input_file(self):
        selected_format = self.input_format_combo.currentText()
        
        if selected_format == "Auto-detect":
            file_filter = (
                f"All Supported Image Files ({' '.join(['*' + ext for ext in SUPPORTED_INPUT_EXTENSIONS])})"
            )
        else:
            extensions = self.input_formats.get(selected_format, [])
            if extensions:
                # Format name for display, e.g. "JPEG"
                format_display_name = selected_format.upper()
                # Create filter string, e.g., "JPEG Files (*.jpg *.jpeg)"
                file_filter = f"{format_display_name} Files ({' '.join(['*' + ext for ext in extensions])})"
            else: # Fallback, should ideally not happen
                file_filter = (
                    f"All Supported Image Files ({' '.join(['*' + ext for ext in SUPPORTED_INPUT_EXTENSIONS])})"
                )

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Image File", "", file_filter
        )
        if file_path:
            self.input_path_edit.setText(file_path)
            self.current_dir = None # Single file mode, so no current directory for refresh
            self.files_to_convert = [file_path] # This list will be used by update_file_list_display
            
            self.update_file_list_display() # Call the new method to update UI

            self.log_text.append(f"Selected file: {file_path}")

            # Set output directory to the input directory if not already set
            if not self.output_dir_set:
                self.output_dir_edit.setText(os.path.dirname(file_path))
                self.output_dir_set = True

            # Reset current_dir since we're working with a single file
            self.current_dir = None

    def select_input_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory")
        if dir_path:
            self.input_path_edit.setText(dir_path)
            self.current_dir = dir_path
            self.update_file_count() # This will call collect_files and then update_file_list_display
            self.log_text.append(f"Selected directory: {dir_path}")

            # Set output directory to the input directory if not already set
            if not self.output_dir_set:
                self.output_dir_edit.setText(dir_path)
                self.output_dir_set = True

    def update_file_count(self):
        """Update the count of files in the selected directory"""
        if not self.current_dir or self.is_processing:
            # Clear tree and label if no directory is selected or if processing
            if hasattr(self, 'file_tree_widget'): # Ensure widget exists
                self.file_tree_widget.clear()
            if hasattr(self, 'active_files_label'): # Ensure widget exists
                self.active_files_label.setText("0 files selected for conversion")
            self.convert_btn.setEnabled(False)
            self.files_processed_label.setText(f"0/0 files processed")
            return

        try:
            # Clear the tree before populating
            if hasattr(self, 'file_tree_widget'):
                self.file_tree_widget.clear()
            
            self.collect_files(self.current_dir, self.recursive_check.isChecked())
            
            if hasattr(self, 'file_tree_widget'): # Ensure widget exists
                self.file_tree_widget.clear() # Clear tree here before collect_files potentially adds to self.files_to_convert
            
            self.collect_files(self.current_dir, self.recursive_check.isChecked())
            
            # After collecting files, update the display which includes populating the tree
            self.update_file_list_display()

            # Log the update (count is now handled in update_file_list_display)
            # self.log_text.append(f"Updated file list: {len(self.files_to_convert)} image files found based on current selection.")
        except Exception as e:
            self.log_text.append(f"Error updating file count: {str(e)}")
            QMessageBox.critical(
                self, "Error", f"Failed to scan directory: {str(e)}"
            )

    def update_file_list_display(self):
        """Updates the file tree widget and related UI elements based on self.files_to_convert."""
        if not hasattr(self, 'file_tree_widget'): # Should not happen
            return
            
        self.file_tree_widget.clear()
        
        for file_path in self.files_to_convert: # Assumes self.files_to_convert is already set
            item = QTreeWidgetItem(self.file_tree_widget)
            item.setText(0, file_path)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked)

        count = len(self.files_to_convert)
        if hasattr(self, 'active_files_label'): # Ensure widget exists
            self.active_files_label.setText(f"{count} files selected for conversion")
        
        self.convert_btn.setEnabled(count > 0) # Enable button if files are present
        
        # Update the progress label denominator
        if count > 0:
             self.files_processed_label.setText(f"0/{count} files processed")
        else:
            self.files_processed_label.setText(f"0/0 files processed")
        
        # Log the number of files found and listed
        self.log_text.append(f"Displaying {count} files in the list.")
        
        # Initialize active file count label and convert button state
        self.update_active_file_count()


    def select_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Output Directory"
        )
        if dir_path:
            self.output_dir_edit.setText(dir_path)
            self.log_text.append(f"Output directory set to: {dir_path}")
            self.output_dir_set = True
            self.last_output_dir = dir_path  # Store the directory

    def collect_files(self, dir_path, recursive=True):
        self.files_to_convert = []
        selected_format = self.input_format_combo.currentText()
        
        if selected_format == "Auto-detect":
            # Use all extensions from SUPPORTED_INPUT_EXTENSIONS, already prepared in self.input_formats["Auto-detect"]
            # However, SUPPORTED_INPUT_EXTENSIONS is a tuple of strings like ('.jpg', '.png') which is what endswith() needs
            extensions_to_check = SUPPORTED_INPUT_EXTENSIONS 
        else:
            extensions_to_check = tuple(self.input_formats.get(selected_format, []))

        if not extensions_to_check: # Should not happen if self.input_formats is correctly populated
            self.log_text.append(f"Warning: No extensions found for format {selected_format}. Defaulting to all.")
            extensions_to_check = SUPPORTED_INPUT_EXTENSIONS

        try:
            if recursive:
                for root, _, files in os.walk(dir_path):
                    for file in files:
                        if file.lower().endswith(extensions_to_check):
                            # Normalize path
                            file_path = os.path.normpath(os.path.join(root, file))
                            self.files_to_convert.append(file_path)
            else:
                for file in os.listdir(dir_path):
                    if file.lower().endswith(extensions_to_check):
                        # Normalize path
                        file_path = os.path.normpath(os.path.join(dir_path, file))
                        self.files_to_convert.append(file_path)

            # Sort files for consistent display
            self.files_to_convert.sort()

        except Exception as e:
            self.log_text.append(f"Error collecting files: {str(e)}")
            QMessageBox.critical(
                self, "Error", f"Failed to scan directory: {str(e)}"
            )

    def start_conversion(self):
        output_dir = self.output_dir_edit.text()
        try:
            if not self.replace_files_check.isChecked():
                os.makedirs(output_dir, exist_ok=True)

            self.progress_bar.setValue(0)
            self.progress_label.setText("Converting...")
            self.convert_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)

            # Mark as processing - this locks the file list
            self.is_processing = True

            files_to_process = []
            root = self.file_tree_widget.invisibleRootItem()
            for i in range(root.childCount()):
                item = root.child(i)
                if item.checkState(0) == Qt.Checked:
                    files_to_process.append(item.text(0))
            
            total_files = len(files_to_process)

            if total_files == 0:
                QMessageBox.warning(self, "No Files Selected", "Please select at least one file to convert.")
                self.convert_btn.setEnabled(True) # Re-enable convert button
                self.cancel_btn.setEnabled(False)
                self.is_processing = False
                self.progress_label.setText("Ready")
                return

            self.log_text.append(f"Starting conversion for {total_files} selected files.")
            self.files_processed_label.setText(
                f"0/{total_files} files processed"
            )

            # Create and start worker
            self.converter = ImageConverter(
                files_to_process, # Pass the list of checked files
                self.format_combo.currentText(),
                output_dir,
                self.append_suffix_check.isChecked(),
                self.workers_spin.value(),
                self.replace_files_check.isChecked(),
                self.heic_quality_spin.value(),
            )

            self.converter.signals.progress.connect(self.update_progress)
            self.converter.signals.completed.connect(self.update_files_processed)
            self.converter.signals.finished.connect(self.conversion_finished)
            self.converter.signals.error.connect(self.show_error)
            self.converter.signals.log.connect(self.add_log)

            self.log_text.append(
                f"Starting conversion of {total_files} files to "
                f"{self.format_combo.currentText()} format"
            )
            QThreadPool.globalInstance().start(self.converter)
        except Exception as e:
            self.log_text.append(f"Error starting conversion: {str(e)}")
            QMessageBox.critical(
                self, "Error", f"Failed to start conversion: {str(e)}"
            )
            self.convert_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.is_processing = False

    def cancel_conversion(self):
        if self.converter:
            self.converter.cancel()
        self.cancel_btn.setEnabled(False)
        self.convert_btn.setEnabled(True)
        self.progress_label.setText("Conversion cancelled.")
        self.is_processing = False

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_files_processed(self, completed):
        total = len(self.files_to_convert)
        self.files_processed_label.setText(
            f"{completed}/{total} files processed"
        )

    def conversion_finished(self):
        self.progress_label.setText("Conversion completed")
        self.convert_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.log_text.append("Conversion process completed")

        # No longer processing - allow file count to update
        self.is_processing = False

        # Update the file count to reflect any changes during processing
        if self.current_dir:
            self.update_file_count()

        QMessageBox.information(
            self, "Success", "Image conversion completed successfully!"
        )

    def show_error(self, error_msg):
        self.log_text.append(f"ERROR: {error_msg}")

    def add_log(self, message):
        self.log_text.append(message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
