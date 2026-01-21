#!/bin/bash

# Check if tesseract is installed
if ! command -v tesseract &> /dev/null
then
    echo "Error: tesseract is not installed."
    echo "Please install it using: sudo apt install tesseract-ocr"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Run the application
python main.py
