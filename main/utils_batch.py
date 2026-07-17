import concurrent.futures

try:
    from tqdm import tqdm as _tqdm
except ImportError:
    def _tqdm(it, **kwargs):  # type: ignore[misc]
        return it

def batch_process(func, items, max_workers=4, desc=None):
    """
    指定関数funcをitemsに対して並列バッチ処理する。進捗バー付き。

    タスクが例外を送出した場合はその Future の結果を None にして処理を継続する
    (一件の失敗が残り全件の結果を失わせないようにするため)。
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(func, item) for item in items]
        for f in _tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc=desc):
            exc = f.exception()
            if exc is not None:
                _log.error("batch_process task failed: %s", exc)
                results.append(None)
            else:
                results.append(f.result())
    return results
