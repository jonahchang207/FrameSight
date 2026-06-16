"""Localhost video/stream annotation dashboard.

Decodes a video file or stream URL (never a live grab of your own screen),
runs the FrameSight detector, and renders the annotated overlay in the browser
with live, editable settings. No forward/velocity prediction — boxes are the
latest detection drawn on the current frame, so this is a review/understanding
tool for recorded or streamed content, not a real-time capture overlay.
"""
