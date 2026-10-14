import os
import time
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Iterable, AsyncIterable
from fastapi.responses import StreamingResponse
from fastapi import FastAPI, HTTPException
from openai import OpenAI, AsyncOpenAI, APITimeoutError, APIConnectionError

load_dotenv()
app = FastAPI(docs_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                base_url="https://api.deepseek.com",
                )
aclient = AsyncOpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                      base_url="https://api.deepseek.com",)

@app.get("/docs", include_in_schema=False)
def custom_docs():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
    )

class ChatRequest(BaseModel):
    message: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/chat")
def chat(req: ChatRequest):
    try:
        user_input = req.message.strip()
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": user_input}],
            stream=False,
            timeout=30.0,
        )
    except APITimeoutError:
        raise HTTPException(status_code=504, detail="模型服务响应超时")
    except APIConnectionError:
        raise HTTPException(status_code=502, detail="无法连接模型服务")
    return {"reply":resp.choices[0].message.content}

@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    def event_stream() -> Iterable[str]:
        try:
            stream = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": req.message.strip()}],
                stream=True,
                timeout=30.0,
            )
            for chunk in stream:
                piece = chunk.choices[0].delta.content
                if piece:
                    yield f"data: {piece}\n\n"
            yield f"data: [DONE]\n\n"
        except APITimeoutError:
            yield "event: upstream_error\ndata: 模型服务超时，回答已中断\n\n"
        except APIConnectionError:
            yield "event: upstream_error\ndata: 无法连接模型服务，回答已中断\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.post("/chat/stream/async")
async def chat_stream_async(req: ChatRequest):
    """异步版 SSE 流式聊天接口。与上方同步版 chat_stream 的区别：
    1. 使用 AsyncOpenAI（aclient）代替同步 OpenAI client，请求不阻塞事件循环；
    2. 内部 event_stream 也是 async def，用 async for 消费 DeepSeek 返回的异步流。"""
    async def event_stream() -> AsyncIterable[str]:
        try:
            # await 发起异步 HTTP 请求，不阻塞 FastAPI 的事件循环，
            # 这样其它请求可以在等待 DeepSeek 响应期间被处理。
            stream = await aclient.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": req.message.strip()}],
                stream=True,  # 让 DeepSeek 以 SSE 逐块返回
                timeout=30.0,
            )
            # async for 逐块读取异步流，每个 chunk 是 DeepSeek 推来的一个 token 增量
            async for chunk in stream:
                piece = chunk.choices[0].delta.content  # 取出本轮 token 文本（可能为 None）
                if piece:  # 跳过空 token（如 role 信息、结束标记等）
                    # SSE 协议要求：每条消息以 "data: " 开头，用两个 \n\n 与下一条分隔
                    yield f"data: {piece}\n\n"
            yield f"data: [DONE]\n\n"
        except APITimeoutError:
            yield "event: upstream_error\ndata: 模型服务超时，回答已中断\n\n"
        except APIConnectionError:
            yield "event: upstream_error\ndata: 无法连接模型服务，回答已中断\n\n"
    # StreamingResponse 接收异步生成器，FastAPI 会自动驱动它并以 chunked 编码推送给客户端，
    # media_type 必须是 text/event-stream，浏览器/客户端才会按 SSE 协议解析。
    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.get("/slow")                      # 异步版
async def slow():
    await asyncio.sleep(1.5)
    return {"ok": 1}

@app.get("/slow-sync")                 # 同步版
def slow_sync():
    time.sleep(1.5)
    return {"ok": 1}