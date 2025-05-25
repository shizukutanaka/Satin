"""
Advanced Task Scheduler for Satin
"""
import heapq
import time
import threading
import queue
import uuid
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Callable, Any, Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta

class TaskPriority(Enum):
    """Task priority levels"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3

class TaskStatus(Enum):
    """Task status"""
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()

@dataclass(order=True)
class ScheduledTask:
    """Task to be scheduled"""
    priority: int
    scheduled_time: float
    task_id: str = field(compare=False)
    func: Callable = field(compare=False)
    args: tuple = field(compare=False, default_factory=tuple)
    kwargs: dict = field(compare=False, default_factory=dict)
    status: TaskStatus = field(compare=False, default=TaskStatus.PENDING)
    result: Any = field(compare=False, default=None)
    error: Optional[Exception] = field(compare=False, default=None)
    retries: int = field(compare=False, default=0)
    max_retries: int = field(compare=False, default=0)
    created_at: float = field(compare=False, default_factory=time.time)
    
    def run(self):
        """Execute the task"""
        self.status = TaskStatus.RUNNING
        try:
            self.result = self.func(*self.args, **self.kwargs)
            self.status = TaskStatus.COMPLETED
            return self.result
        except Exception as e:
            self.error = e
            if self.retries < self.max_retries:
                self.retries += 1
                self.status = TaskStatus.PENDING
                return None
            self.status = TaskStatus.FAILED
            raise

class TaskScheduler:
    """Task scheduler with priority queue"""
    
    def __init__(self, num_workers: int = 4):
        self.ready_queue = queue.PriorityQueue()
        self.scheduled_tasks: List[Tuple[float, ScheduledTask]] = []
        self.tasks: Dict[str, ScheduledTask] = {}
        self.workers: List[threading.Thread] = []
        self.running = False
        self.lock = threading.RLock()
        self.worker_semaphore = threading.Semaphore(num_workers)
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
    
    def start(self) -> None:
        """Start the scheduler"""
        if self.running:
            return
            
        self.running = True
        self.scheduler_thread.start()
        
        # Start worker threads
        for i in range(self.worker_semaphore._value):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"Worker-{i}",
                daemon=True
            )
            self.workers.append(worker)
            worker.start()
    
    def stop(self, wait: bool = True) -> None:
        """Stop the scheduler"""
        if not self.running:
            return
            
        self.running = False
        
        # Wake up all threads
        with self.lock:
            for _ in range(len(self.workers)):
                self.ready_queue.put((0, None))
        
        if wait:
            self.scheduler_thread.join()
            for worker in self.workers:
                worker.join()
    
    def schedule(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        priority: Union[TaskPriority, int] = TaskPriority.NORMAL,
        delay: float = 0,
        max_retries: int = 0,
        task_id: Optional[str] = None
    ) -> str:
        """Schedule a task to run asynchronously"""
        if kwargs is None:
            kwargs = {}
            
        if isinstance(priority, TaskPriority):
            priority = priority.value
            
        task_id = task_id or str(uuid.uuid4())
        scheduled_time = time.time() + delay
        
        task = ScheduledTask(
            priority=-priority,  # Lower values are higher priority
            scheduled_time=scheduled_time,
            task_id=task_id,
            func=func,
            args=args,
            kwargs=kwargs,
            max_retries=max_retries
        )
        
        with self.lock:
            if delay <= 0:
                self.ready_queue.put((task.priority, task))
            else:
                heapq.heappush(self.scheduled_tasks, (scheduled_time, task))
            
            self.tasks[task_id] = task
        
        return task_id
    
    def schedule_periodic(
        self,
        func: Callable,
        interval: float,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        priority: Union[TaskPriority, int] = TaskPriority.NORMAL,
        max_retries: int = 0,
        task_id: Optional[str] = None
    ) -> str:
        """Schedule a task to run periodically"""
        if kwargs is None:
            kwargs = {}
            
        task_id = task_id or str(uuid.uuid4())
        
        def periodic_wrapper():
            try:
                func(*args, **kwargs)
            finally:
                # Reschedule the task
                if self.running:
                    self.schedule(
                        periodic_wrapper,
                        delay=interval,
                        priority=priority,
                        max_retries=max_retries,
                        task_id=task_id
                    )
        
        # Schedule the first execution
        return self.schedule(
            periodic_wrapper,
            delay=interval,
            priority=priority,
            task_id=task_id
        )
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a scheduled task"""
        with self.lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.CANCELLED
                    return True
        return False
    
    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """Get the status of a task"""
        task = self.tasks.get(task_id)
        return task.status if task else None
    
    def get_task_result(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """Get the result of a completed task"""
        start_time = time.time()
        
        while True:
            with self.lock:
                task = self.tasks.get(task_id)
                if not task:
                    return None
                    
                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    if task.status == TaskStatus.FAILED and task.error:
                        raise task.error
                    return task.result
            
            if timeout is not None and (time.time() - start_time) > timeout:
                raise TimeoutError(f"Timed out waiting for task {task_id}")
                
            time.sleep(0.1)
    
    def _scheduler_loop(self) -> None:
        """Main scheduler loop"""
        while self.running:
            now = time.time()
            
            with self.lock:
                # Check for scheduled tasks that are ready
                while self.scheduled_tasks and self.scheduled_tasks[0][0] <= now:
                    _, task = heapq.heappop(self.scheduled_tasks)
                    if task.status == TaskStatus.PENDING:
                        self.ready_queue.put((task.priority, task))
            
            # Sleep until the next scheduled task or 1 second
            next_run = max(0, (self.scheduled_tasks[0][0] - now) if self.scheduled_tasks else 1)
            time.sleep(min(1.0, next_run))
    
    def _worker_loop(self) -> None:
        """Worker thread loop"""
        while self.running:
            try:
                # Get a task with timeout to allow checking self.running
                try:
                    _, task = self.ready_queue.get(timeout=1)
                    if task is None:  # Shutdown signal
                        break
                except queue.Empty:
                    continue
                
                with self.worker_semaphore:
                    try:
                        task.run()
                    except Exception as e:
                        print(f"Error in task {task.task_id}: {e}")
                    finally:
                        self.ready_queue.task_done()
                        
            except Exception as e:
                print(f"Error in worker thread: {e}")

# Global scheduler instance
_scheduler = None

def get_scheduler() -> TaskScheduler:
    """Get or create the global task scheduler"""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
        _scheduler.start()
    return _scheduler

def schedule_task(
    func: Callable,
    args: tuple = (),
    kwargs: Optional[dict] = None,
    priority: Union[TaskPriority, int] = TaskPriority.NORMAL,
    delay: float = 0,
    max_retries: int = 0,
    task_id: Optional[str] = None
) -> str:
    """Schedule a task using the global scheduler"""
    return get_scheduler().schedule(
        func=func,
        args=args,
        kwargs=kwargs or {},
        priority=priority,
        delay=delay,
        max_retries=max_retries,
        task_id=task_id
    )

def schedule_periodic(
    func: Callable,
    interval: float,
    args: tuple = (),
    kwargs: Optional[dict] = None,
    priority: Union[TaskPriority, int] = TaskPriority.NORMAL,
    max_retries: int = 0,
    task_id: Optional[str] = None
) -> str:
    """Schedule a periodic task using the global scheduler"""
    return get_scheduler().schedule_periodic(
        func=func,
        interval=interval,
        args=args,
        kwargs=kwargs or {},
        priority=priority,
        max_retries=max_retries,
        task_id=task_id
    )

def shutdown_scheduler(wait: bool = True) -> None:
    """Shutdown the global scheduler"""
    global _scheduler
    if _scheduler is not None:
        _scheduler.stop(wait=wait)
        _scheduler = None
