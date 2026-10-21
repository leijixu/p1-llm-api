FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple uv \
    && uv sync --frozen --no-dev

COPY src ./src

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]