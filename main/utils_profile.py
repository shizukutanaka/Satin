import time
import logging
from functools import wraps

logging.basicConfig(filename='satin_profile.log', level=logging.INFO,
                    format='[%(asctime)s] %(levelname)s %(message)s')

def profile_time(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        elapsed = end - start
        logging.info(f"{func.__name__} 実行時間: {elapsed:.4f}秒")
        return result
    return wrapper

def log_info(msg):
    logging.info(msg)

def log_error(msg):
    logging.error(msg)
