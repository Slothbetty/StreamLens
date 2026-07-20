"""
GlobalState module for SABRE simulation.

This module contains the GlobalState singleton class that manages all global state
variables for the SABRE adaptive bitrate streaming simulation.
"""

class GlobalState:
    """
    Singleton class to hold all global state variables.
    This replaces the use of global variables throughout the codebase.
    """
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GlobalState, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            # Buffer and playback state
            self.buffer_contents = []
            self.buffer_fcc = 0
            self.next_segment = 0
            self.current_playback_pos = 0  # Current playback position in ms (for MultiRegionBuffer)
            self.total_play_time = 0
            self.last_seek_time = 0
            
            # Manifest and configuration
            self.manifest = None
            self.buffer_size = 0
            self.max_buffer_size = 0
            
            # Network and throughput
            self.throughput = None
            self.latency = None
            self.throughput_history = None
            self.network_total_time = 0
            self.sustainable_quality = 0
            
            
            # Statistics and metrics
            self.rebuffer_event_count = 0
            self.rebuffer_time = 0
            self.segment_rebuffer_time = 0
            # Wall-clock sim time (ms) each time rebuffer_event_count increments (for tooling / charts)
            self.rebuffer_event_starts_ms = []
            # Stall duration (ms) charged for that same increment (matches rebuffer_time summands)
            self.rebuffer_event_durations_ms = []
            self.played_utility = 0
            self.played_bitrate = 0
            self.total_bitrate_change = 0
            self.total_log_bitrate_change = 0
            self.switch_count = 0
            self.total_reaction_time = 0
            self.last_played = None
            
            # Quality and rampup
            self.rampup_origin = 0
            self.rampup_time = None
            self.rampup_threshold = None
            self.pending_quality_up = []
            
            # Estimation metrics
            self.overestimate_count = 0
            self.overestimate_average = 0
            self.goodestimate_count = 0
            self.goodestimate_average = 0
            self.estimate_average = 0
            
            # Seek events
            self.seek_events = []
            
            # Configuration
            self.verbose = False
            
            # Abandonment
            self.abandoned_to_quality = None
            
            # Reaction metrics
            self.reaction_metrics = []
            
            # Startup time
            self.startup_time = 0
            
            # MultiRegionBuffer for Nonlinear Buffering (initialized later when manifest is available)
            self.multi_region_buffer = None
            
            GlobalState._initialized = True


# Global instance
gs = GlobalState()
