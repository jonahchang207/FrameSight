"""Buffered video / stream decoder with seek + pause support.

Reads a *recorded or streamed* source (a file path, a direct media URL, or a
page URL resolved via yt-dlp) into a bounded look-ahead queue on a background
thread. The bounded queue is the smoothing buffer: it lets the player run at a
steady frame rate even when decode or inference hitch. It never captures the
local screen — the only inputs are decoded media.

Queue items are ``(frame_index, frame)`` tuples so the player can report an
accurate scrub position. ``read()`` returns ``ENDED`` when the source is
finished and ``None`` for a transient empty (caller should retry).
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Optional, Tuple, Union

import cv2
import numpy as np

_DIRECT_MEDIA_SUFFIXES = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m3u8", ".ts", ".flv")

ENDED = object()  # sentinel: source finished
FrameItem = Tuple[int, np.ndarray]


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
        self.source_path = source
        self._raw_source = source
        self._loop = loop
        self._fps_override = fps_override
        self._queue: "queue.Queue[Union[FrameItem, object]]" = queue.Queue(maxsize=buffer_frames)
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cap: Optional[cv2.VideoCapture] = None

        self._seek_lock = threading.Lock()
        self._seek_target: Optional[int] = None
        self._decode_idx = 0

        self.fps: float = 30.0
        self.width: int = 0
        self.height: int = 0
        self.frame_count: int = 0
        self.is_file = not _looks_like_url(source) and Path(source).exists()
        self.seekable = False

    # -- setup -------------------------------------------------------------
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
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.frame_count = count if count > 0 else 0
        # Only files with a known length support meaningful scrubbing.
        self.seekable = self.is_file and self.frame_count > 0

    def start(self) -> None:
        if self._cap is None:
            self.open()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # -- controls ----------------------------------------------------------
    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def seek_fraction(self, fraction: float) -> None:
        if not self.seekable:
            return
        fraction = max(0.0, min(1.0, float(fraction)))
        target = int(fraction * max(0, self.frame_count - 1))
        with self._seek_lock:
            self._seek_target = target

    # -- decode loop -------------------------------------------------------
    def _run(self) -> None:
        assert self._cap is not None
        while not self._stop.is_set():
            target = self._take_seek_target()
            if target is not None:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, target)
                self._flush_queue()
                self._decode_idx = target
                # Emit exactly one frame at the new position so a paused player
                # can show where the user scrubbed to.
                if not self._read_and_put():
                    return
                continue

            if self._paused.is_set():
                # Don't decode ahead while paused — keeps the buffer from
                # bursting on resume and lets pause actually pause.
                self._stop.wait(0.03)
                continue

            if not self._read_and_put():
                return

    def _read_and_put(self) -> bool:
        """Read one frame and enqueue it. Returns False if the loop should end."""
        assert self._cap is not None
        ok, frame = self._cap.read()
        if not ok:
            if self._loop and self.is_file:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self._decode_idx = 0
                return True
            self._put(ENDED)
            return False
        idx = self._decode_idx
        self._decode_idx += 1
        self._put((idx, frame))
        return True

    def _take_seek_target(self) -> Optional[int]:
        with self._seek_lock:
            target = self._seek_target
            self._seek_target = None
            return target

    def _flush_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def _put(self, item: Union[FrameItem, object]) -> None:
        while not self._stop.is_set():
            try:
                self._queue.put(item, timeout=0.1)
                return
            except queue.Full:
                # A pending seek invalidates buffered frames — drop them so the
                # new position isn't stuck behind a full queue.
                with self._seek_lock:
                    if self._seek_target is not None:
                        self._flush_queue()

    # -- consume -----------------------------------------------------------
    def read(self, timeout: float = 0.5) -> Union[FrameItem, object, None]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None  # transient: nothing buffered yet

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None
