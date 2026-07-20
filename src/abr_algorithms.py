# Copyright (c) 2018, Kevin Spiteri
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import math
import os
from importlib.machinery import SourceFileLoader
from enum import Enum

from global_state import gs


def get_buffer_level(segment_time, buffer_contents, buffer_fcc):
    """Returns the current buffer level."""
    # If multi_region_buffer exists, use it; otherwise fall back to linear buffering
    if gs.multi_region_buffer is not None:
        # Pass buffer_fcc parameter to match linear buffering behavior
        return gs.multi_region_buffer.get_buffer_level(buffer_fcc)
    return segment_time * len(buffer_contents) - buffer_fcc


class ThroughputHistory:
    def __init__(self, config):
        pass

    def push(self, time, tput, lat):
        raise NotImplementedError


class SessionInfo:

    def __init__(self):
        pass

    def get_throughput(self):
        return gs.throughput

    def get_buffer_contents(self):
        # If multi_region_buffer exists, return chunks from buffer; otherwise return buffer_contents
        if gs.multi_region_buffer is not None:
            playable_chunks = gs.multi_region_buffer.get_contiguous_chunks_from_current_position()
            # Convert to same format as buffer_contents: list of (segment_index, quality) tuples
            # For compatibility, we'll return chunks with dummy segment indices
            # This is mainly used for replacement logic
            result = []
            current_pos = gs.current_playback_pos
            for i, quality in enumerate(playable_chunks):
                seg_idx = int((current_pos + i * gs.manifest.segment_time) / gs.manifest.segment_time)
                result.append((seg_idx, quality))
            return result
        return gs.buffer_contents[:]


session_info = SessionInfo()


class Abr:

    session = session_info

    def __init__(self, config):
        pass

    def get_quality_delay(self, segment_index):
        raise NotImplementedError

    def get_first_quality(self):
        return 0

    def report_delay(self, delay):
        pass

    def report_download(self, metrics, is_replacment):
        pass

    def report_seek(self, where):
        pass

    def check_abandon(self, progress, buffer_level):
        return None

    def quality_from_throughput(self, tput): # Note: This function calculates the quality level based on the throughput.
        p = gs.manifest.segment_time

        quality = 0
        while (
            quality + 1 < len(gs.manifest.bitrates)
            and gs.latency + p * gs.manifest.bitrates[quality + 1] / tput <= p
        ):
            quality += 1
        return quality


class Replacement:

    session = session_info

    def check_replace(self, quality):
        return None

    def check_abandon(self, progress, buffer_level):
        return None


average_list = {}
abr_list = {}


class SlidingWindow(ThroughputHistory):

    default_window_size = [3]
    max_store = 20

    def __init__(self, config):
        if "window_size" in config and config["window_size"] != None:
            self.window_size = config["window_size"]
        else:
            self.window_size = SlidingWindow.default_window_size

        # TODO: init somewhere else?
        gs.throughput = None
        gs.latency = None

        self.last_throughputs = []
        self.last_latencies = []

    def push(self, time, tput, lat):
        self.last_throughputs += [tput]
        self.last_throughputs = self.last_throughputs[-SlidingWindow.max_store :]

        self.last_latencies += [lat]
        self.last_latencies = self.last_latencies[-SlidingWindow.max_store :]

        tput = None
        lat = None
        for ws in self.window_size:
            sample = self.last_throughputs[-ws:]
            t = sum(sample) / len(sample)
            tput = t if tput == None else min(tput, t)  # conservative min
            sample = self.last_latencies[-ws:]
            l = sum(sample) / len(sample)
            lat = l if lat == None else max(lat, l)  # conservative max
        gs.throughput = tput
        gs.latency = lat


average_list["sliding"] = SlidingWindow


class Ewma(ThroughputHistory):

    # for throughput:
    default_half_life = [8000, 3000]

    def __init__(self, config):
        # TODO: init somewhere else?
        gs.throughput = None
        gs.latency = None

        if "half_life" in config and config["half_life"] != None:
            self.half_life = [h * 1000 for h in config["half_life"]]
        else:
            self.half_life = Ewma.default_half_life

        self.latency_half_life = [h / gs.manifest.segment_time for h in self.half_life]

        self.throughput = [0] * len(self.half_life)
        self.weight_throughput = 0
        self.latency = [0] * len(self.half_life)
        self.weight_latency = 0

    def push(self, time, tput, lat):
        for i in range(len(self.half_life)):
            alpha = math.pow(0.5, time / self.half_life[i])
            self.throughput[i] = alpha * self.throughput[i] + (1 - alpha) * tput
            alpha = math.pow(0.5, 1 / self.latency_half_life[i])
            self.latency[i] = alpha * self.latency[i] + (1 - alpha) * lat

        self.weight_throughput += time
        self.weight_latency += 1

        tput = None
        lat = None
        for i in range(len(self.half_life)):
            zero_factor = 1 - math.pow(0.5, self.weight_throughput / self.half_life[i])
            t = self.throughput[i] / zero_factor
            tput = t if tput == None else min(tput, t)  # conservative case is min
            zero_factor = 1 - math.pow(
                0.5, self.weight_latency / self.latency_half_life[i]
            )
            l = self.latency[i] / zero_factor
            lat = l if lat == None else max(lat, l)  # conservative case is max
        gs.throughput = tput
        gs.latency = lat


average_list["ewma"] = Ewma
average_default = "ewma"


class Bola(Abr):

    def __init__(self, config):
        utility_offset = -math.log(gs.manifest.bitrates[0])  # so utilities[0] = 0
        self.utilities = [math.log(b) + utility_offset for b in gs.manifest.bitrates]

        self.gp = config["gp"]
        self.buffer_size = config["buffer_size"]
        self.abr_osc = config["abr_osc"]
        self.abr_basic = config["abr_basic"]
        self.Vp = (self.buffer_size - gs.manifest.segment_time) / (
            self.utilities[-1] + self.gp
        )

        self.last_seek_index = 0  # TODO: need to update when multiple seeks
        self.last_quality = 0

        if gs.verbose:
            for q in range(len(gs.manifest.bitrates)):
                b = gs.manifest.bitrates[q]
                u = self.utilities[q]
                l = self.Vp * (self.gp + u)
                if q == 0:
                    print("%d %d" % (q, l))
                else:
                    qq = q - 1
                    bb = gs.manifest.bitrates[qq]
                    uu = self.utilities[qq]
                    ll = self.Vp * (self.gp + (b * uu - bb * u) / (b - bb))
                    print("%d %d    <- %d %d" % (q, l, qq, ll))

    def quality_from_buffer(self): # Note: This function calculates the quality level based on the buffer level.
        level = get_buffer_level(gs.manifest.segment_time, gs.buffer_contents, gs.buffer_fcc)
        quality = 0
        score = None
        for q in range(len(gs.manifest.bitrates)):
            s = (self.Vp * (self.utilities[q] + self.gp) - level) / gs.manifest.bitrates[q]
            if score == None or s > score:
                quality = q
                score = s
        return quality

    def get_quality_delay(self, segment_index):
        if not self.abr_basic:
            t = min(
                segment_index - self.last_seek_index,
                len(gs.manifest.segments) - segment_index,
            )
            t = max(t / 2, 3)
            t = t * gs.manifest.segment_time
            buffer_size = min(self.buffer_size, t)
            self.Vp = (buffer_size - gs.manifest.segment_time) / (
                self.utilities[-1] + self.gp
            )

        quality = self.quality_from_buffer()
        delay = 0

        if quality > self.last_quality:
            quality_t = self.quality_from_throughput(gs.throughput)
            if quality <= quality_t:
                delay = 0
            elif self.last_quality > quality_t:
                quality = self.last_quality
                delay = 0
            else:
                if not self.abr_osc:
                    quality = quality_t + 1 # Note: Without oscillation control, the algorithm prioritizes a higher quality level, assuming the buffer can handle the extra risk.
                    delay = 0
                else:
                    quality = quality_t
                    # now need to calculate delay
                    b = gs.manifest.bitrates[quality]
                    u = self.utilities[quality]
                    # bb = gs.manifest.bitrates[quality + 1]
                    # uu = self.utilities[quality + 1]
                    # l = self.Vp * (self.gp + (bb * u - b * uu) / (bb - b))
                    l = self.Vp * (self.gp + u)  ##########
                    delay = max(0, get_buffer_level(gs.manifest.segment_time, gs.buffer_contents, gs.buffer_fcc) - l)
                    if quality == len(gs.manifest.bitrates) - 1:
                        delay = 0
                    # delay = 0 ###########

        self.last_quality = quality
        return (quality, delay)

    def report_seek(self, where):
        # Compute the segment index corresponding to the new playback position.
        self.last_seek_index = math.floor(where / gs.manifest.segment_time)
        # Seek Update Note:
        # Reset the last chosen quality to a safe starting point.
        # Doesn't affect the simluation result, due to the buffer level is cleaned up.
        # The quality_from_buffer() in get_quality_delay() will re-calculate the quality level and update the self.last_quality into 0.
        self.last_quality = self.get_first_quality()

    def check_abandon(self, progress, buffer_level):
        if self.abr_basic:
            return None

        remain = progress.size - progress.downloaded
        if progress.downloaded <= 0 or remain <= 0:
            return None

        abandon_to = None
        score = (
            self.Vp * (self.gp + self.utilities[progress.quality]) - buffer_level
        ) / remain
        if score < 0:
            return  # TODO: check

        for q in range(progress.quality):
            other_size = (
                progress.size
                * gs.manifest.bitrates[q]
                / gs.manifest.bitrates[progress.quality]
            )
            other_score = (
                self.Vp * (self.gp + self.utilities[q]) - buffer_level
            ) / other_size
            if other_size < remain and other_score > score:
                # check size: see comment in BolaEnh.check_abandon()
                score = other_score
                abandon_to = q

        if abandon_to != None:
            self.last_quality = abandon_to

        return abandon_to


abr_list["bola"] = Bola


class BolaEnh(Abr):

    minimum_buffer = 10000
    minimum_buffer_per_level = 2000
    low_buffer_safety_factor = 0.5
    low_buffer_safety_factor_init = 0.9

    class State(Enum):
        STARTUP = 1
        STEADY = 2

    def __init__(self, config):
        config_buffer_size = config["buffer_size"]
        self.abr_osc = config["abr_osc"]
        self.no_ibr = config["no_ibr"]

        utility_offset = 1 - math.log(gs.manifest.bitrates[0])  # so utilities[0] = 1
        self.utilities = [math.log(b) + utility_offset for b in gs.manifest.bitrates]

        if self.no_ibr:
            self.gp = config["gp"] - 1  # to match BOLA Basic
            buffer = config["buffer_size"]
            self.Vp = (buffer - gs.manifest.segment_time) / (self.utilities[-1] + self.gp)
        else:
            buffer = BolaEnh.minimum_buffer
            buffer += BolaEnh.minimum_buffer_per_level * len(gs.manifest.bitrates)
            buffer = max(buffer, config_buffer_size)
            self.gp = (self.utilities[-1] - 1) / (buffer / BolaEnh.minimum_buffer - 1)
            self.Vp = BolaEnh.minimum_buffer / self.gp
            # equivalently:
            # self.Vp = (buffer - BolaEnh.minimum_buffer) / (math.log(gs.manifest.bitrates[-1] / gs.manifest.bitrates[0]))
            # self.gp = BolaEnh.minimum_buffer / self.Vp

        self.state = BolaEnh.State.STARTUP
        self.placeholder = 0
        self.last_quality = 0
        self._seek_hit_prefetch = False

        if gs.verbose:
            for q in range(len(gs.manifest.bitrates)):
                b = gs.manifest.bitrates[q]
                u = self.utilities[q]
                l = self.Vp * (self.gp + u)
                if q == 0:
                    print("%d %d" % (q, l))
                else:
                    qq = q - 1
                    bb = gs.manifest.bitrates[qq]
                    uu = self.utilities[qq]
                    ll = self.Vp * (self.gp + (b * uu - bb * u) / (b - bb))
                    print("%d %d    <- %d %d" % (q, l, qq, ll))

    def quality_from_buffer(self, level):
        if level == None:
            level = get_buffer_level(gs.manifest.segment_time, gs.buffer_contents, gs.buffer_fcc)
        quality = 0
        score = None
        for q in range(len(gs.manifest.bitrates)):
            s = (self.Vp * (self.utilities[q] + self.gp) - level) / gs.manifest.bitrates[q]
            if score == None or s > score:
                quality = q
                score = s
        return quality

    def quality_from_buffer_placeholder(self):
        return self.quality_from_buffer(get_buffer_level(gs.manifest.segment_time, gs.buffer_contents, gs.buffer_fcc) + self.placeholder)

    def min_buffer_for_quality(self, quality):
        bitrate = gs.manifest.bitrates[quality]
        utility = self.utilities[quality]

        level = 0
        for q in range(quality):
            # for each bitrates[q] less than bitrates[quality],
            # BOLA should prefer bitrates[quality]
            # (unless bitrates[q] has higher utility)
            if self.utilities[q] < self.utilities[quality]:
                b = gs.manifest.bitrates[q]
                u = self.utilities[q]
                l = self.Vp * (self.gp + (bitrate * u - b * utility) / (bitrate - b))
                level = max(level, l)
        return level

    def max_buffer_for_quality(self, quality):
        return self.Vp * (self.utilities[quality] + self.gp)

    def get_quality_delay(self, segment_index):
        buffer_level = get_buffer_level(gs.manifest.segment_time, gs.buffer_contents, gs.buffer_fcc)

        if self.state == BolaEnh.State.STARTUP:
            if gs.throughput == None:
                return (self.last_quality, 0)
            self.state = BolaEnh.State.STEADY
            self.ibr_safety = BolaEnh.low_buffer_safety_factor_init
            quality = self.quality_from_throughput(gs.throughput)
            if getattr(self, '_seek_hit_prefetch', False):
                # Seek landed on prefetch content: throughput estimate may be stale
                # (no fresh download at the seek point). Use 2 quality levels below
                # the throughput-based estimate for the placeholder — this avoids
                # STEADY quality overselection while keeping utility reasonable.
                self._seek_hit_prefetch = False
                conservative_q = max(0, quality - 2)
                self.placeholder = max(0, self.min_buffer_for_quality(conservative_q) - buffer_level)
            else:
                self.placeholder = self.min_buffer_for_quality(quality) - buffer_level
                self.placeholder = max(0, self.placeholder)
            return (quality, 0)

        quality = self.quality_from_buffer_placeholder()
        quality_t = self.quality_from_throughput(gs.throughput)
        if quality > self.last_quality and quality > quality_t:
            quality = max(self.last_quality, quality_t)
            if not self.abr_osc:
                quality += 1

        max_level = self.max_buffer_for_quality(quality)

        if quality > 0:
            q = quality
            b = gs.manifest.bitrates[q]
            u = self.utilities[q]
            qq = q - 1
            bb = gs.manifest.bitrates[qq]
            uu = self.utilities[qq]
            # max_level = self.Vp * (self.gp + (b * uu - bb * u) / (b - bb))

        delay = buffer_level + self.placeholder - max_level
        if delay > 0:
            if delay <= self.placeholder:
                self.placeholder -= delay
                delay = 0
            else:
                delay -= self.placeholder
                self.placeholder = 0
        else:
            delay = 0

        if quality == len(gs.manifest.bitrates) - 1:
            delay = 0

        # insufficient buffer rule
        if not self.no_ibr:
            safe_size = self.ibr_safety * (buffer_level - gs.latency) * gs.throughput
            self.ibr_safety *= BolaEnh.low_buffer_safety_factor_init
            self.ibr_safety = max(self.ibr_safety, BolaEnh.low_buffer_safety_factor)
            for q in range(quality):
                if gs.manifest.bitrates[q + 1] * gs.manifest.segment_time > safe_size:
                    # print('InsufficientBufferRule %d -> %d' % (quality, q))
                    quality = q
                    delay = 0
                    min_level = self.min_buffer_for_quality(quality)
                    max_placeholder = max(0, min_level - buffer_level)
                    self.placeholder = min(max_placeholder, self.placeholder)
                    break

        # print('ph=%d' % self.placeholder)
        return (quality, delay)

    def report_delay(self, delay):
        self.placeholder += delay

    def report_download(self, metrics, is_replacment):
        self.last_quality = metrics.quality
        level = get_buffer_level(gs.manifest.segment_time, gs.buffer_contents, gs.buffer_fcc)

        if metrics.abandon_to_quality == None:

            if is_replacment:
                self.placeholder += gs.manifest.segment_time
            else:
                # make sure placeholder is not too large relative to download
                level_was = level + metrics.time
                max_effective_level = self.max_buffer_for_quality(metrics.quality)
                max_placeholder = max(0, max_effective_level - level_was)
                self.placeholder = min(self.placeholder, max_placeholder)

                # make sure placeholder not too small (can happen when decision not taken by BOLA)
                if level > 0:
                    # we don't want to inflate placeholder when rebuffering
                    min_effective_level = self.min_buffer_for_quality(metrics.quality)
                    # min_effective_level < max_effective_level
                    min_placeholder = min_effective_level - level_was
                    self.placeholder = max(self.placeholder, min_placeholder)
                # else: no need to deflate placeholder for 0 buffer - empty buffer handled

        elif not is_replacment:  # do nothing if we abandoned a replacement
            # abandonment indicates something went wrong - lower placeholder to conservative level
            if metrics.abandon_to_quality > 0:
                want_level = self.min_buffer_for_quality(metrics.abandon_to_quality)
            else:
                want_level = BolaEnh.minimum_buffer
            max_placeholder = max(0, want_level - level)
            self.placeholder = min(self.placeholder, max_placeholder)

    def report_seek(self, where):
        self.state = BolaEnh.State.STARTUP
        self.placeholder = 0
        self.last_quality = self.get_first_quality()
        self.last_seek_index = math.floor(where / gs.manifest.segment_time)
        self._seek_hit_prefetch = False

    def check_abandon(self, progress, buffer_level):
        remain = progress.size - progress.downloaded
        if progress.downloaded <= 0 or remain <= 0:
            return None

        # abandon leads to new latency, so estimate what current status is after latency
        bl = max(0, buffer_level + self.placeholder - progress.time_to_first_bit)
        tp = progress.downloaded / (progress.time - progress.time_to_first_bit)
        sz = remain - progress.time_to_first_bit * tp
        if sz <= 0:
            return None

        abandon_to = None
        score = (self.Vp * (self.gp + self.utilities[progress.quality]) - bl) / sz

        for q in range(progress.quality):
            other_size = (
                progress.size
                * gs.manifest.bitrates[q]
                / gs.manifest.bitrates[progress.quality]
            )
            other_score = (self.Vp * (self.gp + self.utilities[q]) - bl) / other_size
            if other_size < sz and other_score > score:
                # check size:
                # if remaining bits in this download are less than new download, why switch?
                # IMPORTANT: this check is NOT subsumed in score check:
                # if sz < other_size and bl is large, original score suffers larger penalty
                # print('abandon bl=%d=%d+%d-%d %d->%d score:%d->%s' % (progress.quality, bl, buffer_level, self.placeholder, progress.time_to_first_bit, q, score, other_score))
                score = other_score
                abandon_to = q

        return abandon_to


abr_list["bolae"] = BolaEnh
abr_default = "bolae"


class ThroughputRule(Abr):

    safety_factor = 0.9
    low_buffer_safety_factor = 0.5
    low_buffer_safety_factor_init = 0.9
    abandon_multiplier = 1.8
    abandon_grace_time = 500

    def __init__(self, config):
        self.ibr_safety = ThroughputRule.low_buffer_safety_factor_init
        self.no_ibr = config["no_ibr"]

    def get_quality_delay(self, segment_index):
        quality = self.quality_from_throughput(
            gs.throughput * ThroughputRule.safety_factor
        )

        if not self.no_ibr:
            # insufficient buffer rule
            safe_size = self.ibr_safety * (get_buffer_level(gs.manifest.segment_time, gs.buffer_contents, gs.buffer_fcc) - gs.latency) * gs.throughput
            self.ibr_safety *= ThroughputRule.low_buffer_safety_factor_init
            self.ibr_safety = max(
                self.ibr_safety, ThroughputRule.low_buffer_safety_factor
            )
            for q in range(quality):
                if gs.manifest.bitrates[q + 1] * gs.manifest.segment_time > safe_size:
                    quality = q
                    break

        return (quality, 0)

    def check_abandon(self, progress, buffer_level):
        quality = None  # no abandon

        dl_time = progress.time - progress.time_to_first_bit
        if progress.time >= ThroughputRule.abandon_grace_time and dl_time > 0:
            tput = progress.downloaded / dl_time
            size_left = progress.size - progress.downloaded
            estimate_time_left = size_left / tput
            if (
                progress.time + estimate_time_left
                > ThroughputRule.abandon_multiplier * gs.manifest.segment_time
            ):
                quality = self.quality_from_throughput(
                    tput * ThroughputRule.safety_factor
                )
                estimate_size = (
                    progress.size
                    * gs.manifest.bitrates[quality]
                    / gs.manifest.bitrates[progress.quality]
                )
                if quality >= progress.quality or estimate_size >= size_left:
                    quality = None

        return quality

    def report_seek(self, where):
        # Reset internal throughput-specific state.
        self.ibr_safety = ThroughputRule.low_buffer_safety_factor_init


abr_list["throughput"] = ThroughputRule


class Dynamic(Abr):

    low_buffer_threshold = 10000

    def __init__(self, config):
        self.bola = Bola(config)
        self.tput = ThroughputRule(config)

        self.is_bola = False

    def get_quality_delay(self, segment_index):
        level = get_buffer_level(gs.manifest.segment_time, gs.buffer_contents, gs.buffer_fcc)

        b = self.bola.get_quality_delay(segment_index)
        t = self.tput.get_quality_delay(segment_index)

        if self.is_bola:
            if level < Dynamic.low_buffer_threshold and b[0] < t[0]:
                self.is_bola = False
        else:
            if level > Dynamic.low_buffer_threshold and b[0] >= t[0]:
                self.is_bola = True

        return b if self.is_bola else t

    def get_first_quality(self):
        if self.is_bola:
            return self.bola.get_first_quality()
        else:
            return self.tput.get_first_quality()

    def report_delay(self, delay):
        self.bola.report_delay(delay)
        self.tput.report_delay(delay)

    def report_download(self, metrics, is_replacment):
        self.bola.report_download(metrics, is_replacment)
        self.tput.report_download(metrics, is_replacment)
        if is_replacment:
            self.is_bola = False

    def check_abandon(self, progress, buffer_level):
        if False and self.is_bola:
            return self.bola.check_abandon(progress, buffer_level)
        else:
            return self.tput.check_abandon(progress, buffer_level)

    def report_seek(self, where):
        # Delegate the seek notification to both underlying strategies.
        self.bola.report_seek(where)
        self.tput.report_seek(where)


abr_list["dynamic"] = Dynamic


class DynamicDash(Abr):

    def __init__(self, config):
        self.bola = BolaEnh(config)
        self.tput = ThroughputRule(config)

        buffer_size = config["buffer_size"]
        self.low_threshold = (buffer_size - gs.manifest.segment_time) / 2
        self.high_threshold = (buffer_size - gs.manifest.segment_time) - 100
        self.low_threshold = 5000
        self.high_threshold = 10000
        ######################## TODO
        self.is_bola = False

    def get_quality_delay(self, segment_index):
        level = get_buffer_level(gs.manifest.segment_time, gs.buffer_contents, gs.buffer_fcc)
        if self.is_bola and level < self.low_threshold:
            self.is_bola = False
        elif not self.is_bola and level > self.high_threshold:
            self.is_bola = True

        if self.is_bola:
            return self.bola.get_quality_delay(segment_index)
        else:
            return self.tput.get_quality_delay(segment_index)

    def get_first_quality(self):
        if self.is_bola:
            return self.bola.get_first_quality()
        else:
            return self.tput.get_first_quality()

    def report_delay(self, delay):
        self.bola.report_delay(delay)
        self.tput.report_delay(delay)

    def report_download(self, metrics, is_replacment):
        self.bola.report_download(metrics, is_replacment)
        self.tput.report_download(metrics, is_replacment)

    def check_abandon(self, progress, buffer_level):
        if self.is_bola:
            return self.bola.check_abandon(progress, buffer_level)
        else:
            return self.tput.check_abandon(progress, buffer_level)

    def report_seek(self, where):
        # Notify both strategies of the seek event.
        self.bola.report_seek(where)
        self.tput.report_seek(where)


abr_list["dynamicdash"] = DynamicDash


class Bba(Abr):

    def __init__(self, config):
        pass

    def get_quality_delay(self, segment_index):
        raise NotImplementedError

    def report_delay(self, delay):
        pass

    def report_download(self, metrics, is_replacment):
        pass

    def report_seek(self, where):
        pass


abr_list["bba"] = Bba


class NoReplace(Replacement):
    pass


# TODO: different classes instead of strategy
class Replace(Replacement):

    def __init__(self, strategy):
        self.strategy = strategy
        self.replacing = None
        # self.replacing is either None or -ve index to buffer_contents

    def check_replace(self, quality):
        self.replacing = None

        # Get buffer contents - use multi_region_buffer if available
        if gs.multi_region_buffer is not None:
            # Use MultiRegionBuffer to get playable chunks
            playable_chunks = gs.multi_region_buffer.get_contiguous_chunks_from_current_position()
            buffer_list = playable_chunks  # List of quality values
        else:
            # Fallback to buffer_contents (for compatibility when multi_region_buffer not enabled)
            buffer_list = [q for (_seg_idx, q) in gs.buffer_contents]

        if self.strategy == 0:

            skip = math.ceil(1.5 + gs.buffer_fcc / gs.manifest.segment_time)
            # print('skip = %d  fcc = %d' % (skip, gs.buffer_fcc))
            for i in range(skip, len(buffer_list)):
                q_i = buffer_list[i]
                if q_i < quality:
                    self.replacing = i - len(buffer_list)
                    break

            # if self.replacing == None:
            #    print('no repl:  0/%d' % len(buffer_list))
            # else:
            #    print('replace: %d/%d' % (self.replacing, len(buffer_list)))

        elif self.strategy == 1:

            skip = math.ceil(1.5 + gs.buffer_fcc / gs.manifest.segment_time)
            # print('skip = %d  fcc = %d' % (skip, gs.buffer_fcc))
            for i in range(len(buffer_list) - 1, skip - 1, -1):
                q_i = buffer_list[i]
                if q_i < quality:
                    self.replacing = i - len(buffer_list)
                    break

            # if self.replacing == None:
            #    print('no repl:  0/%d' % len(buffer_list))
            # else:
            #    print('replace: %d/%d' % (self.replacing, len(buffer_list)))

        else:
            pass

        return self.replacing

    def check_abandon(self, progress, buffer_level):
        if self.replacing == None:
            return None
        if buffer_level + gs.manifest.segment_time * self.replacing <= 0:
            return -1
        return None


class AbrInput(Abr):

    def __init__(self, path, config):
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.abr_module = SourceFileLoader(self.name, path).load_module()
        self.abr_class = getattr(self.abr_module, self.name)
        self.abr_class.session = session_info
        self.abr = self.abr_class(config)

    def get_quality_delay(self, segment_index):
        return self.abr.get_quality_delay(segment_index)

    def get_first_quality(self):
        return self.abr.get_first_quality()

    def report_delay(self, delay):
        self.abr.report_delay(delay)

    def report_download(self, metrics, is_replacment):
        self.abr.report_download(metrics, is_replacment)

    def report_seek(self, where):
        self.abr.report_seek(where)

    def check_abandon(self, progress, buffer_level):
        return self.abr.check_abandon(progress, buffer_level)


class ReplacementInput(Replacement):

    def __init__(self, path):
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.replacement_module = SourceFileLoader(self.name, path).load_module()
        self.replacement_class = getattr(self.replacement_module, self.name)
        self.replacement_class.session = session_info
        self.replacement = self.replacement_class()

    def check_replace(self, quality):
        return self.replacement.check_replace(quality)

    def check_abandon(self, progress, buffer_level):
        return self.replacement.check_abandon(progress, buffer_level)
