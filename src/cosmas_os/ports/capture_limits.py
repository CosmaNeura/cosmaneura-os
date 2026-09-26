"""Supported protocol 1.0 wire limits; Scribe owns reservation authority.

Current Scribe supports 2048 chunks and 384 MiB. A legacy 1000-chunk
capability receipt retains its 64 MiB budget; visit profiles stay explicit.
"""

MAX_CAPTURE_CHUNKS = 2048
MAX_CAPTURE_PLAINTEXT_BYTES = 384 * 1024 * 1024
LEGACY_CAPTURE_PLAINTEXT_BYTES = 64 * 1024 * 1024
