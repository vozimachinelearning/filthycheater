# Screen Solver

A simple Tkinter application that captures a region of your screen, extracts text using Tesseract OCR, and uses Ollama (via LangChain) to provide a solution or suggestion. Ideal for coding challenges or technical interviews.

## Prerequisites

1.  **System Packages**:
    - `tesseract-ocr`: Required for text extraction.
      ```bash
      sudo apt install tesseract-ocr
      # On macOS: brew install tesseract
      # On Windows: Download installer from https://github.com/UB-Mannheim/tesseract/wiki
      ```
    - `python3-tk`: (Usually included, but if you get a Tkinter error)
      ```bash
      sudo apt install python3-tk
      ```

2.  **Ollama**:
    - Ensure Ollama is installed and running.
    - Pull the model you want to use (default is `llama3`):
      ```bash
      ollama pull llama3
      ```

## Setup

1.  Create a virtual environment (already done if you used the assistant):
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

## Running the App

Run the helper script:

```bash
./run.sh
```

Or manually:

```bash
source venv/bin/activate
python main.py
```

## Usage

1.  Enter the **Ollama Model** name (default: `llama3`) in the configuration box.
2.  Click **Capture & Solve**.
3.  The screen will dim. Click and drag to select the area containing the question/code.
4.  The app will process the image and display the extracted text and the AI's suggestion.
# filthycheater
# filthycheater
