import markdown
from PyQt5 import QtWidgets, QtCore, QtGui


class MainWindow(QtWidgets.QWidget):
    """PyQt5 GUI for Screen Reader & Solver.

    Signals:
      - captureRequested: emitted by the controller when hotkey presses are detected
      - append_text_signal(str): used by background threads to append text to the output
      - scrollRequested(int): request scroll (-1 up, +1 down)
      - set_enabled_signal(bool): enable/disable the overlay while processing
    """
    captureRequested = QtCore.pyqtSignal()
    append_text_signal = QtCore.pyqtSignal(str)
    scrollRequested = QtCore.pyqtSignal(int)
    set_enabled_signal = QtCore.pyqtSignal(bool)
    set_visible_signal = QtCore.pyqtSignal(bool)
    toggle_visible_signal = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Screen Reader & Solver")
        self.resize(360, 240)
        self.setWindowOpacity(0.85)
        # Frameless so no title bar; stays on top
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.FramelessWindowHint)

        # Layout (minimal margins so content can use maximum space)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # Minimal Output-only UI (no settings / buttons) — dark theme
        self.setStyleSheet("""
            QWidget { background-color: #121212; color: #e0e0e0; }
            QGroupBox { border: none; }
            QTextEdit { background-color: #1e1e1e; color: #e6e6e6; border: 1px solid #333; padding: 6px; }
            QLabel { color: #e0e0e0; }
            /* Markdown Styles */
            h1, h2, h3, h4, h5, h6 { color: #ffffff; font-weight: bold; margin-top: 10px; margin-bottom: 5px; }
            code { background-color: #2b2b2b; color: #a9b7c6; font-family: Consolas, monospace; padding: 2px; border-radius: 3px; }
            pre { background-color: #2b2b2b; color: #a9b7c6; font-family: Consolas, monospace; padding: 10px; margin: 5px 0; border-radius: 5px; white-space: pre-wrap; }
            a { color: #5294e2; text-decoration: none; }
            blockquote { border-left: 3px solid #5294e2; padding-left: 10px; color: #a0a0a0; }
        """)

        # Output (no scrollbars; wrapped; auto-resizes to content)
        self.output = QtWidgets.QTextEdit()
        self.output.setReadOnly(True)
        self.output.setFontFamily("Consolas")
        # Wrap anywhere to prevent horizontal overflow
        self.output.setWordWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
        # disallow selection/copy/paste
        self.output.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
        # hide scrollbars (we will scroll programmatically)
        self.output.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.output.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        # start with a constrained width; height will adjust as text arrives
        self.output.setFixedWidth(360)
        self.output.setFixedHeight(100)
        layout.addWidget(self.output, 1)

        # Make the window ignore mouse events (click-through overlay)
        # Use both WA_TransparentForMouseEvents and WindowTransparentForInput to maximize click-through compatibility
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        try:
            # Qt.WindowTransparentForInput available on newer Qt5 builds
            self.setWindowFlag(QtCore.Qt.WindowTransparentForInput, True)
        except Exception:
            pass

        # Connect signals
        self.append_text_signal.connect(self._append_text)
        self.scrollRequested.connect(self._on_scroll)
        self.set_enabled_signal.connect(self._set_enabled)
        self.set_visible_signal.connect(self._set_visible)
        self.toggle_visible_signal.connect(self._toggle_visible)

    def _position_top_right(self):
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        w, h = self.width(), self.height()
        x = screen.right() - w - 20
        y = screen.top() + 20
        self.move(x, y)

    # Slots
    def _append_text(self, text: str):
        print(f"[ui] _append_text received len={len(text)}")
        self.output.moveCursor(QtGui.QTextCursor.End)
        
        # Convert Markdown to HTML
        try:
            # extensions:
            # - fenced_code: supports ```code``` blocks
            # - codehilite: syntax highlighting (requires pygments)
            # - tables: supports tables
            html = markdown.markdown(
                text, 
                extensions=['fenced_code', 'codehilite', 'tables'],
                extension_configs={
                    'codehilite': {
                        'noclasses': True,  # Use inline styles
                        'pygments_style': 'monokai' # Dark theme friendly
                    }
                }
            )
            # Insert HTML
            # Force pre-wrap style inline to ensure PyQt respects it
            html = html.replace("<pre>", "<pre style='white-space: pre-wrap;'>")
            self.output.insertHtml(html)
            # Ensure a newline block after
            self.output.insertPlainText("\n")
            print("[ui] text inserted successfully")
        except Exception as e:
            # Fallback
            self.output.insertPlainText(text)
            print(f"[ui] Markdown error: {e}")

        self.output.moveCursor(QtGui.QTextCursor.End)
        # Resize to fit content on next event loop iteration
        QtCore.QTimer.singleShot(0, self._adjust_size)

    def _set_enabled(self, enabled: bool):
        # disable the whole window while processing (no buttons to toggle)
        self.setDisabled(not enabled)

    def _on_scroll(self, direction: int):
        """Scroll the output by direction: -1 up, +1 down."""
        sb = self.output.verticalScrollBar()
        if not sb:
            return
        # Use a page fraction for smoother scrolling
        step = max(1, int(sb.pageStep() * 0.15))
        new = sb.value() + direction * step
        new = max(0, min(new, sb.maximum()))
        sb.setValue(new)

    def _adjust_size(self):
        print("[ui] _adjust_size start")
        # Compute sensible width first, then set text width and measure height.
        doc = self.output.document()
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        
        # Constraints
        min_w = 300
        # Allow up to 75% of screen width
        max_w = int(screen.width() * 0.75)
        padding = 32  # margins + borders + scrollbar-space

        # 1. Measure "Ideal" Width (unbounded)
        # This captures the natural width of long code lines.
        # For paragraphs, it might return a huge width (one long line), which we clamp later.
        doc.setTextWidth(10000) 
        ideal_w = doc.idealWidth()

        # 2. Determine Initial Target Width
        # Clamp to max_w. Ensure at least min_w.
        target_w = max(min_w, min(ideal_w + padding, max_w))
        
        # 3. Apply and Measure Height
        doc.setTextWidth(max(target_w - padding, 50))
        doc.adjustSize()
        doc_height = int(doc.size().height()) + padding
        
        # 4. Aspect Ratio Check (Prevent Tall/Skinny windows)
        # If the content wrapped (e.g. long paragraph) and made the window very tall,
        # we should widen the window to reduce height, up to max_w.
        # Check if Height > Width (Portrait) and we have room to grow.
        if doc_height > target_w and target_w < max_w:
            # Try to aim for a squarer aspect or 4:3
            # Simple heuristic: widen by 50% or until max
            new_w = min(max_w, int(target_w * 1.5))
            
            # Re-measure
            doc.setTextWidth(max(new_w - padding, 50))
            doc.adjustSize()
            new_h = int(doc.size().height()) + padding
            
            # If the new height is significantly better (shorter), keep the wider width.
            # (Sometimes widening doesn't help much if it's just a few very long items, but usually it does).
            target_w = new_w
            doc_height = new_h

        # 5. Final Height Constraint
        max_h = screen.height() - 80
        desired_h = min(max(doc_height, 40), max_h)

        # Apply sizes
        self.output.setFixedWidth(int(target_w))
        self.output.setFixedHeight(desired_h)

        # Resize overall window to fit content (minimal extra padding)
        total_h = desired_h + 8
        total_w = int(target_w) + 8
        self.setFixedSize(total_w, total_h)
        self._position_top_right()
        print(f"[ui] resized to {total_w}x{total_h}")


    # Convenience methods for external callers
    def append_text(self, text: str):
        self.append_text_signal.emit(text)

    def set_enabled(self, enabled: bool):
        self.set_enabled_signal.emit(enabled)

    def set_visible(self, visible: bool):
        """Set visibility of the overlay from other threads safely."""
        self.set_visible_signal.emit(visible)

    def _set_visible(self, visible: bool):
        self.setVisible(bool(visible))

    def _toggle_visible(self):
        self.setVisible(not self.isVisible())

    def toggle_visible(self):
        """Toggle visibility of the overlay from other threads safely."""
        self.toggle_visible_signal.emit()

