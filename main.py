"""Main logic for Screen Reader & Solver (PyQt5 version).

This file wires the GUI (in `ui.py`) with the background logic (screenshot, OCR, LLM).
"""
import sys
import os
import threading
import pytesseract
from PIL import Image
import mss
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from pynput import keyboard
from PyQt5 import QtWidgets
from ui import MainWindow


class Controller:
    def __init__(self, gui: MainWindow):
        self.gui = gui
        self._capture_lock = threading.Lock()

        # Debounced right-only exit timer (distinguish right-only vs left+right chord)
        self._right_exit_timer = None
        self._right_debounce = 0.14  # seconds

        # Wire GUI signals
        self.gui.captureRequested.connect(self._on_capture_requested)

        # Hotkey listener state
        self._pressed = set()
        self._hotkey_active = False
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()

    def _apply_right_exit(self):
        # Timer callback to perform a right-only exit if not canceled
        with self._capture_lock:
            self._right_exit_timer = None
            try:
                QtWidgets.QApplication.quit()
            except Exception:
                # fallback
                os._exit(0)

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
        model_name = os.environ.get("OLLAMA_MODEL", "ministral-3:3b")
        threading.Thread(target=self._capture_and_process, args=(model_name,), daemon=True).start()

    def _capture_and_process(self, model_name: str):
        with self._capture_lock:
            try:
                # Disable GUI
                self.gui.set_enabled(False)

                # 1) Hide overlay, ensure it's hidden, then capture full screen
                try:
                    self.gui.set_visible(False)
                except Exception:
                    pass
                # small delay to allow window to become invisible to the compositor
                import time
                time.sleep(0.08)

                with mss.mss() as sct:
                    monitor = sct.monitors[0]
                    sct_img = sct.grab(monitor)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

                # Restore overlay visibility before doing any UI updates
                try:
                    self.gui.set_visible(True)
                except Exception:
                    pass

                # 2) OCR
                extracted_text = pytesseract.image_to_string(img)

                if not extracted_text.strip():
                    # Only show final message (no OCR content or status)
                    self.gui.append_text("No suggestion (no text detected).\n" + "=" * 40 + "\n")
                    return

                # 3) AI Processing
                try:
                    # Instantiate a fresh LLM client and attempt resets if needed to avoid persisted context
                    try:
                        # Preferred: pass reset=True if constructor supports it
                        llm = ChatOllama(model=model_name, reset=True)
                    except TypeError:
                        # Fallback: normal construction
                        llm = ChatOllama(model=model_name)

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

                    base_sys = ("IGNORE any previous conversation context. Treat this input as a NEW, independent problem — do not use prior messages or history in your reasoning. You are an expert software engineer helper. You will be given text extracted from a screen, which is likely a coding challenge, an interview question, or a technical error. Provide a concise, clear, and correct solution or suggestion. If code is required, provide it. Do not be chatty.")

                    prompt = ChatPromptTemplate.from_messages([
                        ("system", base_sys),
                        ("user", "{text}")
                    ])

                    user_payload = extracted_text

                    chain = prompt | llm | StrOutputParser()
                    response = chain.invoke({"text": user_payload})
                    # Only append the final AI response (no OCR or status)
                    self.gui.append_text(response + "\n" + "=" * 40 + "\n")
                except Exception as e:
                    self.gui.append_text(f"AI Error: {e}\n")

            except Exception as e:
                self.gui.append_text(f"Error: {e}\n")
            finally:
                self.gui.set_enabled(True)

    def stop(self):
        try:
            if self._listener:
                self._listener.stop()
        except Exception:
            pass


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
