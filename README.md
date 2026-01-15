# Image Format Converter

A simple GUI application to convert images between various formats (JPG, PNG, BMP, TIFF, WEBP, HEIC).

## Features

*   Convert single images or entire directories.
*   Supports recursive directory processing.
*   Choose output format.
*   Option to append a suffix to converted filenames.
*   Adjust HEIC quality.
*   Parallel processing for faster conversion.
*   Select input format: Choose a specific input format (e.g., JPG, PNG) or use 'Auto-detect'.
*   File selection tree: View and manage the list of files to be converted using a tree with checkboxes. Allows for individual file selection/deselection from a directory scan.

## Installation
Windows installer available from the releases page:
https://github.com/Tim-Tadj/Image-Format-Converter/releases


## Build Instructions

This project uses [uv](https://astral.sh/blog/uv) as the Python project manager. To build the application, follow these steps:

1.  Install uv:
    ```bash
    pip install uv
    ```
2.  Create virtual environment:
    ```bash
    uv venv
    ```
3.  Activate virtual environment:
    ```bash
    .\.venv\Scripts\activate  # On Windows
    source ./.venv/bin/activate # On Linux/macOS
    ```
4.  Install dependencies:
    ```bash
    uv sync
    ```
5.  Build the application using `cx_Freeze` (pyproject.toml config):
    ```bash
    cxfreeze build
    ```
    The application will be located in the `build` directory.

    Or, to create an installer:

    ```bash
    cxfreeze bdist_msi  # Windows only
    ```

    The installer will be located in the `dist` directory.
