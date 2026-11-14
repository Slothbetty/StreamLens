import os

import numpy as np

# Inference for the Comyco policy network. The weights were trained offline in a copy of this simulator,
# so only numpy is needed here.

# State rows: last bitrate, buffer level, throughput, download time, next chunk sizes, chunks left.
S_INFO = 6
S_LEN = 10  # Must be >= the number of bitrate levels.
BUFFER_NORM_FACTOR = 10.0
CHUNK_TIL_VIDEO_END_CAP = 48.0
M_IN_K = 1000.0


def load_weights(name):
    # Reads <name>_weights.npz next to this file; the path can be overridden with $<NAME>_WEIGHTS.
    path = os.environ.get(name.upper() + "_WEIGHTS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), name + "_weights.npz")
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def _linear(w, name, x):
    return w[name + ".weight"] @ x + w[name + ".bias"]


def scores(w, state):
    """Returns one score per quality level; the best quality is the argmax."""
    a_dim = w["pi_head.weight"].shape[0]
    parts = [
        _linear(w, "fc1_actor", state[0, -1:]),
        _linear(w, "fc2_actor", state[1, -1:]),
        _linear(w, "conv1_actor", state[2, :]),
        _linear(w, "conv2_actor", state[3, :]),
        _linear(w, "conv3_actor", state[4, :a_dim]),
        _linear(w, "fc3_actor", state[5, -1:]),
    ]
    h = np.maximum(_linear(w, "fc4_actor", np.maximum(np.concatenate(parts), 0.0)), 0.0)
    return _linear(w, "pi_head", h)


class StateBuilder:
    """Keeps the last S_LEN downloads and builds the network input from them."""

    def __init__(self, bitrates_kbps):
        self.bitrates = [float(b) for b in bitrates_kbps]
        self.max_br = max(self.bitrates)
        self.a_dim = len(self.bitrates)
        assert S_LEN >= self.a_dim
        self.state = np.zeros((S_INFO, S_LEN), dtype=np.float32)

    def push(self, quality, size_bits, delay_ms):
        self.state = np.roll(self.state, -1, axis=1)
        self.state[0, -1] = self.bitrates[quality] / self.max_br
        self.state[2, -1] = (size_bits / 8.0) / max(delay_ms, 1e-6) / M_IN_K  # MB/s
        self.state[3, -1] = delay_ms / M_IN_K / BUFFER_NORM_FACTOR

    def observe(self, buffer_ms, next_sizes_bits, chunks_left):
        state = self.state.copy()
        state[1, -1] = buffer_ms / M_IN_K / BUFFER_NORM_FACTOR
        state[4, :] = 0.0
        state[4, :self.a_dim] = np.asarray(next_sizes_bits, dtype=np.float32) / 8.0 / 1e6  # MB
        state[5, -1] = min(float(chunks_left), CHUNK_TIL_VIDEO_END_CAP) / CHUNK_TIL_VIDEO_END_CAP
        return state
