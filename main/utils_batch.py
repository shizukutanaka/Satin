import concurrent.futures

try:
    from tqdm import tqdm as _tqdm
except ImportError:
    def _tqdm(it, **kwargs):  # type: ignore[misc]
        return it

def batch_process(func, items, max_workers=4, desc=None):
    """
    指定関数funcをitemsに対して並列バッチ処理する。進捗バー付き。
    """
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(func, item) for item in items]
        for f in _tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc=desc):
            results.append(f.result())
    return results
