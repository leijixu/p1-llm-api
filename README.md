# LLM 对话 API 服务

基于 FastAPI 的大模型对话接口服务。通过 OpenAI 兼容 SDK 接入 DeepSeek，提供健康检查、单轮对话与流式对话三个接口，并自带可直接调试的 Swagger 文档。

## 接口

| 方法 | 路径 | 说明 | 请求体 | 响应 |
| --- | --- | --- | --- | --- |
| GET | `/health` | 健康检查 | 无 | `{"status": "ok"}` |
| POST | `/chat` | 单轮对话（一次性返回） | `{"message": "你好"}` | `{"reply": "你好！..."}` |
| POST | `/chat/stream` | 单轮对话（SSE 流式返回） | `{"message": "你好"}` | `text/event-stream`，逐块推送 `data: ...` |

启动后打开 http://127.0.0.1:8000/docs 可直接在页面上调用这三个接口。

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
   uv run uvicorn main:app --app-dir src --port 8000
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

规则是 `data:` + **一个空格** + 内容，然后空行表示这一条消息结束。浏览器端用 `EventSource` 解析。注意冒号后面的空格是协议规定的分隔符，漏掉会导致内容解析错乱。

FastAPI 侧用 `StreamingResponse` 包一个**生成器**：生成器 `yield` 一次，客户端就收到一个 chunk，响应头里是 `transfer-encoding: chunked`（长度未知，边算边发）。

过程中踩到的三个坑：

- **生成器里的代码是「请求来了才执行」**。函数体第一行的拼写错误（`comletions`）在启动时完全没有症状，只有真正调用接口才抛 `AttributeError`，表现为「启动正常、一调就断」，浏览器只能显示 `Failed to fetch`。排查方法是去看 uvicorn 终端里的 traceback，而不是在浏览器里找原因。
- **`StreamingResponse(content, status_code, headers, media_type, ...)`**：第二个位置参数是 `status_code`，不是 `media_type`。把 MIME 类型当第二个位置参数传进去，得到的是错误的状态码和默认的 `Content-Type`，必须写成关键字参数 `media_type="text/event-stream"`。
- **`data:` 后必须有空格**，见上文协议格式。

## 已知局限与下一步

- `/chat` 与 `/chat/stream` 都是同步实现（`def` + 同步 `OpenAI` 客户端）。FastAPI 会把同步端点丢到线程池执行，不会阻塞事件循环，但每个进行中的请求都占住一个线程，高并发下线程池会成为瓶颈。**下一步：改用 `AsyncOpenAI` + `async def` + `async for`**，并加一个并发压测对比。
- `/chat/stream` 没有发送 SSE 的结束事件（`data: [DONE]`）和异常事件，客户端无法区分「正常结束」和「中途断了」。
- 两个对话接口每次请求都独立，没有多轮上下文（对比：P0 的命令行版本已实现多轮记忆）。
- 尚无鉴权、限流与超时重试，不适合直接暴露到公网。