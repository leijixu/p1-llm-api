import time, urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = "http://127.0.0.1:8000/slow"    # 填一个端点地址
N = 60       # 并发数，填 60

def hit(_):
    t = time.perf_counter()
    urllib.request.urlopen(URL).read()
    return time.perf_counter() - t

t0 = time.perf_counter()
with ThreadPoolExecutor(max_workers=N) as ex:
    list(ex.map(hit, range(N)))
print(f"{N} 并发 总耗时 {time.perf_counter() - t0:.2f} 秒")