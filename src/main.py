import os
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()
app = FastAPI(docs_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                base_url="https://api.deepseek.com",
                )

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
    reqs = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role":"user","content":user_input}],
        stream=False,
    )
    return {"reply":reqs.choices[0].message.content}