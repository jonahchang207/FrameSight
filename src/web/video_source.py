"""Buffered video / stream decoder.

Reads a *recorded or streamed* source (a file path, a direct media URL, or a
page URL resolved via yt-dlp) into a bounded look-ahead queue on a background
thread. The bounded queue is the smoothing buffer: it lets the player run at a
steady frame rate even when decode or inference hitch. It never captures the
local screen — the only inputs are decoded media.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

_DIRECT_MEDIA_SUFFIXES = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m3u8", ".ts", ".flv")


def _looks_like_url(source: str) -> bool:
    return "://" in source


def resolve_source(source: str) -> str:
    """Resolve a page URL (YouTube/Twitch/etc.) to a direct stream URL.

    Direct file paths and direct media URLs pass through unchanged. Page URLs
    are handed to yt-dlp when it's installed; if it isn't, we pass the URL to
    OpenCV/FFmpeg and let it try.
    """
    if not _looks_like_url(source):
        return source
    lowered = source.lower().split("?", 1)[0]
    if lowered.endswith(_DIRECT_MEDIA_SUFFIXES):
        return source
    try:
        import yt_dlp  # type: ignore
    except ImportError:
        print("yt-dlp not installed — passing URL straight to FFmpeg (may fail for "
              "site pages). Install with: pip install yt-dlp")
        return source
    opts = {"quiet": True, "no_warnings": True, "format": "best[ext=mp4]/best"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(source, download=False)
        if "url" in info:
            return info["url"]
        # Playlists / multi-format: take the first playable entry.
        entries = info.get("entries") or []
        if entries and "url" in entries[0]:
            return entries[0]["url"]
    return source


class BufferedVideoSource:
    def __init__(
        self,
        source: str,
        buffer_frames: int = 90,
        loop: bool = True,
        fps_override: Optional[float] = None,
    ) -> None:
        self._raw_source = source
        self._loop = loop
        self._fps_override = fps_override
        self._queue: "queue.Queue[Optional[np.ndarray]]" = queue.Queue(maxsize=buffer_frames)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cap: Optional[cv2.VideoCapture] = None
        self.fps: float = 30.0
        self.width: int = 0
        self.height: int = 0
        self.is_file = not _looks_like_url(source) and Path(source).exists()

    def open(self) -> None:
        resolved = resolve_source(self._raw_source)
        cap = cv2.VideoCapture(resolved)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open source: {self._raw_source}")
        self._cap = cap
        fps = cap.get(cv2.CAP_PROP_FPS)
        if self._fps_override:
            self.fps = float(self._fps_override)
        elif fps and 1.0 <= fps <= 240.0:
            self.fps = float(fps)
        else:
            self.fps = 30.0
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 0
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 0

    def start(self) -> None:
        if self._cap is None:
            self.open()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        assert self._cap is not None
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if not ok:
                # End of file/stream. Loop files; end streams.
                if self._loop and self.is_file:
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                self._put(None)  # sentinel: source ended
                return
            self._put(frame)

    def _put(self, item: Optional[np.ndarray]) -> None:
        # Block (with periodic stop checks) so we never drop frames or busy-spin;
        # the bounded queue throttles decode to the player's consumption rate.
        while not self._stop.is_set():
            try:
                self._queue.put(item, timeout=0.1)
                return
            except queue.Full:
                continue

    def read(self, timeout: float = 0.5) -> Optional[np.ndarray]:
        """Return the next frame, or None when the source has ended."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return np.empty(0)  # transient: nothing buffered yet, try again

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None
