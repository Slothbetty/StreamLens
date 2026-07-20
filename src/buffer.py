from __future__ import annotations
import math
import sys
import typing
from bisect import bisect_right
from enum import Enum

# Import gs for compatibility methods
from global_state import gs

class BufferRegion:
    """Buffer region: a continuous region of chunks.
    Stores boundaries as integer chunk indices to avoid float drift.
    """
    def __init__(self, start_idx: int, chunk_duration: float) -> None:
        self.start_idx = start_idx  # inclusive chunk index
        self.end_idx = None         # exclusive chunk index
        self.chunk_duration = chunk_duration
        self.chunks = []           # Chunks [quality_1, quality_2, ...]

    def start_ms(self) -> float:
        return self.start_idx * self.chunk_duration

    def end_ms(self) -> float | None:
        if self.end_idx is None:
            return None
        return self.end_idx * self.chunk_duration

    def add_chunk(self, quality: float) -> None:
        """Adds one chunk of given quality to the region.
        This is to be used during download. """
        if self.end_idx is None:
            self.end_idx = self.start_idx + 1
        else:
            self.end_idx += 1
        self.chunks.append(quality)

    def pop_chunk(self, pos_idx: int) -> None:
        """Pops all chunks before `pos_idx` for user seek.
        This is to be used during seek, assuming no back seek allowed. """
        n_chunk_to_pop = max(0, pos_idx - self.start_idx)
        self.start_idx += n_chunk_to_pop
        self.chunks = self.chunks[n_chunk_to_pop : ]
        if self.chunks:
            self.end_idx = self.start_idx + len(self.chunks)
        else:
            self.end_idx = None

    def _pop_back_chunk(self, pos_idx: int) -> None:
        """Pops all chunks after `pos_idx`. Used in merge. """
        if self.end_idx is None:
            return
        n_chunk_to_pop = max(0, self.end_idx - pos_idx)
        self.end_idx -= n_chunk_to_pop
        if n_chunk_to_pop > 0:
            self.chunks = self.chunks[ : -n_chunk_to_pop]
        if not self.chunks:
            self.end_idx = None

    def exists(self, pos_idx: int) -> bool:
        """Returns if chunk at `pos_idx` exists in this region. """
        if self.end_idx is None:
            return False  # Region has no chunks yet
        return self.start_idx <= pos_idx < self.end_idx

    def try_merge(self, region: BufferRegion) -> bool:
        """Try merging this region with another buffer region.

        If the given region can be merged, then current region is updated with
        the new chunks; otherwise if region and current region are not
        overlapped, nothing is changed. Returns if the merge is successful.
        """
        # Handle None end values
        if self.end_idx is None or region.end_idx is None:
            return False
        if self.end_idx < region.start_idx or self.start_idx > region.end_idx:
            return False
        # TODO: logging w/ various levels is preferred here
        if self.start_idx < region.start_idx:
            # self <- region case
            if self.end_idx > region.start_idx:
                print(f'Warning: positive overlap between regions: '
                    f'self.end: {self.end_idx} > region.start: {region.start_idx}')
            region.pop_chunk(self.end_idx)
            self.end_idx = region.end_idx
            self.chunks.extend(region.chunks)
            return True
        else:
            # region -> self case
            if self.start_idx < region.end_idx:
                print(f'Warning: positive overlap between regions: '
                    f'self.start: {self.start_idx} > region.end: {region.end_idx}')
            region._pop_back_chunk(self.start_idx)
            self.start_idx = region.start_idx
            self.chunks = region.chunks + self.chunks
            return True


class MultiRegionBuffer:
    """
    Multi-Region-Buffer: buffer with multiple regions for Nonlinear Buffering."""
    
    def __init__(self, chunk_duration) -> None:
        self.region_starts = []     # start idx of regions for bisect
        # Reason for not using list: regions can be merged, and i will be moved
        # for all the regions afterwards
        self.region_map = {}        # region map {idx: region}
        self.chunk_duration = chunk_duration
        self.prefetch_indices = set()  # tracks which chunk indices were prefetched

    def _pos_to_idx(self, pos_ms: float) -> int:
        """Convert milliseconds to chunk index (floor to containing chunk)."""
        return int(math.floor(pos_ms / self.chunk_duration + 1e-9))

    def _idx_to_pos(self, idx: int) -> float:
        return idx * self.chunk_duration

    def buffer_by_pos(self, pos: float, quality: float):
        """Buffers a chunk for `pos`. Handles three cases:
        1. pos inside existing region -> add chunk to that region
        2. pos at end of existing region (adjacent) -> extend that region
        3. pos misses all regions -> create new region
        """
        pos_idx = self._pos_to_idx(pos)
        region = self._find_region_of_idx(pos_idx)
        if region:
            region.add_chunk(quality)
            # Filter valid starts before checking next region
            valid_starts = [s for s in self.region_starts if s in self.region_map]
            i_region = bisect_right(valid_starts, pos_idx) - 1
            if 0 <= i_region < len(valid_starts) and i_region < len(valid_starts) - 1:
                next_start = valid_starts[i_region + 1]
                if next_start in self.region_map:
                    next_region = self.region_map[next_start]
                    if region.try_merge(next_region):
                        # Successfully merged, clean up the merged region
                        if next_start in self.region_map:
                            del self.region_map[next_start]
                        if next_start in self.region_starts:
                            self.region_starts.remove(next_start)
            print(f'Add into existing region: {region.start_ms()} - {region.end_ms()} s')

        else:
            # Check if there's a region that ends exactly at this position (adjacent)
            # This handles sequential downloads
            valid_starts = [s for s in self.region_starts if s in self.region_map]
            found_adjacent = False
            for start in valid_starts:
                adj_region = self.region_map[start]
                if adj_region.end_idx is not None:
                    if adj_region.end_idx == pos_idx:
                        # Found adjacent region - extend it
                        adj_region.add_chunk(quality)
                        found_adjacent = True
                        # Try to merge with next region if exists
                        valid_starts_sorted = sorted(valid_starts)
                        if start in valid_starts_sorted:
                            idx = valid_starts_sorted.index(start)
                            if idx + 1 < len(valid_starts_sorted):
                                next_start = valid_starts_sorted[idx + 1]
                                if next_start in self.region_map:
                                    next_region = self.region_map[next_start]
                                    if adj_region.try_merge(next_region):
                                        # Successfully merged, clean up the merged region
                                        if next_start in self.region_map:
                                            del self.region_map[next_start]
                                        if next_start in self.region_starts:
                                            self.region_starts.remove(next_start)
                        print(f'Extend adjacent region: {adj_region.start_ms()} - {adj_region.end_ms()} s')
                        break
            
            if not found_adjacent:
                start_idx = pos_idx
                region = BufferRegion(start_idx, self.chunk_duration)
                region.add_chunk(quality)  # Add the chunk to set end
                self.region_starts.append(start_idx)
                self.region_starts.sort()
                self.region_map[start_idx] = region
                print(f'Start a new region: {region.start_ms()} - {region.end_ms()} s')

    def buffer_by_region(self, i_region: int, quality: float):
        """Buffers a chunk after i-th existing region.
        New buffer region is not supported here on purpose.
        """
        # Filter valid starts
        valid_starts = [s for s in self.region_starts if s in self.region_map]
        assert 0 <= i_region < len(valid_starts)
        region_start = valid_starts[i_region]
        region = self.region_map[region_start]
        region.add_chunk(quality)
        if i_region < len(valid_starts) - 1:
            next_start = valid_starts[i_region + 1]
            if next_start in self.region_map:
                next_region = self.region_map[next_start]
                region.try_merge(next_region)
        print(f'Add into existing region: {region.start_ms()} - {region.end_ms()} s')

    def _find_region_of(self, pos: float):
        """Finds the region of given `pos` in milliseconds."""
        pos_idx = self._pos_to_idx(pos)
        return self._find_region_of_idx(pos_idx)

    def _find_region_of_idx(self, pos_idx: int):
        """Finds the region of given chunk index."""
        
        if not self.region_starts:
            return None
        
        # Filter out starts that don't exist in region_map (due to merging)
        valid_starts = sorted([s for s in self.region_starts if s in self.region_map])
        if not valid_starts:
            return None
        
        # First, try to find region containing pos (standard case)
        i_region = bisect_right(valid_starts, pos_idx) - 1
        if 0 <= i_region < len(valid_starts):
            start = valid_starts[i_region]
            if start in self.region_map:
                region = self.region_map[start]
                if region.exists(pos_idx):
                    return region
        
        return None
    
    def get_buffer_level(self, buffer_fcc=None):
        """Calculate buffer level. For sequential downloads, matches linear buffering behavior.
        Counts remaining chunks in buffer (chunks are removed via pop_chunk() during playback,
        just like buffer_contents.pop(0) in linear buffering).
        
        Uses get_contiguous_chunks_from_current_position() to correctly count chunks from 
        current playback position forward, ensuring consistent behavior for both sequential 
        downloads and seeks/multi-region scenarios."""
        # Use provided buffer_fcc parameter, or fall back to gs.buffer_fcc if available
        if buffer_fcc is None:
            buffer_fcc = gs.buffer_fcc if gs else 0
        
        # Get contiguous chunks from current playback position (works for both sequential and multi-region)
        contiguous_chunks = self.get_contiguous_chunks_from_current_position()
        total_chunks = len(contiguous_chunks)
        
        # Calculate buffer level
        buffer_level = self.chunk_duration * total_chunks - buffer_fcc
        
        # Clamp to 0 to prevent negative buffer levels (shouldn't happen, but safety check)
        buffer_level = max(0, buffer_level)
        
        return buffer_level
    
    def get_contiguous_chunks_from_current_position(self):
        """Return contiguous chunks from current playback position forward."""
        if gs is None:
            return []
        
        pos_idx = self._pos_to_idx(gs.current_playback_pos)
        region = self._find_region_of_idx(pos_idx)
        if not region:
            return []
        
        # Slice from pos_idx within the region: after a prefetch hit + merge,
        # region.start_idx can be behind pos_idx (saved prefetch re-inserted before
        # current position). Returning all chunks would cause phantom replay of
        # already-past segments and an inflated buffer level.
        pos_in_region = pos_idx - region.start_idx
        chunks = list(region.chunks[pos_in_region:])

        # Collect chunks from subsequent contiguous regions
        valid_starts = sorted([s for s in self.region_starts if s in self.region_map])
        try:
            region_idx = valid_starts.index(region.start_idx)
        except ValueError:
            return chunks
        
        # QUESTION: Shall we ignore the gaps between regions for Nonlinear Buffering? 
        # Current implementation does not ignore the gaps.
        current_region = region
        for i in range(region_idx + 1, len(valid_starts)):
            next_start = valid_starts[i]
            next_region = self.region_map.get(next_start)
            if not next_region:
                break
            
            if current_region.end_idx is not None:
                if current_region.end_idx == next_start:
                    chunks.extend(next_region.chunks)
                    current_region = next_region
                else:
                    break
            else:
                break
        
        return chunks
    
    def add_chunk(self, segment_index, quality):
        """Add chunk, convert segment_index to ms position."""
        pos_ms = segment_index * self.chunk_duration
        self.buffer_by_pos(pos_ms, quality)
        self.merge_adjacent_regions()

    def add_prefetch_chunk(self, segment_index, quality):
        """Add a prefetch chunk and record its provenance."""
        self.add_chunk(segment_index, quality)
        self.prefetch_indices.add(segment_index)
    
    def merge_adjacent_regions(self):
        """Merge regions that are adjacent (no gap between them)."""
        # Filter out any starts that don't have corresponding regions in the map, or regions with no chunks
        valid_starts = []
        for start in self.region_starts:
            if start in self.region_map:
                region = self.region_map[start]
                if region and region.chunks:  # Only include regions with chunks
                    valid_starts.append(start)
        
        # Update region_starts to remove stale/empty entries
        self.region_starts = valid_starts
        
        if len(valid_starts) < 2:
            return
        
        # Sort regions by start position
        sorted_starts = sorted(valid_starts)
        merged_starts = []
        merged_map = {}
        
        i = 0
        while i < len(sorted_starts):
            current_start = sorted_starts[i]
            if current_start not in self.region_map:
                i += 1
                continue
                
            current_region = self.region_map[current_start]
            
            # Skip empty regions
            if not current_region or not current_region.chunks:
                i += 1
                continue
            
            # Check if we can merge with next region
            if i + 1 < len(sorted_starts):
                next_start = sorted_starts[i + 1]
                if next_start not in self.region_map:
                    # Next region doesn't exist, keep current and move on
                    merged_starts.append(current_start)
                    merged_map[current_start] = current_region
                    i += 1
                    continue
                    
                next_region = self.region_map[next_start]
                
                # Check if regions are adjacent (end of current == start of next)
                if current_region.end_idx is not None:
                    if current_region.end_idx == next_start:
                        # Merge: extend current region with next region's chunks
                        if current_region.try_merge(next_region):
                            # Successfully merged, remove next region from map
                            if next_start in self.region_map:
                                del self.region_map[next_start]
                            # After merging, current_region is updated in place
                            # For adjacent regions, current_region.start doesn't change (self <- region case)
                            merged_starts.append(current_start)
                            merged_map[current_start] = current_region
                            # Successfully merged, skip next region
                            i += 2
                            continue
            
            # Keep current region as-is
            merged_starts.append(current_start)
            merged_map[current_start] = current_region
            i += 1
        
        # Update MultiRegionBuffer with merged regions
        self.region_starts = merged_starts
        self.region_map = merged_map

    def pop_chunk(self):
            """Remove first chunk (index 0) from current playback position region."""
            if gs is None:
                return
            # Clean up any stale entries in region_starts first
            self.region_starts = [s for s in self.region_starts if s in self.region_map]
            
            # Find region containing current playback position (handles boundary cases)
            pos_idx = self._pos_to_idx(gs.current_playback_pos)
            target_idx = pos_idx - 1 if pos_idx > 0 else pos_idx
            region = self._find_region_of_idx(target_idx)
            if not region or not region.chunks:
                return
            
            # Remove the first chunk (index 0) - matches buffer_contents.pop(0)
            old_start = region.start_idx
            self.prefetch_indices.discard(old_start)
            region.chunks.pop(0)
            
            # Update region start since we removed the first chunk
            new_start = region.start_idx + 1
            
            # Update region_map key if start changed
            # First, remove old key
            if old_start in self.region_map:
                del self.region_map[old_start]
            if old_start in self.region_starts:
                self.region_starts.remove(old_start)
            
            # Update region start
            region.start_idx = new_start
             
            # Recalculate region end based on new start and remaining chunks
            # end = start + len(chunks) * chunk_duration
            if region.chunks:
                region.end_idx = region.start_idx + len(region.chunks)
            else:
                region.end_idx = None
            
            # Check if region is empty (no chunks left) BEFORE updating region_map
            if len(region.chunks) == 0:
                # Region is empty, don't add it back to region_map
                # old_start already removed above, so we're done
                return  # Early return since region is gone
            
            # Region still has chunks, update region_map with new key
            # Only add if new_start doesn't already exist (shouldn't happen in sequential downloads, but safety check)
            if new_start not in self.region_map:
                if new_start not in self.region_starts:
                    self.region_starts.append(new_start)
                self.region_starts.sort()
                self.region_map[new_start] = region
            else:
                # new_start already exists - this shouldn't happen in sequential downloads
                # but if it does, merge chunks into existing region
                existing_region = self.region_map[new_start]
                if existing_region and existing_region.chunks:
                    # Merge chunks
                    existing_region.chunks.extend(region.chunks)
                    if region.end_idx is not None and existing_region.end_idx is not None:
                        existing_region.end_idx = max(existing_region.end_idx, region.end_idx)
                else:
                    # Replace with our region
                    self.region_map[new_start] = region
                    if new_start not in self.region_starts:
                        self.region_starts.append(new_start)
                    self.region_starts.sort()