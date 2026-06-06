import time
import logging
from functools import wraps

# Use a dedicated module logger writing to its own file, rather than calling
# logging.basicConfig() at import time. basicConfig() configures the ROOT logger,
# so importing this profiling helper could redirect the entire application's logs
# into satin_profile.log (and drop console output) depending on import order.
logger = logging.getLogger(__name__)
if not logger.handlers:
    _handler = logging.FileHandler('satin_profile.log', encoding='utf-8')
    _handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s %(message)s'))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    # Keep profiling output in its own file without duplicating into root handlers.
    logger.propagate = False


def profile_time(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            # Log elapsed time even if the call raised.
            logger.info(f"{func.__name__} 実行時間: {time.perf_counter() - start:.4f}秒")
    return wrapper


def log_info(msg):
    logger.info(msg)


def log_error(msg):
    logger.error(msg)
