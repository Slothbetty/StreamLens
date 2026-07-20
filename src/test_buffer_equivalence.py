#!/usr/bin/env python3
"""
Equivalence test: linear buffer vs Nonlinear Buffer.

Verifies that simulations with and without buffer.py (MultiRegionBuffer)
produce identical metrics during sequential chunk downloads — i.e. the
same graph output with 0.0% change expected.

Usage:
    # Run all tests
    python test_buffer_equivalence.py

    # Run quick test (single ABR algorithm, faster)
    python test_buffer_equivalence.py --quick
    
    # Test specific ABR algorithm
    python test_buffer_equivalence.py --abr bola
    
    # Verbose output
    python test_buffer_equivalence.py -v

The test ensures that:
- total_rebuffer_time matches exactly (0.0% change)
- rebuffer_count matches exactly
- total_play_time matches exactly
- played_utility matches exactly
- rebuffer_ratio matches exactly
- Buffer levels match at each download event
"""

import sys
import subprocess
import json
import unittest
from pathlib import Path
from run_comparison import run_simulation, parse_simulation_output


class TestBufferComparison(unittest.TestCase):
    """Test that buffer.py produces identical results to linear buffering."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test configuration once for all tests."""
        cls.test_dir = Path(__file__).parent
        cls.config = {
            'network': 'synthetic/network.json',
            'movie': 'synthetic/movie.json',
            'abr': 'bola',  # Will be overridden per test
            'network_multiplier': 1.0
        }
        # All ABR algorithms to test
        cls.abr_algorithms = ['bola', 'bolae', 'dynamic', 'dynamicdash', 'throughput']
        # Tolerance for floating point comparisons
        cls.tolerance = 1e-6
    
    def run_comparison(self, abr_algorithm):
        """Run comparison for a specific ABR algorithm and return metrics."""
        config = self.config.copy()
        config['abr'] = abr_algorithm
        
        # Run simulations
        metrics_without = run_simulation(use_buffer_py=False, config=config)
        metrics_with = run_simulation(use_buffer_py=True, config=config)
        
        self.assertIsNotNone(metrics_without, f"Simulation without buffer.py failed for {abr_algorithm}")
        self.assertIsNotNone(metrics_with, f"Simulation with buffer.py failed for {abr_algorithm}")
        
        return metrics_without, metrics_with
    
    def assert_metrics_equal(self, metrics_without, metrics_with, abr_algorithm):
        """Assert that metrics are identical (0.0% change)."""
        summary_without = metrics_without.get('summary', {})
        summary_with = metrics_with.get('summary', {})
        
        # Key metrics to compare
        metrics_to_check = [
            'total_rebuffer_time',
            'rebuffer_count',
            'total_play_time',
            'played_utility',
            'rebuffer_ratio'
        ]
        
        print(f"\n  Testing {abr_algorithm}:")
        print(f"  {'Metric':<30} {'Without buffer.py':<20} {'With buffer.py':<20} {'Status':<10}")
        print(f"  {'-'*80}")
        
        failures = []
        all_passed = True
        
        for key in metrics_to_check:
            val_without = summary_without.get(key, 0)
            val_with = summary_with.get(key, 0)
            
            # Handle zero values
            if val_without == 0 and val_with == 0:
                status = "PASS"
                print(f"  {key:<30} {str(val_without):<20} {str(val_with):<20} {status:<10}")
                continue  # Both zero, skip comparison
            
            # Calculate difference
            if isinstance(val_without, (int, float)) and isinstance(val_with, (int, float)):
                diff = abs(val_without - val_with)
                if diff > self.tolerance:
                    status = "FAIL"
                    all_passed = False
                    failures.append(
                        f"{abr_algorithm}.{key}: without={val_without}, with={val_with}, "
                        f"diff={diff}"
                    )
                else:
                    status = "PASS"
                    # Calculate percentage change for display
                    if val_without != 0:
                        pct_change = ((val_with - val_without) / val_without) * 100
                        status += f" ({pct_change:+.1f}%)"
                    else:
                        status += " (0.0%)"
            else:
                if val_without != val_with:
                    status = "FAIL"
                    all_passed = False
                    failures.append(
                        f"{abr_algorithm}.{key}: without={val_without}, with={val_with}"
                    )
                else:
                    status = "PASS"
            
            print(f"  {key:<30} {str(val_without):<20} {str(val_with):<20} {status:<10}")
        
        if failures:
            error_msg = f"\n  Metrics mismatch for {abr_algorithm}:\n  " + "\n  ".join(failures)
            self.fail(error_msg)
        else:
            print(f"  All metrics match for {abr_algorithm}")
    
    def test_bola_comparison(self):
        """Test that bola produces identical results."""
        print(f"\n{'='*85}")
        print(f"Test: bola comparison")
        print(f"{'='*85}")
        metrics_without, metrics_with = self.run_comparison('bola')
        self.assert_metrics_equal(metrics_without, metrics_with, 'bola')
    
    def test_bolae_comparison(self):
        """Test that bolae produces identical results."""
        print(f"\n{'='*85}")
        print(f"Test: bolae comparison")
        print(f"{'='*85}")
        metrics_without, metrics_with = self.run_comparison('bolae')
        self.assert_metrics_equal(metrics_without, metrics_with, 'bolae')
    
    def test_dynamic_comparison(self):
        """Test that dynamic produces identical results."""
        print(f"\n{'='*85}")
        print(f"Test: dynamic comparison")
        print(f"{'='*85}")
        metrics_without, metrics_with = self.run_comparison('dynamic')
        self.assert_metrics_equal(metrics_without, metrics_with, 'dynamic')
    
    def test_dynamicdash_comparison(self):
        """Test that dynamicdash produces identical results."""
        print(f"\n{'='*85}")
        print(f"Test: dynamicdash comparison")
        print(f"{'='*85}")
        metrics_without, metrics_with = self.run_comparison('dynamicdash')
        self.assert_metrics_equal(metrics_without, metrics_with, 'dynamicdash')
    
    def test_throughput_comparison(self):
        """Test that throughput produces identical results."""
        print(f"\n{'='*85}")
        print(f"Test: throughput comparison")
        print(f"{'='*85}")
        metrics_without, metrics_with = self.run_comparison('throughput')
        self.assert_metrics_equal(metrics_without, metrics_with, 'throughput')
    
    def test_all_abr_algorithms(self):
        """Test all ABR algorithms in one test."""
        print(f"\n{'='*85}")
        print(f"Test: All ABR algorithms comparison")
        print(f"{'='*85}")
        failures = []
        
        for abr in self.abr_algorithms:
            try:
                metrics_without, metrics_with = self.run_comparison(abr)
                summary_without = metrics_without.get('summary', {})
                summary_with = metrics_with.get('summary', {})
                
                # Check each metric
                metrics_to_check = [
                    'total_rebuffer_time',
                    'rebuffer_count',
                    'total_play_time',
                    'played_utility',
                    'rebuffer_ratio'
                ]
                
                print(f"\n  Testing {abr}:")
                for key in metrics_to_check:
                    val_without = summary_without.get(key, 0)
                    val_with = summary_with.get(key, 0)
                    
                    if val_without == 0 and val_with == 0:
                        continue
                    
                    if isinstance(val_without, (int, float)) and isinstance(val_with, (int, float)):
                        if abs(val_without - val_with) > self.tolerance:
                            failures.append(
                                f"{abr}.{key}: without={val_without}, with={val_with}, "
                                f"diff={abs(val_without - val_with)}"
                            )
                            print(f"    FAIL {key}: mismatch (without={val_without}, with={val_with})")
                        else:
                            pct = ((val_with - val_without) / val_without * 100) if val_without != 0 else 0.0
                            print(f"    PASS {key}: match ({pct:+.1f}%)")
                    else:
                        if val_without != val_with:
                            failures.append(
                                f"{abr}.{key}: without={val_without}, with={val_with}"
                            )
                            print(f"    FAIL {key}: mismatch (without={val_without}, with={val_with})")
                        else:
                            print(f"    PASS {key}: match")
            except Exception as e:
                failures.append(f"{abr}: {str(e)}")
                print(f"    FAIL Error: {str(e)}")
        
        if failures:
            error_msg = "\nMetrics mismatch detected:\n" + "\n".join(failures)
            self.fail(error_msg)
        else:
            print(f"\n  All ABR algorithms passed")
    
    def test_buffer_level_consistency(self):
        """Test that buffer levels are consistent throughout simulation."""
        print(f"\n{'='*85}")
        print(f"Test: Buffer level consistency")
        print(f"{'='*85}")
        # Test with bola as representative
        config = self.config.copy()
        config['abr'] = 'bola'
        
        metrics_without = run_simulation(use_buffer_py=False, config=config)
        metrics_with = run_simulation(use_buffer_py=True, config=config)
        
        self.assertIsNotNone(metrics_without)
        self.assertIsNotNone(metrics_with)
        
        # Check that download events have consistent buffer levels
        events_without = metrics_without.get('download_events', [])
        events_with = metrics_with.get('download_events', [])
        
        # Should have same number of events
        self.assertEqual(
            len(events_without), len(events_with),
            "Different number of download events"
        )
        
        print(f"\n  Checking {len(events_without)} download events...")
        mismatches = []
        
        # Check buffer levels match for each event
        for i, (event_without, event_with) in enumerate(zip(events_without, events_with)):
            bl_before_without = event_without.get('buffer_level_before', 0)
            bl_before_with = event_with.get('buffer_level_before', 0)
            bl_after_without = event_without.get('buffer_level_after', 0)
            bl_after_with = event_with.get('buffer_level_after', 0)
            
            if abs(bl_before_without - bl_before_with) > self.tolerance:
                mismatches.append(
                    f"Event {i} buffer_before: without={bl_before_without}, with={bl_before_with}"
                )
            
            if abs(bl_after_without - bl_after_with) > self.tolerance:
                mismatches.append(
                    f"Event {i} buffer_after: without={bl_after_without}, with={bl_after_with}"
                )
        
        if mismatches:
            error_msg = "Buffer level mismatches detected:\n  " + "\n  ".join(mismatches)
            self.fail(error_msg)
        else:
            print(f"  All buffer levels match across {len(events_without)} events")


class TestBufferComparisonQuick(unittest.TestCase):
    """Quick test that runs a single ABR algorithm for faster feedback."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test configuration."""
        cls.test_dir = Path(__file__).parent
        cls.config = {
            'network': 'synthetic/network.json',
            'movie': 'synthetic/movie.json',
            'abr': 'bola',
            'network_multiplier': 1.0
        }
        cls.tolerance = 1e-6
    
    def test_quick_comparison(self):
        """Quick test with bola algorithm."""
        print(f"\n{'='*85}")
        print(f"Quick Test: bola comparison")
        print(f"{'='*85}")
        from run_comparison import run_simulation
        
        metrics_without = run_simulation(use_buffer_py=False, config=self.config)
        metrics_with = run_simulation(use_buffer_py=True, config=self.config)
        
        self.assertIsNotNone(metrics_without, "Simulation without buffer.py failed")
        self.assertIsNotNone(metrics_with, "Simulation with buffer.py failed")
        
        summary_without = metrics_without.get('summary', {})
        summary_with = metrics_with.get('summary', {})
        
        print(f"\n  {'Metric':<30} {'Without buffer.py':<20} {'With buffer.py':<20} {'Status':<10}")
        print(f"  {'-'*80}")
        
        # Check key metrics
        for key in ['total_rebuffer_time', 'rebuffer_count', 'total_play_time', 
                    'played_utility', 'rebuffer_ratio']:
            val_without = summary_without.get(key, 0)
            val_with = summary_with.get(key, 0)
            
            if val_without == 0 and val_with == 0:
                print(f"  {key:<30} {str(val_without):<20} {str(val_with):<20} {'PASS':<10}")
                continue
            
            if isinstance(val_without, (int, float)) and isinstance(val_with, (int, float)):
                diff = abs(val_without - val_with)
                if diff > self.tolerance:
                    status = f"FAIL (diff={diff})"
                    self.fail(f"Metric {key} mismatch: without={val_without}, with={val_with}")
                else:
                    pct = ((val_with - val_without) / val_without * 100) if val_without != 0 else 0.0
                    status = f"PASS ({pct:+.1f}%)"
            else:
                if val_without != val_with:
                    status = "FAIL"
                    self.fail(f"Metric {key} mismatch: without={val_without}, with={val_with}")
                else:
                    status = "PASS"
            
            print(f"  {key:<30} {str(val_without):<20} {str(val_with):<20} {status:<10}")
        
        print(f"\n  Quick test passed")


if __name__ == '__main__':
    import argparse
    
    # Filter out our custom arguments before unittest.main() processes them
    custom_args = ['--quick', '--abr']
    sys_argv = sys.argv[:]
    quick_mode = '--quick' in sys_argv
    abr_arg = None
    verbose = '-v' in sys_argv or '--verbose' in sys_argv
    
    if '--abr' in sys_argv:
        idx = sys_argv.index('--abr')
        if idx + 1 < len(sys_argv):
            abr_arg = sys_argv[idx + 1]
            sys_argv.pop(idx)  # Remove --abr
            sys_argv.pop(idx)  # Remove value
    
    # Remove custom args
    sys_argv = [arg for arg in sys_argv if arg not in ['--quick', '--verbose']]
    
    if quick_mode:
        # Run only quick test
        suite = unittest.TestLoader().loadTestsFromTestCase(TestBufferComparisonQuick)
        runner = unittest.TextTestRunner(verbosity=2 if verbose else 1)
        result = runner.run(suite)
        print(f"\n{'='*85}")
        print(f"Summary: {'PASSED' if result.wasSuccessful() else 'FAILED'}")
        print(f"Tests run: {result.testsRun}, Failures: {len(result.failures)}, Errors: {len(result.errors)}")
        print(f"{'='*85}")
        sys.exit(0 if result.wasSuccessful() else 1)
    elif abr_arg:
        # Run test for specific ABR
        test_method_name = f'test_{abr_arg}_comparison'
        if not hasattr(TestBufferComparison, test_method_name):
            print(f"Error: No test found for ABR algorithm '{abr_arg}'", file=sys.stderr)
            print(f"Available algorithms: {', '.join(TestBufferComparison.abr_algorithms)}", file=sys.stderr)
            sys.exit(1)
        
        suite = unittest.TestSuite()
        suite.addTest(TestBufferComparison(test_method_name))
        runner = unittest.TextTestRunner(verbosity=2 if verbose else 1)
        result = runner.run(suite)
        print(f"\n{'='*85}")
        print(f"Summary: {'PASSED' if result.wasSuccessful() else 'FAILED'}")
        print(f"Tests run: {result.testsRun}, Failures: {len(result.failures)}, Errors: {len(result.errors)}")
        print(f"{'='*85}")
        sys.exit(0 if result.wasSuccessful() else 1)
    else:
        # Run all tests - restore original argv for unittest.main()
        # We'll use a custom test runner to add summary
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromModule(sys.modules[__name__])
        runner = unittest.TextTestRunner(verbosity=2 if verbose else 1)
        result = runner.run(suite)
        print(f"\n{'='*85}")
        print(f"Test Summary")
        print(f"{'='*85}")
        print(f"Tests run: {result.testsRun}")
        print(f"Failures: {len(result.failures)}")
        print(f"Errors: {len(result.errors)}")
        if result.failures:
            print(f"\nFailures:")
            for test, traceback in result.failures:
                print(f"  - {test}: {traceback.split(chr(10))[-2]}")
        if result.errors:
            print(f"\nErrors:")
            for test, traceback in result.errors:
                print(f"  - {test}: {traceback.split(chr(10))[-2]}")
        print(f"\nResult: {'ALL TESTS PASSED' if result.wasSuccessful() else 'SOME TESTS FAILED'}")
        print(f"{'='*85}")
        sys.exit(0 if result.wasSuccessful() else 1)
