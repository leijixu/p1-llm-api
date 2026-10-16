# LLM 对话 API 服务

基于 FastAPI 的大模型对话接口服务。通过 OpenAI 兼容 SDK 接入 DeepSeek，提供健康检查与三种对话接口（一次性返回 / 同步流式 / 异步流式），自带可直接调试的 Swagger 文档，并附带一份并发压测脚本，用实测数据对比同步与异步端点的行为差异。

## 接口

| 方法 | 路径 | 说明 | 请求体 | 响应 |
| --- | --- | --- | --- | --- |
| GET | `/health` | 健康检查 | 无 | `{"status": "ok"}` |
| POST | `/chat` | 单轮对话（一次性返回） | `{"message": "你好"}` | `{"reply": "你好！..."}` |
| POST | `/chat/stream` | 流式对话（同步实现） | `{"message": "你好"}` | `text/event-stream`，逐块推送 `data: ...` |
| POST | `/chat/stream/async` | 流式对话（异步实现） | `{"message": "你好"}` | 同上 |

另外有两个**只用于压测对照**的端点：`/slow`（`async def` + `await asyncio.sleep(1.5)`）与 `/slow-sync`（`def` + `time.sleep(1.5)`），见「同步 vs 异步」一节。

启动后打开 http://127.0.0.1:8000/docs 可直接在页面上调用这些接口。

## 快速开始

1. 安装依赖（需要 Python 3.14+）

   ```powershell
   uv sync
   ```

2. 在项目根目录新建 `.env`，写入你的密钥

   ```
   DEEPSEEK_API_KEY=sk-你的key
   ```

3. 启动服务

   ```powershell
   uv run uvicorn main:app --app-dir src --port 8000 --reload
   ```

   `--app-dir src` 不能省：入口文件在 `src/` 下，而 uvicorn 默认只在当前目录里找模块。

4. 验证流式接口（`-N` 关闭 curl 自身的缓冲，否则文字会攒到最后一次性冒出来）

   ```powershell
   curl.exe -N -X POST http://127.0.0.1:8000/chat/stream -H "Content-Type: application/json" -d '{"message": "用三句话介绍杭州"}'
   ```

## 项目结构

```
src/
  main.py        接口定义（FastAPI 应用）
  static/        Swagger UI 静态资源（本地化，见下文）
bench.py         并发压测脚本（对比同步 / 异步端点）
.env             密钥，已被 .gitignore 忽略
pyproject.toml   依赖声明
```

## 技术栈

FastAPI · uvicorn · openai SDK（OpenAI 兼容协议）· python-dotenv · uv · DeepSeek API

## 实现要点

### 1. `/health` 不只是个 Hello World

它的用途是给负载均衡、监控系统和容器编排（如 K8s 的 liveness/readiness 探针）做探活。语义是「这个实例能不能正常服务请求」，所以要设计成：进程活着但关键依赖（这里是模型 API）不可用时，它应该返回非 200，让调度器把流量切走。生产环境里少了它，服务出问题只能等用户报障。

### 2. Swagger UI 静态资源本地化

FastAPI 默认的 `/docs` 返回的只是一张**空壳 HTML**，真正的界面由浏览器去 `cdn.jsdelivr.net` 下载 Swagger UI 的 JS/CSS。国内访问该 CDN 时经常出现 **TCP 能连接、TLS 握手被重置**的情况，结果是接口本身完全正常（`/health` 返回 200），但 `/docs` 页面一片空白。

解决办法是把静态资源收到自己手里：

- 下载 `swagger-ui-bundle.js`、`swagger-ui.css` 到 `src/static/`
- `app = FastAPI(docs_url=None)` 关掉默认文档路由
- `app.mount("/static", StaticFiles(...))` 挂载静态目录
- 用 `get_swagger_ui_html(swagger_js_url=..., swagger_css_url=...)` 重新实现 `/docs`，指向本地文件

收益是 `/docs` 不再依赖任何第三方 CDN，断网、换机器、CDN 被墙都不受影响。

### 3. 密钥不进版本库

API Key 通过 `.env` 管理，`.env` 已写入 `.gitignore`；`main.py` 只从环境变量读取（`os.environ["DEEPSEEK_API_KEY"]`），仓库中不存在任何明文密钥。

### 4. `/chat/stream`：用 SSE 做流式输出

`/chat` 要等模型把整段话生成完才一次性返回，长回复时用户盯着白屏等好几秒。流式输出让 token 一生成就往外推，首字节延迟从「秒级」降到「毫秒级」——这是所有对话类产品的标配体验。

实现方式是 **SSE（Server-Sent Events）**：一种跑在普通 HTTP 上的文本推送协议，服务端按下面这个格式一段段写：

```
data: 杭州

data: 是浙江省的省会
```

规则是 `data:` + **一个空格** + 内容，然后空行表示这一条消息结束。浏览器端用 `EventSource` 解析。注意冒号后面的空格是协议规定的分隔符，漏掉会导致内容解析错乱；而 Content-Type 必须是严格的 `text/event-stream`，少了 `text/` 前缀时 Swagger 依然能正常显示响应体（它只是把字符串原样打出来，不解析 SSE），但真实前端会直接连接失败。

FastAPI 侧用 `StreamingResponse` 包一个**生成器**：生成器 `yield` 一次，客户端就收到一个 chunk，响应头里是 `transfer-encoding: chunked`（长度未知，边算边发）。

过程中踩到的坑：

- **生成器里的代码是「请求来了才执行」**。函数体里的拼写错误（`comletions`）在启动时完全没有症状，只有真正调用接口才抛 `AttributeError`，表现为「启动正常、一调就断」，浏览器只能显示 `Failed to fetch`。排查方法是去看 uvicorn 终端里的 traceback，而不是在浏览器里找原因。
- **`StreamingResponse(content, status_code, headers, media_type, ...)`**：第二个位置参数是 `status_code`，不是 `media_type`。把 MIME 类型当第二个位置参数传进去，得到的是错误的状态码和默认的 `Content-Type`，必须写成关键字参数 `media_type="text/event-stream"`。

### 5. 同步 vs 异步：实测数据

同一台机器、同一个 uvicorn 进程、同样的 1.5 秒等待，分别发 60 与 120 个并发请求：

| 端点 | 实现 | 60 并发 | 120 并发 |
| --- | --- | --- | --- |
| `/slow-sync` | `def` + `time.sleep(1.5)` | **3.25 s** | **4.70 s** |
| `/slow` | `async def` + `await asyncio.sleep(1.5)` | **1.77 s** | **1.73 / 1.81 s** |

（异步 120 并发跑了两次，1.73 与 1.81 的差值属于测量噪声，说明它并没有随并发数变慢。）

同步版为什么不是 1.5 秒？因为 FastAPI 把同步端点丢进 anyio 的线程池执行，而线程池的默认容量是 **40**（`anyio/_backends/_asyncio.py` 里的 `CapacityLimiter(40)`）。多出来的请求只能排队分批：

| 并发数 | 批数 | 理论耗时 | 实测 |
| --- | --- | --- | --- |
| 60 | 2 | 3.0 s | 3.25 s |
| 120 | 3 | 4.5 s | 4.70 s |

异步版稳定在 1.7~1.8 秒（1.5 秒等待 + 约 0.2 秒客户端开销，`urllib` 每个请求新建一条 TCP 连接），120 并发与 60 并发几乎没有差别。

得出的结论：

- **同步端点的耗时随并发数线性增长**：并发每涨 40 就多一批，耗时多约 1.5 秒
- **异步端点没有这个上限**，耗时与并发数基本无关，理论上限接近操作系统的文件描述符数量
- 换成真实模型调用（每次 3~10 秒）差距会进一步放大：400 并发时同步要跑 10 批，异步仍是 1 批
- 但异步有个前提：端点内部不能出现同步阻塞调用。一旦出现（比如在 `async def` 里调用同步的 SDK），整个事件循环会被卡住，并发度掉到 1，比同步版还差

复现方式：

```powershell
uv run python bench.py http://127.0.0.1:8000/slow-sync 60
uv run python bench.py http://127.0.0.1:8000/slow 60
uv run python bench.py http://127.0.0.1:8000/slow-sync 120
uv run python bench.py http://127.0.0.1:8000/slow 120
```
### 6. 超时与错误处理

上游（模型服务）不是永远可用的。openai SDK 的默认超时是 **600 秒**（`openai/_constants.py` 里的 `DEFAULT_TIMEOUT`），意思是上游卡住时，一个请求会占着资源等满 10 分钟；并发一上来，服务自己先被拖死。所以三个对话端点都显式设了 `timeout=30.0`。

> 流式接口里的 `timeout` 语义不一样：它不是「整个回答最多 30 秒」，而是「**两个 chunk 之间**最多等 30 秒」，长回答不会被掐断。

出错时要翻译成正确的状态码，而不是笼统的 500：

| 上游情况 | 异常类型 | 返回 | 含义 |
| --- | --- | --- | --- |
| 请求超时 | `APITimeoutError` | **504** | 网关等上游超时 |
| 连不上 / 网络中断 | `APIConnectionError` | **502** | 网关连不上上游 |
| 上游返回错误状态码 | `APIStatusError` | 待补 | 按具体状态细分 |
| 触发限流 | `RateLimitError` | 待补 | 是 `APIStatusError` 的子类 |

两个容易踩的点：

- **`except` 的顺序必须子类在前**。`APITimeoutError` 继承自 `APIConnectionError`（见 `openai/_exceptions.py`），父类写前面会把超时也接走，永远返回不到 504
- **流式端点不能靠状态码上报错误**。`StreamingResponse` 会先发 `200 OK` 响应头，然后才开始跑生成器；生成器抛错时状态码已经发出去了。唯一的上报通道是往流里再写一条消息：

```
event: upstream_error
data: 模型服务超时，回答已中断
```

事件名用 `upstream_error` 而不是 `error`，是为了避开 `EventSource` 内置的 `error` 事件（连接断开时触发），否则前端分不清是上游挂了还是自己网断了。

正常结束时则发送 data: [DONE]——这是 OpenAI 生态约定的哨兵值（不是 SSE 协议自带的）。两个信号互斥：**出错时不会发 [DONE]**，客户端据此区分「答完了」和「中途断了」。

验证方式（不用等上游真的挂）：

- 超时：把 `timeout` 临时改成 `0.001` → `/chat` 返回 504，流式端点在流里返回 `upstream_error` 事件
- 连不上：把 `base_url` 临时改成 `http://127.0.0.1:9/v1` → `/chat` 返回 502
### 7. 按 IP 限流

地址一旦公开，任何人（包括爬虫）都能调用并消耗 API 额度。所以在中间件层加了限流：按客户端 IP 做 60 秒的滑动窗口，窗口内超过 20 次就返回 `429`，并带上 `Retry-After` 头告诉对方等多久再来。

只拦 `/chat` 开头的业务接口，`/health`、`/docs`、`/static` 不拦——探活接口要被监控高频调用，而 `/docs` 加载一次要请求四个资源（页面 + CSS + JS + openapi.json），拦它会让人直接打不开文档页。

用滑动窗口而不是「每分钟清零」的固定窗口，是因为固定窗口在两个窗口的交界处会放行接近两倍的流量。

三个实现细节：

- **中间件里不能 `raise HTTPException`**。异常处理器挂在路由那一层，在中间件里抛出去没人接，会变成一个 500。要自己造响应：`return JSONResponse(status_code=429, ...)`
- 每个 IP 用一个 `deque` 存最近几次请求的时间戳，`while` 循环把超出窗口的从左侧弹出（用 `while` 不是 `if`，因为可能积压了好几个过期的）
- 时间用 `time.monotonic()` 而不是 `time.time()`，避免系统时间被调整时窗口错乱

验证方式是先用固定延迟的对照端点 `/slow`（不消耗模型调用）在本地把 `LIMIT` 临时设成 3 跑通，再改回 20 部署上线。
## 在线演示

http://43.142.41.234:8000/docs

部署在腾讯云轻量应用服务器（上海二区，Ubuntu 24.04 LTS，x86_64）。

## 部署记录

```bash
# 1. 基础工具
sudo apt update && sudo apt install -y git curl

# 2. 装 uv（官方脚本从 GitHub 下载，国内可能长时间卡住；改用清华源）
sudo pip3 install --break-system-packages -i https://pypi.tuna.tsinghua.edu.cn/simple uv

# 3. 拉代码（仓库是 public，无需配置 SSH 密钥）
git clone https://github.com/leijixu/p1-llm-api.git && cd p1-llm-api

# 4. 装依赖（uv 自动挑选并下载 CPython，依赖走 lock 文件中记录的清华源）
uv sync

# 5. 写入密钥（不要在命令行里 echo，会把 key 留在 shell 历史中）
nano .env

# 6. 交给 systemd 托管
#    前台启动的进程是 SSH 会话的子进程，会话一断服务就死
sudo nano /etc/systemd/system/p1-llm-api.service
```

unit 文件内容：

```ini
[Unit]
Description=LLM Chat API
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/p1-llm-api
ExecStart=/home/ubuntu/p1-llm-api/.venv/bin/uvicorn main:app --app-dir src --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now p1-llm-api
sudo systemctl status p1-llm-api --no-pager
journalctl -u p1-llm-api -f        # 持续查看日志
```

用 systemd 而不是 `nohup` / `screen`，因为它一次解决三件事：常驻、开机自启、崩溃后自动重启，而且日志统一进 `journalctl`。

其中 `WorkingDirectory` 必须写对——代码里 `load_dotenv()` 是在**当前工作目录**找 `.env` 的，路径错了服务起不来，报错信息还会含糊地说是密钥缺失。
部署时踩到的坑：

- **uvicorn 默认只监听 `127.0.0.1`**，外部访问不到，必须显式加 `--host 0.0.0.0`
- **云厂商的防火墙（安全组）默认只放行 22 端口**，需要在控制台手动放行 8000。两个坑的现象完全一样：服务在本机 curl 正常，外部全部超时
- 国内服务器用 80 端口对公网提供 HTTP 服务需要 ICP 备案，所以演示走 8000 这类非标准端口
- `uv sync` 的耗时主要在下载 CPython 解释器（来源是 GitHub，与依赖源无关）
## 已知局限与下一步

- 只有超时与连接错误做了状态码映射，`APIStatusError`（上游返回错误状态码）与 `RateLimitError`（限流）还没有细分
- 重试完全依赖 SDK 默认配置（`max_retries=2`，指数退避 + 抖动），没有按接口场景调整
- `/slow` 与 `/slow-sync` 是压测对照端点，不属于业务接口，上生产前应删除或独立成文件
- 压测脚本用 `urllib`，每个请求新建 TCP 连接，客户端开销没有和端点开销分离；换成 `httpx.AsyncClient` 复用连接后能测得更准
- 对话端点每次请求都独立，没有多轮上下文（对比：P0 的命令行版本已实现多轮记忆）
- 尚无鉴权与限流，不适合直接暴露到公网
- 公网地址没有任何鉴权与限流，任何人都可以调用并消耗 API 额度
- 尚未 Docker 化