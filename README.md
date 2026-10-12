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

同一台机器、同一个 uvicorn 进程、同样的 1.5 秒等待，各发 60 个并发请求：

| 端点 | 实现 | 60 并发总耗时 |
| --- | --- | --- |
| `/slow-sync` | `def` + `time.sleep(1.5)` | **3.19 s** |
| `/slow` | `async def` + `await asyncio.sleep(1.5)` | **1.78 s** |

同步版为什么是 3.19 秒而不是 1.5 秒？因为 FastAPI 把同步端点丢进 anyio 的线程池执行，而线程池的默认容量是 **40**（`anyio/_backends/_asyncio.py` 里的 `CapacityLimiter(40)`）。60 个请求要跑两批：40 + 20，所以约等于 1.5 × 2。

异步版 1.78 秒 ≈ 1.5 秒的等待 + 约 0.28 秒的客户端开销（`urllib` 每个请求新建一条 TCP 连接）。60 个请求全部挂在同一个事件循环上，一起等、一起回。

得出的结论：

- **同步端点的并发上限 = 线程池容量（默认 40）**，超出的请求排队
- **异步端点没有这个上限**，理论上限接近操作系统的文件描述符数量
- 但异步有个前提：端点内部不能出现同步阻塞调用。一旦出现（比如在 `async def` 里调用同步的 SDK），整个事件循环会被卡住，并发度掉到 1，比同步版还差

复现方式：把 `bench.py` 顶部的 `URL` 改成对应端点，然后 `uv run python bench.py`。

## 已知局限与下一步

- `/slow` 与 `/slow-sync` 是压测对照端点，不属于业务接口，上生产前应删除或独立成文件
- 压测脚本用 `urllib`，每个请求新建 TCP 连接，客户端开销没有和端点开销分离；换成 `httpx.AsyncClient` 复用连接后能测得更准
- 两个流式端点都没有发送 SSE 的结束事件（`data: [DONE]`）与异常事件，客户端无法区分「正常结束」和「中途断了」
- 对话端点每次请求都独立，没有多轮上下文（对比：P0 的命令行版本已实现多轮记忆）
- 尚无鉴权、限流与超时重试
- 尚未 Docker 化，也未部署到云服务器