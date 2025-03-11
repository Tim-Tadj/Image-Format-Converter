import sys
from cx_Freeze import setup, Executable

# Define build options with optimized includes and excludes
build_exe_options = {
    "packages": [
        "os",
        "PIL",
        "cv2",
        "pillow_heif",
        "PySide6.QtWidgets",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "numpy",
        "numpy.linalg",
        "numpy.fft",
        "numpy.random",
    ],
    "excludes": [
        "PySide6.Qt3D",
        "PySide6.QtMultimedia",
        "PySide6.QtNetwork",
        "PySide6.QtSql",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "tkinter",
        "psutil",
        "setuptools",
        "wheel",
        "unittest",
        "pydoc_data",
        "__pycache__",
        "tcl8",
        "tk8.6",
        "lib2to3",
        "test",
        "html",
        "xml",
        "xmlrpc",
        "http",
        "email",
        "asyncio",
        "curses",
        "bz2",
        "lzma"

    ],
    "include_files": [],
    "optimize": 2,
}


# Determine the base for GUI application on Windows
base = None
if sys.platform == "win32":
    base = "Win32GUI"

# Define the executable
exe = Executable(
    script="img_convert_gui.py",
    base=base,
    icon=None 
)

# Setup the application
setup(
    name="ImageFormatConverter",
    version="0.1",
    description="Image Format Converter",
    options={"build_exe": build_exe_options},
    executables=[exe]
)
