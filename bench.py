import sys,time, urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = sys.argv[1]    # 填一个端点地址
N = int(sys.argv[2])       # 并发数，填 60

def hit(_):
    """单次 HTTP 请求，返回该请求的耗时（秒）。参数 _ 为 ThreadPoolExecutor.map 传入的占位序号，未使用。"""
    t = time.perf_counter()                        # 记录请求开始时间
    urllib.request.urlopen(URL).read()             # 发起阻塞式 HTTP 请求并读取完整响应
    return time.perf_counter() - t                 # 返回请求耗时

t0 = time.perf_counter()                         # 记录整轮并发测试的开始时间
with ThreadPoolExecutor(max_workers=N) as ex:    # 创建线程池，N 个 worker 并发执行
    # ex.map 把 range(N) 产生的 N 个序号依次传给 hit；list() 强制消费迭代器，
    # 阻塞等待所有线程完成并收集每个 hit 的返回值（单次请求耗时列表）。
    list(ex.map(hit, range(N)))
print(f"{N} 并发 总耗时 {time.perf_counter() - t0:.2f} 秒")  # 打印 N 并发下的整体墙钟耗时