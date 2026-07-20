"""
Prefetch module for SABRE Nonlinear Buffering.

Decides *when* and *where* to prefetch based on:
- A JSON config that lists target segment indices and a buffer-level threshold

Bitrate / quality selection is delegated to the ABR algorithm via the standard
``abr.get_quality_delay(segment_index)`` interface.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Dummy prefetch module that will be replaced with RL prefetch module.
class PrefetchModule:
    """Config-driven prefetch scheduler.

    Parameters
    ----------
    config_path : str | Path
        Path to a JSON file with the format::

            {
              "buffer_level_threshold": 20000,
              "prefetch": [
                {"segment": 5},
                {"segment": 10},
                {"segment": 15}
              ]
            }

        ``buffer_level_threshold`` is the minimum buffer level (in ms)
        required before a prefetch download is triggered (``should_prefetch``
        uses ``buffer_level_ms > threshold``). Verbose logs print
        ``bl=<before>-><after>``: *before* is the level when the prefetch
        download **starts** (must exceed the threshold); *after* is the
        level once the download completes and the chunk is added (often lower
        if the buffer drained during the download).
    """

    def __init__(self, config_path: str | Path) -> None:
        with open(config_path) as f:
            data = json.load(f)

        self.buffer_threshold_ms: float = data.get("buffer_level_threshold", 20000)
        entries = data.get("prefetch", [])
        self.pending_segments: list[int] = [e["segment"] for e in entries]
        self.completed_segments: set[int] = set()

    def should_prefetch(self, buffer_level_ms: float) -> bool:
        """Return True if conditions are met to start a prefetch download."""
        return (
            buffer_level_ms > self.buffer_threshold_ms
            and len(self.pending_segments) > 0
        )

    def get_next_prefetch_segment(self) -> Optional[int]:
        """Return the next segment to prefetch, or None if none remain."""
        if not self.pending_segments:
            return None
        return self.pending_segments[0]

    def mark_prefetched(self, segment_index: int) -> None:
        """Record that *segment_index* has been successfully prefetched."""
        if segment_index in self.pending_segments:
            self.pending_segments.remove(segment_index)
        self.completed_segments.add(segment_index)

    def skip_stale_segments(self, current_segment: int) -> None:
        """Discard any pending segments at or behind *current_segment*.

        Called before each prefetch decision so that segments the playhead has
        already passed are never downloaded.  Discarded segments are NOT added
        to ``completed_segments`` because they were never actually fetched.
        """
        self.pending_segments = [
            s for s in self.pending_segments if s > current_segment
        ]
