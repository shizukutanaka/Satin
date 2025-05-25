"""
Task Scheduler Demo for Satin
"""
import time
import random
from task_scheduler import (
    schedule_task,
    schedule_periodic,
    TaskPriority,
    get_scheduler,
    shutdown_scheduler
)

def simple_task(name: str) -> str:
    """A simple task that just prints a message"""
    print(f"[{time.ctime()}] Task '{name}' started")
    time.sleep(random.uniform(0.5, 2.0))  # Simulate work
    result = f"Result of {name}"
    print(f"[{time.ctime()}] Task '{name}' completed")
    return result

def failing_task():
    """A task that fails with a probability"""
    if random.random() < 0.3:  # 30% chance to fail
        raise ValueError("Random failure occurred!")
    return "Success"

def periodic_task(counter: list):
    """A periodic task that maintains state"""
    counter[0] += 1
    print(f"Periodic task run #{counter[0]} at {time.ctime()}")

def high_priority_task():
    """A high priority task"""
    print(f"[{time.ctime()}] HIGH PRIORITY TASK EXECUTED")

def main():
    print("=== Satin Task Scheduler Demo ===\n")
    
    # Start the scheduler
    scheduler = get_scheduler()
    
    try:
        # Schedule some simple tasks
        print("Scheduling simple tasks...")
        task1 = schedule_task(simple_task, ("Task 1",), priority=TaskPriority.NORMAL)
        task2 = schedule_task(simple_task, ("Task 2",), priority=TaskPriority.LOW)
        task3 = schedule_task(simple_task, ("Task 3 (High Priority)",), 
                            priority=TaskPriority.HIGH)
        
        # Schedule a delayed task
        print("\nScheduling a delayed task...")
        schedule_task(
            simple_task,
            ("Delayed Task",),
            delay=3.0,
            priority=TaskPriority.NORMAL
        )
        
        # Schedule a failing task with retries
        print("\nScheduling a task with retries...")
        schedule_task(
            failing_task,
            max_retries=3,
            priority=TaskPriority.NORMAL
        )
        
        # Schedule a periodic task
        print("\nScheduling a periodic task...")
        counter = [0]
        schedule_periodic(
            periodic_task,
            interval=2.0,
            args=(counter,),
            priority=TaskPriority.LOW
        )
        
        # Schedule some high priority tasks that will jump the queue
        print("\nScheduling high priority tasks...")
        for i in range(3):
            schedule_task(
                high_priority_task,
                delay=1.0 + i * 0.5,
                priority=TaskPriority.CRITICAL
            )
        
        # Wait for tasks to complete
        print("\nWaiting for tasks to complete (press Ctrl+C to exit)...")
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nShutting down scheduler...")
    finally:
        # Clean up
        shutdown_scheduler(wait=True)
        print("Scheduler shut down.")

if __name__ == "__main__":
    main()
