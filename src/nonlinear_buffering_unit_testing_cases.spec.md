# Nonlinear Buffering Test Cases

## Context

- `MultiRegionBuffer` in [buffer.py](src/buffer.py) supports non-contiguous regions, making it capable of holding prefetched chunks at arbitrary positions
- `update_buffer_during_seek` in [sabre.py](src/sabre.py) handles seek logic: if seek target is in a buffered region, no rebuffer; otherwise, rebuffer occurs. In both cases, only non-prefetch chunks/regions entirely before the seek position are cleaned up; prefetch chunks and all regions after the seek position are preserved
- Movie segments are 3000ms each in `movie.json`, but tests will use a configurable `chunk_duration` (2000ms) for clean alignment with the user's "10-12s" example
- The `GlobalState` singleton (`gs`) in [global_state.py](src/global_state.py) must be reset between tests since `get_buffer_level()` and `get_contiguous_chunks_from_current_position()` read `gs.current_playback_pos` and `gs.buffer_fcc`

## Step 0: Add prefetch provenance tracking to MultiRegionBuffer

Add a **prefetch index set** to [buffer.py](src/buffer.py) so we can distinguish prefetched chunks from linearly buffered ones, even after regions merge.

Changes to `MultiRegionBuffer`:

- Add `self.prefetch_indices = set()` in `__init`__
- Add `add_prefetch_chunk(self, segment_index, quality)` method: calls `self.add_chunk(segment_index, quality)` then adds `segment_index` to `self.prefetch_indices`
- Update `pop_chunk()` to also call `self.prefetch_indices.discard(popped_idx)` when removing a chunk

This approach is minimally invasive -- merge logic, `BufferRegion`, and all existing methods remain untouched. The set is a parallel tracking structure.

## New File

Create `src/test_nonlinear_buffer_cases.py` using `unittest.TestCase`, consistent with existing [test_buffer_equivalence.py](src/test_buffer_equivalence.py).

## Seek Helper: `multi_region_buffer_seek` in sabre.py

Extracted from `update_buffer_during_seek` as a standalone function `multi_region_buffer_seek(buf, seek_pos_ms, seg_time)` in [sabre.py](src/sabre.py). Called by both `update_buffer_during_seek` (production) and the test file (via `from sabre import multi_region_buffer_seek`).

- Sets `gs.current_playback_pos = seek_pos_ms` and `gs.buffer_fcc = 0`
- Calls `buf._find_region_of(seek_pos_ms)` to check for a hit
- If hit: saves prefetch chunks before seek position from the hit region, trims all chunks before seek position (via `pop_chunk`), re-inserts saved prefetch chunks as separate regions, returns `False` (no rebuffer)
- If miss: clears only non-prefetch regions entirely before the seek position (regions after seek position and prefetch regions are preserved), returns `True` (rebuffer)
- `update_buffer_during_seek` calls this helper and then handles caller-specific state (`gs.buffer_fcc` partial-segment override, `gs.next_segment` on miss)

## Test Cases

### Test 1: Seek to prefetched chunk, no rebuffer

- Linear buffer: add chunks 0-3 (0-8s)
- Prefetch: add chunk 5 (10-12s) at high quality via `add_prefetch_chunk`
- Seek to 10000ms (10s, chunk 5)
- Assert: `multi_region_buffer_seek` returns `False` (no rebuffer)
- Assert: `buffer._find_region_of(10000)` returns a region
- Assert: `buffer.get_buffer_level()` equals 1 chunk duration (2000ms)

### Test 2: Seek to non-prefetched positions, rebuffer

Covers both an adjacent-gap miss and a far-out miss in a single test.

- Linear buffer: add chunks 0-3 (0-8s)
- Prefetch: add chunk 5 (10-12s)
- Seek to 8000ms (chunk 4, gap between linear end and prefetch start) → rebuffer
- Seek to 16000ms (chunk 8, far beyond any buffered region) → rebuffer
- Assert: `buffer._find_region_of(16000)` returns `None`

### Test 3: Multiple seeks with multiple prefetch chunks

- Linear buffer: add chunks 0-3 (0-8s)
- Prefetch: add chunks 5 (10-12s) and 10 (20-22s)
- First seek to 10000ms → no rebuffer, buffer level = 1 chunk
- Second seek to 20000ms → no rebuffer, buffer level = 1 chunk

### Test 4: Prefetch regions preserved and linear cleaned after seek

Verifies that prefetch regions survive across two sequential seeks and that non-prefetch linear data is cleaned up.

- Linear buffer: add chunks 0-3 (0-8s)
- Prefetch: add chunks 5 (10-12s) and 10 (20-22s)
- Seek to 10000ms (chunk 5)
- Assert: chunk 10 region (20-22s) still exists, `10 in buffer.prefetch_indices`
- Seek to 20000ms (chunk 10)
- Assert: linear buffer region (0-8s) is cleaned up
- Assert: `5 in buffer.prefetch_indices` (prefetch provenance survives)

### Test 5: Adjacent prefetch merges with linear buffer, provenance tracked

- Linear buffer: add chunks 0-3 (0-8s)
- Prefetch: add chunk 4 (8-10s) via `add_prefetch_chunk`
- Assert: regions merge into a single region 0-10s (1 valid region)
- Assert: `4 in buffer.prefetch_indices` (provenance survives merge)
- Assert: `0 not in buffer.prefetch_indices` (linear chunks are not marked as prefetch)

### Test 6: Seek within linear buffer (no prefetch -- baseline)

- Linear buffer: add chunks 0-7 (0-16s)
- No prefetch
- Seek to 4000ms (chunk 2, within linear buffer)
- Assert: no rebuffer, buffer level reflects 6 remaining chunks (12000ms)

### Test 7: Buffer level reflects contiguous prefetch after seek

- Prefetch: add contiguous chunks 10, 11, 12
- Seek to 20000ms (chunk 10) → hit
- Assert: no rebuffer, buffer level = 3 chunk durations (6000ms)

### Test 8: Non-contiguous prefetch regions -- hit and miss

- Prefetch: add chunks 5 and 20
- Seek to 10000ms (chunk 5) → hit
- Assert: chunk 20 region still exists (after seek position)
- Seek to 30000ms (chunk 15) → miss (between the two prefetch regions)
- Assert: rebuffer
- Assert: both prefetch regions preserved (`5` and `20` in `prefetch_indices`)
- Assert: chunk 20 region still exists

### Test 9: Non-prefetch regions after seek position are preserved

- Linear buffer: add chunks 0-3 (0-8s)
- Non-prefetch region: add chunks 20-22 (40-46s)
- Seek to 20000ms (chunk 10) → miss (between the two regions)
- Assert: rebuffer
- Assert: linear buffer (0-8s) cleaned (before seek, no prefetch)
- Assert: region at chunks 20-22 (40-46s) preserved (after seek position)

### Test 10: Prefetch chunks in same region preserved during seek

- Build single contiguous region [3, 4, 5, 6, 7] where chunks 3-4 are prefetch and 5-7 are linear
- Seek to 12000ms (chunk 6) → within the region, past the prefetch chunks
- Assert: no rebuffer
- Assert: prefetch chunks 3-4 preserved as a separate region
- Assert: `3 in buffer.prefetch_indices` and `4 in buffer.prefetch_indices`
- Assert: region at seek position (chunk 6) exists, buffer level = 2 chunks (6 and 7)

## Test setUp / tearDown

Each test must reset the `GlobalState` singleton:

```python
def setUp(self):
    gs._initialized = False
    gs.__init__()
    self.chunk_duration = 2000  # 2s chunks
    self.buffer = MultiRegionBuffer(self.chunk_duration)
    gs.multi_region_buffer = self.buffer
    gs.current_playback_pos = 0
    gs.buffer_fcc = 0
```

---

## Prefetch Module Implementation

### New File: `src/prefetch.py`

Create a `PrefetchModule` class that decides **when** and **where** to prefetch.

**JSON config format** (location + buffer threshold, bitrate decided by ABR):

```json
{
  "buffer_level_threshold": 20000,
  "prefetch": [
    {"segment": 5},
    {"segment": 10},
    {"segment": 15}
  ]
}
```

**PrefetchModule class:**

- `__init__(self, config_path: str)` -- loads JSON config including `buffer_level_threshold` and prefetch segment list
- `should_prefetch(self, buffer_level_ms: float) -> bool` -- returns `True` if `buffer_level_ms > buffer_threshold_ms` and there are remaining prefetch targets
- `get_next_prefetch_segment(self) -> int | None` -- returns next un-prefetched segment index, or `None` if all done
- `mark_prefetched(self, segment_index: int)` -- marks segment as completed (removes from pending list)
- `pending_segments: list[int]` -- remaining segments to prefetch
- `completed_segments: set[int]` -- segments already prefetched

### Integration in `sabre.py` -- `process_download_loop`

The prefetch check runs **independently** of the full-buffer delay, triggered by `prefetch_module.should_prefetch(buffer_level)` on every loop iteration (before the `full_delay > 0` check):

1. Skip already-prefetched segments: if `gs.next_segment` is in `buffer.prefetch_indices`, increment and continue
2. Check `prefetch_module.should_prefetch(buffer_level)` — if buffer level exceeds the config threshold and segments remain:
  a. Get next prefetch segment: `prefetch_seg = prefetch_module.get_next_prefetch_segment()`
   b. Ask ABR for quality: `quality, delay = abr.get_quality_delay(prefetch_seg)`
   c. Download via `network.download(size, prefetch_seg, quality, buffer_level)`
   d. Deplete buffer during download time (handles playback/seeks)
   e. Add to buffer: `gs.multi_region_buffer.add_prefetch_chunk(prefetch_seg, quality)`
   f. Mark completed: `prefetch_module.mark_prefetched(prefetch_seg)`
   g. Continue loop to re-evaluate buffer state
3. Then check `full_delay > 0` for normal buffer-full idling

### CLI arguments (in `sabre.py`)

- `--prefetch-config` / `-pc`: path to prefetch JSON config file (default: None, no prefetch). The config file includes the `buffer_level_threshold` value, so no separate CLI arg is needed for the threshold.

### ABR integration

The ABR decides quality for prefetch chunks using the **existing** `abr.get_quality_delay(segment_index)` interface. No changes to ABR classes needed. The quality chosen will reflect the ABR's view of current conditions (throughput, buffer level). Since prefetch happens when buffer is high, ABR will typically choose a high quality -- matching the user's expectation: "Generally the prefetch chunk will have a high bitrate, because the prefetch chunk is already downloaded when the buffer level is high enough."

### Prefetch module tests (in `test_nonlinear_buffer_cases.py`)

- **Test 11**: JSON loading -- verify `PrefetchModule` correctly parses the config and lists pending segments
- **Test 12**: Trigger logic -- `should_prefetch` returns `True` only when buffer > threshold and segments remain
- **Test 13**: Segment exhaustion -- after all segments prefetched, `get_next_prefetch_segment()` returns `None`
- **Test 14**: Skip already-prefetched -- during linear download, prefetched segments are skipped (next_segment incremented)
