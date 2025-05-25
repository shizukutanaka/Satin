"""
Demonstration of optimization utilities
"""
import time
import random
from pathlib import Path
import sys

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from main.optimize import monitor, cache_result, batch_process, enable_monitoring

def expensive_calculation(x: int) -> int:
    """Simulate an expensive calculation"""
    time.sleep(0.1)  # Simulate work
    return x * x

@cache_result(ttl=5)  # Cache for 5 seconds
def cached_calculation(x: int) -> int:
    """Expensive calculation with caching"""
    print(f"Calculating for {x}...")
    time.sleep(0.1)
    return x * x

def process_batch(batch: list) -> list:
    """Process a batch of items"""
    return [item * 2 for item in batch]

def main():
    # Enable performance monitoring
    enable_monitoring()
    
    # 1. Basic timing
    @monitor.timeit
    def example_function():
        time.sleep(0.2)
        return "Done"
    
    print("=== Basic Timing ===")
    result = example_function()
    print(f"Result: {result}")
    
    # 2. Caching example
    print("\n=== Caching Example ===")
    for i in [1, 2, 1, 3, 1]:
        print(f"cached_calculation({i}) = {cached_calculation(i)}")
    
    print("\nWaiting for cache to expire...")
    time.sleep(6)  # Wait for cache to expire
    print(f"cached_calculation(1) = {cached_calculation(1)}")
    
    # 3. Batch processing
    print("\n=== Batch Processing ===")
    items = list(range(1, 11))  # 1-10
    processed = batch_process(items, process_batch, batch_size=3)
    print(f"Processed items: {processed}")
    
    # Show performance metrics
    print("\n=== Performance Metrics ===")
    metrics = monitor.get_metrics()
    for name, stats in metrics.items():
        print(f"{name}: {stats}")

if __name__ == "__main__":
    main()
