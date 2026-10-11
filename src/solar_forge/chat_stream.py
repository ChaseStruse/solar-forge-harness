"""Batch worker-thread text chunks into bounded-rate terminal updates."""
from threading import Lock


class StreamDisplay:
    def __init__(self, loop, append, interval=0.05):
        self.loop, self.append, self.interval = loop, append, interval
        self.lock = Lock()
        self.chunks = []
        self.scheduled = False
        self.closed = False
        self.handle = None

    def push(self, chunk):
        with self.lock:
            if self.closed:
                return
            self.chunks.append(chunk)
            if self.scheduled:
                return
            self.scheduled = True
        self.loop.call_soon_threadsafe(self._schedule)

    def _schedule(self):
        if not self.closed:
            self.handle = self.loop.call_later(self.interval, self._flush)

    def _flush(self):
        self.handle = None
        with self.lock:
            if self.closed:
                return
            text = ''.join(self.chunks)
            self.chunks.clear()
            self.scheduled = False
        if text:
            self.append(text)

    def close(self):
        """The saved response replaces the preview; discard late UI callbacks."""
        with self.lock:
            self.closed = True
            self.chunks.clear()
        if self.handle:
            self.handle.cancel()
            self.handle = None
