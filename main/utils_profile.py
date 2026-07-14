import os
import time
import logging
import logging.handlers
from functools import wraps

# Use a dedicated module logger writing to its own file, rather than calling
# logging.basicConfig() at import time. basicConfig() configures the ROOT logger,
# so importing this profiling helper could redirect the entire application's logs
# into satin_profile.log (and drop console output) depending on import order.
#
# The file lives under config/logs/ (same directory LoggingManager uses),
# not a bare relative path — a relative FileHandler path resolves against
# whatever the process's cwd happens to be, so it used to litter the repo
# root with an ever-growing, never-rotated satin_profile.log (this module
# is imported by several *_batch utilities, so any --manage invocation
# from the repo root kept appending to it). RotatingFileHandler caps it.
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "logs")

logger = logging.getLogger(__name__)
if not logger.handlers:
    os.makedirs(_LOG_DIR, exist_ok=True)
    _handler = logging.handlers.RotatingFileHandler(
        os.path.join(_LOG_DIR, "satin_profile.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8',
    )
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
