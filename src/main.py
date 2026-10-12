import os
import time
import asyncio
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Iterable, AsyncIterable
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI

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
    user_input = req.message.strip()
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role":"user","content":user_input}],
        stream=False,
    )
    return {"reply":resp.choices[0].message.content}

@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    def event_stream() -> Iterable[str]:
        stream = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": req.message.strip()}],
            stream=True,
        )
        for chunk in stream:
            piece = chunk.choices[0].delta.content
            if piece:
                yield f"data: {piece}\n\n"
    return StreamingResponse(event_stream(),media_type="text/event-stream")

@app.post("/chat/stream/async")
async def chat_stream_async(req: ChatRequest):
    async def event_stream() -> AsyncIterable[str]:
        stream = await aclient.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": req.message.strip()}],
            stream=True,
        )
        async for chunk in stream:
            piece = chunk.choices[0].delta.content
            if piece:
                yield f"data: {piece}\n\n"
    return StreamingResponse(event_stream(),media_type="text/event-stream")

@app.get("/slow")                      # 异步版
async def slow():
    await asyncio.sleep(1.5)
    return {"ok": 1}

@app.get("/slow-sync")                 # 同步版
def slow_sync():
    time.sleep(1.5)
    return {"ok": 1}