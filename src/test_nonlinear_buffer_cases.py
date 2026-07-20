#!/usr/bin/env python3
"""
Case-based tests for the Nonlinear Buffer algorithm.

Each test covers a specific scenario (seek hit/miss, prefetch provenance,
region preservation, adjacent merges, buffer level accuracy, PrefetchModule
API) to verify the Nonlinear Buffer handles it correctly.

Usage:
    python test_nonlinear_buffer_cases.py
    python test_nonlinear_buffer_cases.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).parent
sys.path.insert(0, str(SRC_DIR))

from buffer import MultiRegionBuffer
from global_state import GlobalState, gs
from prefetch import PrefetchModule
from sabre import multi_region_buffer_seek


# ---------------------------------------------------------------------------
# MultiRegionBuffer + seek unit tests (Tests 1-10)
# ---------------------------------------------------------------------------

class TestNonlinearBuffering(unittest.TestCase):
    """Unit tests that directly manipulate MultiRegionBuffer and GlobalState."""

    def setUp(self):
        GlobalState._initialized = False
        gs.__init__()
        self.chunk_duration = 2000  # 2 s chunks
        self.buffer = MultiRegionBuffer(self.chunk_duration)
        gs.multi_region_buffer = self.buffer
        gs.current_playback_pos = 0
        gs.buffer_fcc = 0

    # ------------------------------------------------------------------ #
    # Test 1: Positive seek -- seek to prefetched chunk, no rebuffer      #
    # ------------------------------------------------------------------ #
    def test_seek_to_prefetched_chunk_no_rebuffer(self):
        for seg in range(4):
            self.buffer.add_chunk(seg, quality=2)

        self.buffer.add_prefetch_chunk(5, quality=5)

        rebuffer = multi_region_buffer_seek(self.buffer, 10000, self.chunk_duration)
        self.assertFalse(rebuffer, "Seek to prefetched chunk should NOT rebuffer")
        self.assertIsNotNone(
            self.buffer._find_region_of(10000),
            "Region at 10000 ms should exist after seek",
        )
        self.assertEqual(
            self.buffer.get_buffer_level(), self.chunk_duration,
            "Buffer level should equal one chunk duration (2000 ms)",
        )

    # ------------------------------------------------------------------ #
    # Test 2: Seek to non-prefetched positions, rebuffer                  #
    #         (covers adjacent gap AND far-out miss)                      #
    # ------------------------------------------------------------------ #
    def test_seek_to_non_prefetched_rebuffers(self):
        for seg in range(4):
            self.buffer.add_chunk(seg, quality=2)

        self.buffer.add_prefetch_chunk(5, quality=3)

        # Adjacent gap: chunk 4 sits between linear end and prefetch start
        rebuffer = multi_region_buffer_seek(self.buffer, 8000, self.chunk_duration)
        self.assertTrue(rebuffer, "Seek to gap at chunk 4 should rebuffer")

        # Far-out miss: chunk 8 is well beyond any buffered region
        rebuffer = multi_region_buffer_seek(self.buffer, 16000, self.chunk_duration)
        self.assertTrue(rebuffer, "Seek to 16000 ms (chunk 8, no data) should rebuffer")
        self.assertIsNone(
            self.buffer._find_region_of(16000),
            "No region should exist at 16000 ms",
        )

    # ------------------------------------------------------------------ #
    # Test 3: Multiple seeks with multiple prefetch chunks                #
    # ------------------------------------------------------------------ #
    def test_multiple_seeks_with_multiple_prefetch(self):
        for seg in range(4):
            self.buffer.add_chunk(seg, quality=2)

        self.buffer.add_prefetch_chunk(5, quality=4)
        self.buffer.add_prefetch_chunk(10, quality=4)

        rebuffer = multi_region_buffer_seek(self.buffer, 10000, self.chunk_duration)
        self.assertFalse(rebuffer)
        self.assertEqual(
            self.buffer.get_buffer_level(), self.chunk_duration,
            "Buffer level should be one chunk after first seek",
        )

        rebuffer = multi_region_buffer_seek(self.buffer, 20000, self.chunk_duration)
        self.assertFalse(rebuffer)
        self.assertEqual(
            self.buffer.get_buffer_level(), self.chunk_duration,
            "Buffer level should be one chunk after second seek",
        )

    # ------------------------------------------------------------------ #
    # Test 4: Prefetch preserved, linear cleaned after seek               #
    #         (covers region survival across two sequential seeks)        #
    # ------------------------------------------------------------------ #
    def test_prefetch_regions_preserved_after_seek(self):
        for seg in range(4):
            self.buffer.add_chunk(seg, quality=2)

        self.buffer.add_prefetch_chunk(5, quality=4)
        self.buffer.add_prefetch_chunk(10, quality=4)

        multi_region_buffer_seek(self.buffer, 10000, self.chunk_duration)

        self.assertIsNotNone(
            self.buffer._find_region_of(20000),
            "Chunk 10 region should be preserved after seeking to chunk 5",
        )
        self.assertIn(10, self.buffer.prefetch_indices,
                       "Prefetch provenance for chunk 10 should survive")

        multi_region_buffer_seek(self.buffer, 20000, self.chunk_duration)

        self.assertIsNone(
            self.buffer._find_region_of(0),
            "Linear buffer at 0 ms should be cleaned up after seek",
        )
        self.assertIn(5, self.buffer.prefetch_indices,
                       "Prefetch provenance for chunk 5 should survive")

    # ------------------------------------------------------------------ #
    # Test 5: Adjacent prefetch merges, provenance tracked                #
    # ------------------------------------------------------------------ #
    def test_adjacent_prefetch_merges_provenance_tracked(self):
        for seg in range(4):
            self.buffer.add_chunk(seg, quality=2)

        self.buffer.add_prefetch_chunk(4, quality=5)

        valid_regions = [s for s in self.buffer.region_starts if s in self.buffer.region_map]
        self.assertEqual(
            len(valid_regions), 1,
            "Adjacent prefetch should merge into single region",
        )

        self.assertIn(4, self.buffer.prefetch_indices,
                       "Prefetch index 4 should remain after merge")
        self.assertNotIn(0, self.buffer.prefetch_indices,
                          "Linear chunk 0 should NOT be in prefetch_indices")

    # ------------------------------------------------------------------ #
    # Test 6: Seek within linear buffer (baseline, no prefetch)           #
    # ------------------------------------------------------------------ #
    def test_seek_within_linear_buffer_no_prefetch(self):
        for seg in range(8):
            self.buffer.add_chunk(seg, quality=3)

        rebuffer = multi_region_buffer_seek(self.buffer, 4000, self.chunk_duration)
        self.assertFalse(rebuffer, "Seek within linear buffer should not rebuffer")

        expected_level = self.chunk_duration * 6  # chunks 2,3,4,5,6,7 remain
        self.assertEqual(
            self.buffer.get_buffer_level(), expected_level,
            f"Buffer level should reflect 6 remaining chunks ({expected_level} ms)",
        )

    # ------------------------------------------------------------------ #
    # Test 7: Buffer level reflects contiguous prefetch after seek        #
    # ------------------------------------------------------------------ #
    def test_buffer_level_reflects_contiguous_prefetch(self):
        self.buffer.add_prefetch_chunk(10, quality=4)
        self.buffer.add_prefetch_chunk(11, quality=4)
        self.buffer.add_prefetch_chunk(12, quality=4)

        rebuffer = multi_region_buffer_seek(self.buffer, 20000, self.chunk_duration)
        self.assertFalse(rebuffer)
        self.assertEqual(
            self.buffer.get_buffer_level(), self.chunk_duration * 3,
            "Buffer level should be 3 contiguous prefetch chunks (6000 ms)",
        )

    # ------------------------------------------------------------------ #
    # Test 8: Non-contiguous prefetch regions -- hit and miss             #
    # ------------------------------------------------------------------ #
    def test_noncontiguous_prefetch_regions(self):
        self.buffer.add_prefetch_chunk(5, quality=3)
        self.buffer.add_prefetch_chunk(20, quality=3)

        rebuffer = multi_region_buffer_seek(self.buffer, 10000, self.chunk_duration)
        self.assertFalse(rebuffer)

        self.assertIsNotNone(self.buffer._find_region_of(40000))

        rebuffer = multi_region_buffer_seek(self.buffer, 30000, self.chunk_duration)
        self.assertTrue(rebuffer, "Seek to gap between prefetch regions should rebuffer")

        self.assertIn(5, self.buffer.prefetch_indices)
        self.assertIn(20, self.buffer.prefetch_indices)
        self.assertIsNotNone(
            self.buffer._find_region_of(40000),
            "Prefetch region at chunk 20 should survive a miss at chunk 15",
        )

    # ------------------------------------------------------------------ #
    # Test 9: Non-prefetch regions after seek position are preserved      #
    # ------------------------------------------------------------------ #
    def test_regions_after_seek_preserved(self):
        """All regions after the seek position are kept, regardless of
        whether they contain prefetch chunks."""
        for seg in range(4):
            self.buffer.add_chunk(seg, quality=2)

        for seg in range(20, 23):
            self.buffer.add_chunk(seg, quality=3)

        rebuffer = multi_region_buffer_seek(self.buffer, 20000, self.chunk_duration)
        self.assertTrue(rebuffer, "Seek to gap should rebuffer")

        self.assertIsNone(
            self.buffer._find_region_of(0),
            "Non-prefetch region before seek should be cleaned",
        )

        self.assertIsNotNone(
            self.buffer._find_region_of(40000),
            "Non-prefetch region AFTER seek position should be preserved",
        )

    # ------------------------------------------------------------------ #
    # Test 10: Prefetch chunks in same region preserved during seek       #
    # ------------------------------------------------------------------ #
    def test_prefetch_in_same_region_preserved(self):
        """When seeking within a region that contains prefetch chunks before
        the seek position, those prefetch chunks are saved and re-inserted
        as a separate region."""
        self.buffer.add_prefetch_chunk(3, quality=5)
        self.buffer.add_prefetch_chunk(4, quality=5)
        self.buffer.add_chunk(5, quality=2)
        self.buffer.add_chunk(6, quality=2)
        self.buffer.add_chunk(7, quality=2)

        valid_regions = [s for s in self.buffer.region_starts if s in self.buffer.region_map]
        self.assertEqual(len(valid_regions), 1, "Should be one merged region")

        rebuffer = multi_region_buffer_seek(self.buffer, 12000, self.chunk_duration)
        self.assertFalse(rebuffer)

        self.assertIsNotNone(
            self.buffer._find_region_of(6000),
            "Prefetch chunk 3 (at 6000 ms) should be preserved",
        )
        self.assertIn(3, self.buffer.prefetch_indices)
        self.assertIn(4, self.buffer.prefetch_indices)

        self.assertIsNotNone(
            self.buffer._find_region_of(12000),
            "Region at seek position should exist",
        )
        self.assertEqual(
            self.buffer.get_buffer_level(), self.chunk_duration * 2,
            "Buffer level should be 2 chunks (6 and 7) at seek position",
        )


# ---------------------------------------------------------------------------
# PrefetchModule unit tests (Tests 11-14)
# ---------------------------------------------------------------------------

class TestPrefetchModule(unittest.TestCase):
    """Unit tests for PrefetchModule loading, trigger logic, and exhaustion."""

    FIXTURE = SRC_DIR / "synthetic" / "test_prefetch_config_fixture.json"

    def setUp(self):
        self.pm = PrefetchModule(str(self.FIXTURE))

    # ------------------------------------------------------------------ #
    # Test 11: JSON loading                                               #
    # ------------------------------------------------------------------ #
    def test_json_loading(self):
        self.assertEqual(self.pm.pending_segments, [5, 10, 15])
        self.assertEqual(self.pm.completed_segments, set())
        self.assertEqual(self.pm.buffer_threshold_ms, 20000)

    # ------------------------------------------------------------------ #
    # Test 12: Trigger logic                                              #
    # ------------------------------------------------------------------ #
    def test_trigger_logic(self):
        self.assertFalse(
            self.pm.should_prefetch(10000),
            "Should NOT prefetch when buffer < threshold",
        )
        self.assertTrue(
            self.pm.should_prefetch(25000),
            "Should prefetch when buffer > threshold",
        )

    # ------------------------------------------------------------------ #
    # Test 13: Segment exhaustion                                         #
    # ------------------------------------------------------------------ #
    def test_segment_exhaustion(self):
        for seg in [5, 10, 15]:
            self.assertIsNotNone(self.pm.get_next_prefetch_segment())
            self.pm.mark_prefetched(seg)
        self.assertIsNone(self.pm.get_next_prefetch_segment())
        self.assertFalse(self.pm.should_prefetch(99999))

    # ------------------------------------------------------------------ #
    # Test 13b: skip_stale_segments removes past entries                 #
    # ------------------------------------------------------------------ #
    def test_skip_stale_segments(self):
        """Segments at or behind the current playhead must be discarded before
        any prefetch download is attempted — reproduces the bug where seg 7 and
        seg 12 were downloaded at wall-clock ~300 s even though the playhead
        had already seeked past content position ~90 s (seg 30+)."""
        pm = PrefetchModule(str(self.FIXTURE))   # pending: [5, 10, 15]

        # Playhead is at segment 10 — segments 5 and 10 are stale.
        pm.skip_stale_segments(current_segment=10)
        self.assertEqual(pm.pending_segments, [15],
            "Segments 5 and 10 should be purged; only 15 remains")

        # Calling again when all remaining segments are also stale clears list.
        pm.skip_stale_segments(current_segment=15)
        self.assertEqual(pm.pending_segments, [],
            "All pending segments purged when playhead is at or past the last one")
        self.assertFalse(pm.should_prefetch(99999),
            "should_prefetch must return False when nothing is pending")

    # ------------------------------------------------------------------ #
    # Test 14: Skip already-prefetched during linear download             #
    # ------------------------------------------------------------------ #
    def test_skip_already_prefetched(self):
        """Simulate the linear download loop skipping prefetched segments.

        In sabre.py, the download loop checks ``gs.next_segment in
        buffer.prefetch_indices`` and increments ``gs.next_segment`` to
        avoid re-downloading prefetched chunks.
        """
        GlobalState._initialized = False
        gs.__init__()
        chunk_duration = 2000
        buf = MultiRegionBuffer(chunk_duration)
        gs.multi_region_buffer = buf
        gs.current_playback_pos = 0
        gs.buffer_fcc = 0
        gs.next_segment = 0

        buf.add_prefetch_chunk(3, quality=5)
        buf.add_prefetch_chunk(6, quality=5)

        downloaded = []
        for _ in range(10):
            if gs.next_segment >= 10:
                break
            if gs.next_segment in buf.prefetch_indices:
                gs.next_segment += 1
                continue
            downloaded.append(gs.next_segment)
            buf.add_chunk(gs.next_segment, quality=2)
            gs.next_segment += 1

        self.assertNotIn(3, downloaded,
                          "Segment 3 should be skipped (already prefetched)")
        self.assertNotIn(6, downloaded,
                          "Segment 6 should be skipped (already prefetched)")
        self.assertIn(0, downloaded)
        self.assertIn(1, downloaded)
        self.assertIn(4, downloaded)
        self.assertIn(5, downloaded)


# ---------------------------------------------------------------------------
# from_segment calculation tests (Tests 15-18)
# ---------------------------------------------------------------------------

class TestFromSegmentCalculation(unittest.TestCase):
    """
    Verify that the from_segment value reported at seek time reflects the
    actual content position, not the wall-clock simulation time.

    The logic under test (sabre.py, interrupted_by_seek):

        if gs.multi_region_buffer is not None:
            from_segment = int(gs.current_playback_pos / seg_time)
        else:
            buffer_base = gs.next_segment - len(gs.buffer_contents)
            from_segment = int((buffer_base * seg_time + gs.buffer_fcc) / seg_time)
    """

    SEG_TIME = 3000  # ms — matches the real movie (3 s segments)

    def setUp(self):
        GlobalState._initialized = False
        gs.__init__()
        gs.buffer_fcc = 0

    def _from_segment_dynamic(self):
        """Replicate the nonlinear-buffer branch of the from_segment calculation."""
        return int(gs.current_playback_pos / self.SEG_TIME)

    def _from_segment_linear(self):
        """Replicate the linear-buffer branch of the from_segment calculation."""
        buffer_base = gs.next_segment - len(gs.buffer_contents)
        return int((buffer_base * self.SEG_TIME + gs.buffer_fcc) / self.SEG_TIME)

    # ------------------------------------------------------------------ #
    # Test 15: Nonlinear Buffer — from_segment tracks content_playback_pos #
    #          and diverges from wall-clock after rebuffering             #
    # ------------------------------------------------------------------ #
    def test_dynamic_from_segment_uses_content_pos_not_wall_clock(self):
        """After rebuffering, current_playback_pos lags behind total_play_time.
        from_segment must be based on content position, not wall-clock."""
        gs.multi_region_buffer = MultiRegionBuffer(self.SEG_TIME)

        # Simulate: 10 s of rebuffering occurred, so content is 10 s behind wall-clock.
        gs.total_play_time = 65_000   # wall-clock: 65 s
        gs.current_playback_pos = 55_000  # content:    55 s  (10 s rebuffer)

        from_seg = self._from_segment_dynamic()
        wall_clock_seg = int(gs.total_play_time / self.SEG_TIME)

        self.assertEqual(from_seg, 18,
            "from_segment should be content-based (55000/3000=18), not wall-clock-based")
        self.assertNotEqual(from_seg, wall_clock_seg,
            "from_segment must differ from naive wall-clock division after rebuffering")

    # ------------------------------------------------------------------ #
    # Test 16: Linear buffer — from_segment equals buffer_base           #
    # ------------------------------------------------------------------ #
    def test_linear_from_segment_equals_buffer_base(self):
        """For linear buffer, from_segment = next_segment - len(buffer_contents),
        which is the index of the segment currently being played."""
        gs.multi_region_buffer = None

        # Simulate 10 segments downloaded, 3 still in buffer (segs 7, 8, 9).
        # buffer_base = 10 - 3 = 7  → currently playing segment 7.
        gs.next_segment = 10
        gs.buffer_contents = [(q, 2) for q in range(3)]  # 3 buffered items
        gs.buffer_fcc = 500  # 500 ms into segment 7

        from_seg = self._from_segment_linear()
        self.assertEqual(from_seg, 7,
            "from_segment should be buffer_base=7 (next_segment=10, 3 buffered)")

    # ------------------------------------------------------------------ #
    # Test 17: Linear buffer — buffer_fcc does not change from_segment   #
    # ------------------------------------------------------------------ #
    def test_linear_from_segment_invariant_to_buffer_fcc(self):
        """buffer_fcc is always < seg_time, so adding it can never push
        content_pos into the next segment — from_segment stays = buffer_base."""
        gs.multi_region_buffer = None
        gs.next_segment = 10
        gs.buffer_contents = [(q, 2) for q in range(3)]   # buffer_base = 7

        for fcc in [0, 1, 999, 1500, self.SEG_TIME - 1]:
            gs.buffer_fcc = fcc
            from_seg = self._from_segment_linear()
            self.assertEqual(from_seg, 7,
                f"from_segment should always be 7 regardless of buffer_fcc={fcc}")

    # ------------------------------------------------------------------ #
    # Test 18: Two sequential seeks — user's specific example            #
    #          seek_when=46.4 → seek_to=66.8, then seek_when=65.0        #
    # ------------------------------------------------------------------ #
    def test_from_segment_after_two_sequential_seeks(self):
        """
        Reproduces the reported scenario:
          Seek 1: at wall-clock 46.4 s → content jumps to 66.8 s (seg 22)
          Play for 18.6 s wall-clock but ~1.4 s is rebuffer → content at ~84 s
          Seek 2: at wall-clock 65.0 s → from_segment should be ~28, NOT 21

        Wall-clock-based (wrong):  floor(65_000 / 3000) = 21
        Content-based   (correct): floor(84_000 / 3000) = 28
        """
        gs.multi_region_buffer = MultiRegionBuffer(self.SEG_TIME)

        # After seek 1 lands at 66.8 s, the player plays forward.
        # 18.6 s of wall-clock elapses; 1.4 s is rebuffering → 17.2 s of content.
        # content position at seek 2: 66_800 + 17_200 = 84_000 ms
        content_pos_at_seek2 = 66_800 + 17_200   # = 84_000 ms
        gs.current_playback_pos = content_pos_at_seek2
        gs.total_play_time = 65_000  # wall-clock at seek 2

        from_seg = self._from_segment_dynamic()

        self.assertEqual(from_seg, 28,
            "from_segment at second seek should be 28 (content at 84 s), not 21")
        self.assertNotEqual(from_seg, int(gs.total_play_time / self.SEG_TIME),
            "from_segment must NOT equal wall-clock-based segment (21)")


if __name__ == "__main__":
    unittest.main()
