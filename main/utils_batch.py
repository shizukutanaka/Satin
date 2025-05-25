import concurrent.futures
from tqdm import tqdm

def batch_process(func, items, max_workers=4, desc=None):
    """
    指定関数funcをitemsに対して並列バッチ処理する。進捗バー付き。
    """
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(func, item) for item in items]
        for f in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc=desc):
            results.append(f.result())
    return results
