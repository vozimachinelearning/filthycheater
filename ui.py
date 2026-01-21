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
        """)

        # Output (no scrollbars; wrapped; auto-resizes to content)
        self.output = QtWidgets.QTextEdit()
        self.output.setReadOnly(True)
        self.output.setFontFamily("Consolas")
        self.output.setWordWrapMode(QtGui.QTextOption.WordWrap)
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

    def _position_top_right(self):
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        w, h = self.width(), self.height()
        x = screen.right() - w - 20
        y = screen.top() + 20
        self.move(x, y)

    # Slots
    def _append_text(self, text: str):
        self.output.moveCursor(QtGui.QTextCursor.End)
        self.output.insertPlainText(text)
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
        # Compute sensible width first, then set text width and measure height.
        doc = self.output.document()
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        min_w = 240
        max_w = int(screen.width() * 0.6)

        # Start with current width or a reasonable default
        start_w = max(self.output.width(), 360)
        start_w = max(min_w, min(start_w, max_w))

        padding = 16
        # One-pass attempt: set doc text width and measure height
        doc.setTextWidth(max(start_w - padding, 50))
        doc.adjustSize()
        doc_height = int(doc.size().height()) + padding

        # If the document is taller than max_h and we can increase width, try widening once to reduce height
        max_h = screen.height() - 80
        if doc_height > max_h and start_w < max_w:
            wider = min(max_w, start_w + 240)
            doc.setTextWidth(max(wider - padding, 50))
            doc.adjustSize()
            doc_height = int(doc.size().height()) + padding
            start_w = wider

        desired_h = min(max(doc_height, 40), max_h)

        # Apply sizes
        self.output.setFixedWidth(start_w)
        self.output.setFixedHeight(desired_h)

        # Resize overall window to fit content (minimal extra padding)
        total_h = desired_h + 8
        total_w = start_w + 8
        self.setFixedSize(total_w, total_h)
        self._position_top_right()


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
