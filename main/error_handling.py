"""
Advanced error handling and recovery system for Satin
"""
import sys
import traceback
from typing import Callable, TypeVar, Any, Optional, Type, Dict
from functools import wraps
from pathlib import Path
import json
from datetime import datetime

T = TypeVar('T')

class SatinError(Exception):
    """Base exception class for Satin"""
    def __init__(self, message: str, code: int = 500, details: Optional[Dict] = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)

class RetryableError(SatinError):
    """Raised when an operation can be retried"""
    def __init__(self, message: str, retry_after: int = 5, max_retries: int = 3):
        super().__init__(message, code=429)  # 429 Too Many Requests
        self.retry_after = retry_after
        self.max_retries = max_retries

class RetryStrategy:
    """Strategy configuration for retry logic"""
    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        exceptions: tuple = (Exception,),
        initial_delay: float = 1.0,
        max_delay: float = 60.0
    ):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.exceptions = exceptions
        self.initial_delay = initial_delay
        self.max_delay = max_delay

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number"""
        delay = self.initial_delay * (self.backoff_factor ** attempt)
        return min(delay, self.max_delay)

class ValidationError(SatinError):
    """Raised when input validation fails"""
    def __init__(self, message: str, field: Optional[str] = None):
        details = {'field': field} if field else {}
        super().__init__(message, code=400, details=details)

class ErrorHandler:
    """Global error handler and recovery manager"""
    
    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file or str(Path('logs') / 'error.log')
        self._handlers = {}
        self._setup_default_handlers()
    
    def _setup_default_handlers(self) -> None:
        """Register default exception handlers"""
        self.register_handler(SatinError, self._handle_satin_error)
        self.register_handler(RetryableError, self._handle_retryable_error)
        self.register_handler(ValidationError, self._handle_validation_error)
        self.register_handler(Exception, self._handle_generic_error)
    
    def register_handler(
        self, 
        exception_type: Type[Exception], 
        handler: Callable[[Exception], Any]
    ) -> None:
        """Register a custom exception handler"""
        self._handlers[exception_type] = handler
    
    def handle_error(self, error: Exception) -> Any:
        """Handle an exception using the appropriate handler"""
        # Find the most specific handler for this exception type
        handler = self._find_handler(type(error))
        
        # Log the error
        self._log_error(error)
        
        # Call the handler
        return handler(error)
    
    def _find_handler(self, exc_type: Type[Exception]) -> Callable:
        """Find the most specific handler for an exception type"""
        for et in self._handlers:
            if issubclass(exc_type, et):
                return self._handlers[et]
        return self._handle_generic_error
    
    def _log_error(self, error: Exception) -> None:
        """Log error details to file"""
        error_info = {
            'timestamp': datetime.utcnow().isoformat(),
            'type': error.__class__.__name__,
            'message': str(error),
            'traceback': traceback.format_exc()
        }
        
        # Add additional details if available
        if hasattr(error, 'details'):
            error_info['details'] = getattr(error, 'details')
        
        # Ensure log directory exists
        log_path = Path(self.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Append to log file
        with open(log_path, 'a', encoding='utf-8') as f:
            json.dump(error_info, f, ensure_ascii=False)
            f.write('\n')
    
    # Default handlers
    def _handle_satin_error(self, error: SatinError) -> Dict:
        """Handle Satin-specific errors"""
        return {
            'error': error.message,
            'code': error.code,
            'details': error.details
        }
    
    def _handle_retryable_error(self, error: RetryableError) -> Dict:
        """Handle retryable errors"""
        return {
            'error': error.message,
            'code': error.code,
            'retry_after': error.retry_after,
            'max_retries': error.max_retries
        }
    
    def _handle_validation_error(self, error: ValidationError) -> Dict:
        """Handle validation errors"""
        return {
            'error': error.message,
            'code': error.code,
            'field': error.details.get('field')
        }
    
    def _handle_generic_error(self, error: Exception) -> Dict:
        """Handle all other exceptions"""
        return {
            'error': 'An unexpected error occurred',
            'code': 500,
            'details': str(error)
        }

def error_handler(log_file: Optional[str] = None):
    """Decorator to handle exceptions in functions"""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            handler = ErrorHandler(log_file)
            try:
                return func(*args, **kwargs)
            except Exception as e:
                return handler.handle_error(e)
        return wrapper
    return decorator

def handle_error(retry_strategy: Optional['RetryStrategy'] = None):
    """Decorator with retry support using RetryStrategy"""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            import time
            import logging
            logger = logging.getLogger(__name__)

            if retry_strategy is None:
                # No retry, just execute
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    logger.exception(f"Error in {func.__name__}: {e}")
                    raise

            # Retry with strategy
            last_exception = None
            for attempt in range(retry_strategy.max_retries):
                try:
                    return func(*args, **kwargs)
                except retry_strategy.exceptions as e:
                    last_exception = e
                    if attempt < retry_strategy.max_retries - 1:
                        delay = retry_strategy.get_delay(attempt)
                        logger.warning(
                            f"Attempt {attempt + 1} failed in {func.__name__}: {e}. "
                            f"Retrying in {delay:.2f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"All {retry_strategy.max_retries} attempts failed in {func.__name__}")
                except Exception as e:
                    # Non-retryable exception
                    logger.exception(f"Non-retryable error in {func.__name__}: {e}")
                    raise

            if last_exception:
                raise last_exception

        return wrapper
    return decorator

def retry_on_error(
    max_retries: int = 3,
    backoff_factor: float = 1.0,
    exceptions: tuple = (Exception,)
):
    """Retry a function on error with exponential backoff"""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries - 1:
                        raise
                    
                    # Calculate backoff time
                    backoff = min(backoff_factor * (2 ** attempt), 60)  # Cap at 60 seconds
                    print(f"Attempt {attempt + 1} failed: {e}. Retrying in {backoff} seconds...")
                    import time
                    time.sleep(backoff)
            
            # This should never be reached due to the raise in the except block
            raise last_exception or Exception("Unknown error in retry decorator")
        return wrapper
    return decorator

# Global error handler instance
_error_handler = ErrorHandler()

def handle_global_error(error: Exception) -> Any:
    """Handle an error using the global error handler.

    NOTE: renamed from `handle_error` to avoid shadowing the `@handle_error`
    decorator factory defined above — the previous duplicate definition replaced
    the decorator with this function, so `@handle_error(RetryStrategy(...))`
    raised `TypeError: 'dict' object is not callable`.
    """
    return _error_handler.handle_error(error)

def set_global_error_handler(handler: ErrorHandler) -> None:
    """Set the global error handler"""
    global _error_handler
    _error_handler = handler
