# Image Format Converter

A simple GUI application to convert images between various formats (JPG, PNG, BMP, TIFF, WEBP, HEIC).

## Features

*   Convert single images or entire directories.
*   Supports recursive directory processing.
*   Choose output format.
*   Option to append a suffix to converted filenames.
*   Adjust HEIC quality.
*   Parallel processing for faster conversion.

## Installation
Windows installer available from releases page:
[Release 0.1.0](https://github.com/Tim-Tadj/Image-Format-Converter/releases/tag/v0.1.0)


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

4.  Build the application using `cx_Freeze`:
    ```bash
    python setup.py build
    ```
    The appliaction will be located in the `build` directory.

    Or, to create an executable:

    ```bash
    python setup.py bdist_msi #for windows
    ```
    
    The installer will be located in the `dist` directory.
