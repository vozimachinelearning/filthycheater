"""Main logic for Screen Reader & Solver (PyQt5 version).

This file wires the GUI (in `ui.py`) with the background logic (screenshot, OCR, LLM).
"""
import sys
import os
import threading
import re
import time
import pytesseract
from PIL import Image
import mss
from langchain_ollama import ChatOllama

# Windows-specific Tesseract configuration
if os.name == 'nt':
    # Common default installation paths for Tesseract on Windows
    _tesseract_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Tesseract-OCR\tesseract.exe"),
    ]
    for _path in _tesseract_paths:
        if os.path.exists(_path):
            pytesseract.pytesseract.tesseract_cmd = _path
            break

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from pynput import keyboard, mouse
from PyQt5 import QtWidgets
from ui import MainWindow


class Controller:
    def __init__(self, gui: MainWindow):
        self.gui = gui
        self._capture_lock = threading.Lock()
        self._last_response = ""  # Store last AI response for typing

        # Keyboard controller for typing
        self._keyboard_controller = keyboard.Controller()

        # Debounced right-only exit timer (distinguish right-only vs left+right chord)
        self._right_exit_timer = None
        self._right_debounce = 0.14  # seconds

        # Debounced left-only toggle timer (distinguish left-only vs left+right chord)
        self._left_toggle_timer = None
        self._left_debounce = 0.14  # seconds

        # Wire GUI signals
        self.gui.captureRequested.connect(self._on_capture_requested)

        # Hotkey listener state
        self._pressed = set()
        self._hotkey_active = False
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()

        # Mouse listener for middle click typing
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._mouse_listener.daemon = True
        self._mouse_listener.start()

    def _apply_right_exit(self):
        # Timer callback to perform a right-only exit if not canceled
        with self._capture_lock:
            self._right_exit_timer = None
            try:
                QtWidgets.QApplication.quit()
            except Exception:
                # fallback
                os._exit(0)

    def _apply_left_toggle(self):
        # Timer callback to toggle visibility if not canceled
        with self._capture_lock:
            self._left_toggle_timer = None
            try:
                self.gui.toggle_visible()
            except Exception:
                pass

    def _on_press(self, key):
        try:
            # Add key to pressed set
            if key in (keyboard.Key.left, keyboard.Key.right):
                self._pressed.add(key)

            # Up / Down scroll handling
            if key == keyboard.Key.up:
                self.gui.scrollRequested.emit(-1)
            elif key == keyboard.Key.down:
                self.gui.scrollRequested.emit(1)

            # If right pressed alone (no left currently down), start debounce to distinguish chord
            if key == keyboard.Key.right and keyboard.Key.left not in self._pressed:
                # Cancel any existing exit timer first
                if self._right_exit_timer:
                    try:
                        self._right_exit_timer.cancel()
                    except Exception:
                        pass
                # Start a short timer; if left is pressed before it fires we'll cancel it
                self._right_exit_timer = threading.Timer(self._right_debounce, self._apply_right_exit)
                self._right_exit_timer.daemon = True
                self._right_exit_timer.start()

            # If left pressed alone (no right currently down), start debounce to distinguish chord
            if key == keyboard.Key.left and keyboard.Key.right not in self._pressed:
                # Cancel any existing toggle timer first
                if self._left_toggle_timer:
                    try:
                        self._left_toggle_timer.cancel()
                    except Exception:
                        pass
                # Start a short timer; if right is pressed before it fires we'll cancel it
                self._left_toggle_timer = threading.Timer(self._left_debounce, self._apply_left_toggle)
                self._left_toggle_timer.daemon = True
                self._left_toggle_timer.start()

        except Exception:
            pass

        # Detect left+right chord: if both present, cancel right-only exit timer and handle chord
        if keyboard.Key.left in self._pressed and keyboard.Key.right in self._pressed and not self._hotkey_active:
            # Cancel pending right-only exit timer if any
            if self._right_exit_timer:
                try:
                    self._right_exit_timer.cancel()
                except Exception:
                    pass
                self._right_exit_timer = None

            # Cancel pending left-only toggle timer if any
            if self._left_toggle_timer:
                try:
                    self._left_toggle_timer.cancel()
                except Exception:
                    pass
                self._left_toggle_timer = None

            self._hotkey_active = True
            # emit capture on GUI main thread (start a clean loop)
            self.gui.captureRequested.emit()

    def _on_release(self, key):
        try:
            if key in (keyboard.Key.left, keyboard.Key.right):
                self._pressed.discard(key)
        except Exception:
            pass
        if not (keyboard.Key.left in self._pressed and keyboard.Key.right in self._pressed):
            self._hotkey_active = False

    def _on_capture_requested(self):
        # Read the model from GUI in main thread, then start background capture
        if self._capture_lock.locked():
            return
        model_name = os.environ.get("OLLAMA_MODEL", "relational/orbis-coding:latest")
        print(f"[capture] requested model={model_name}", flush=True)
        threading.Thread(target=self._capture_and_process, args=(model_name,), daemon=True).start()

    def _capture_and_process(self, model_name: str):
        with self._capture_lock:
            try:
                start_ts = time.monotonic()
                print("[capture] begin", flush=True)
                # Disable GUI
                self.gui.set_enabled(False)

                # 1) Hide overlay, ensure it's hidden, then capture full screen
                try:
                    self.gui.set_visible(False)
                except Exception:
                    pass
                time.sleep(0.08)

                with mss.mss() as sct:
                    monitor = sct.monitors[0]
                    sct_img = sct.grab(monitor)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                print(f"[capture] screenshot captured {sct_img.size} in {time.monotonic() - start_ts:.3f}s", flush=True)

                # Restore overlay visibility before doing any UI updates
                try:
                    self.gui.set_visible(True)
                except Exception:
                    pass
                print("[capture] overlay restored", flush=True)

                # 2) OCR
                ocr_start = time.monotonic()
                extracted_text = pytesseract.image_to_string(img)
                ocr_elapsed = time.monotonic() - ocr_start
                print(f"[ocr] done len={len(extracted_text)} in {ocr_elapsed:.3f}s", flush=True)

                if not extracted_text.strip():
                    # Only show final message (no OCR content or status)
                    print("[ocr] empty text detected", flush=True)
                    self.gui.append_text("No suggestion (no text detected).\n\n---\n")
                    return

                # 3) AI Processing
                try:
                    llm_start = time.monotonic()
                    print("[llm] creating client", flush=True)
                    # Instantiate a fresh LLM client and attempt resets if needed to avoid persisted context
                    try:
                        # Preferred: pass reset=True if constructor supports it
                        llm = ChatOllama(model=model_name, reset=True)
                    except TypeError:
                        # Fallback: normal construction
                        llm = ChatOllama(model=model_name)
                    print(f"[llm] client ready in {time.monotonic() - llm_start:.3f}s", flush=True)

                    # Aggressively try to clear any server/client-side state before each run
                    try:
                        # Try common reset methods on the llm object
                        for method_name in ("reset", "clear", "reset_session"):
                            meth = getattr(llm, method_name, None)
                            if callable(meth):
                                try:
                                    meth()
                                    break
                                except Exception:
                                    pass
                        # Try client.reset() if present
                        client_obj = getattr(llm, "client", None)
                        if client_obj is not None:
                            reset_fn = getattr(client_obj, "reset", None)
                            if callable(reset_fn):
                                try:
                                    reset_fn()
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    print("[llm] reset attempts complete", flush=True)

                    base_sys = ("IGNORE any previous conversation context. Treat this input as a NEW, independent problem — do not use prior messages or history in your reasoning. You are an expert software engineer helper. You will be given text extracted from a screen, which is likely a coding challenge, an interview question, or a technical error. Provide a concise, clear, and correct solution or suggestion. If code is required, provide it. Do not be chatty.")

                    prompt = ChatPromptTemplate.from_messages([
                        ("system", base_sys),
                        ("user", "{text}")
                    ])

                    user_payload = extracted_text

                    chain = prompt | llm | StrOutputParser()
                    invoke_start = time.monotonic()
                    print(f"[llm] invoke start payload_len={len(user_payload)}", flush=True)
                    response = chain.invoke({"text": user_payload})
                    invoke_elapsed = time.monotonic() - invoke_start
                    print(f"[llm] invoke done response_len={len(response)} in {invoke_elapsed:.3f}s", flush=True)
                    
                    # Store response for potential typing
                    self._last_response = response

                    # Only append the final AI response (no OCR or status)
                    print(f"[main] emitting append_text signal with len={len(response)}")
                    self.gui.append_text(response + "\n\n---\n")
                    print(f"[main] append_text signal emitted")
                    print(f"[capture] complete in {time.monotonic() - start_ts:.3f}s", flush=True)
                except Exception as e:
                    print(f"[llm] error {e}", flush=True)
                    self.gui.append_text(f"AI Error: {e}\n")

            except Exception as e:
                print(f"[capture] error {e}", flush=True)
                self.gui.append_text(f"Error: {e}\n")
            finally:
                self.gui.set_enabled(True)

    def stop(self):
        try:
            if self._listener:
                self._listener.stop()
            if self._mouse_listener:
                self._mouse_listener.stop()
        except Exception:
            pass

    def _on_click(self, x, y, button, pressed):
        """Handle mouse clicks to trigger typing."""
        if not pressed:
            return
        
        if button == mouse.Button.middle:
            # Run typing in a separate thread to avoid blocking the listener
            threading.Thread(target=self._type_last_code, daemon=True).start()

    def _type_last_code(self):
        """Extracts code blocks from the last response and types them."""
        # Use a local copy to avoid race conditions if response changes mid-typing
        # (though likely user won't trigger capture while typing)
        text = self._last_response
        print(f"[typing] requested. text_len={len(text)}", flush=True)
        if not text:
            print("[typing] no text available", flush=True)
            return

        # Extract code blocks between triple backticks
        # Supports ```python ... ``` or just ``` ... ```
        code_blocks = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
        
        if not code_blocks:
            # If no code blocks found, do nothing (as per "write just the code")
            # Alternatively, if we wanted to be more flexible, we could check if the whole text looks like code.
            # But strict adherence: ignore explanations -> implies we need to separate code from text.
            print("[typing] no code blocks found", flush=True)
            return
            
        # Join multiple blocks with newlines
        code_to_type = "\n\n".join(code_blocks)
        
        if not code_to_type.strip():
            print("[typing] code blocks empty", flush=True)
            return

        print(f"[typing] typing {len(code_to_type)} chars...", flush=True)
        print(f"[typing] content preview: {code_to_type[:50]!r}", flush=True)
        
        # Small delay to ensure the user has released the mouse or focused the target window
        time.sleep(0.5)
        
        try:
            self._keyboard_controller.type(code_to_type)
            print("[typing] done", flush=True)
        except Exception as e:
            print(f"[typing] error: {e}", flush=True)



def main():
    app = QtWidgets.QApplication(sys.argv)
    gui = MainWindow()
    ctrl = Controller(gui)

    # Ensure we stop background listeners on quit
    app.aboutToQuit.connect(ctrl.stop)

    gui.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
