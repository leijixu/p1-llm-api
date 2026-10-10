# LLM 对话 API 服务

基于 FastAPI 的大模型对话接口服务。通过 OpenAI 兼容 SDK 接入 DeepSeek，提供健康检查与对话两个接口，并自带可直接调试的 Swagger 文档。

## 接口

| 方法 | 路径 | 说明 | 请求体 | 响应 |
| --- | --- | --- | --- | --- |
| GET | `/health` | 健康检查 | 无 | `{"status": "ok"}` |
| POST | `/chat` | 单轮对话 | `{"message": "你好"}` | `{"reply": "你好！..."}` |

启动后打开 http://127.0.0.1:8000/docs 可直接在页面上调用这两个接口。

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

## 已知局限与下一步

- `/chat` 目前是同步阻塞的（`stream=False`），需要等模型生成完整回复后一次性返回，长回复时首字节延迟高。**下一步改造为 SSE 流式输出。**
- `/chat` 每次请求独立，没有多轮上下文（对比：P0 的命令行版本已实现多轮记忆）。
- 尚无鉴权、限流与超时重试，不适合直接暴露到公网。