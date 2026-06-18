FROM python:3.11-alpine

WORKDIR /app

RUN apk add --no-cache gcc musl-dev libffi-dev && \
    pip install --no-cache-dir \
    "mcp[cli]>=1.23.0,<2.0" \
    "fastapi>=0.115" \
    "uvicorn[standard]" \
    httpx \
    "cachetools>=5.0" && \
    apk del gcc musl-dev libffi-dev

COPY server.py .

EXPOSE 8626

ENV PORT=8626
# MCP_WEBHOOK_TOKEN must be provided at runtime — no default intentionally.
# Example: docker run -e MCP_WEBHOOK_TOKEN=your_strong_random_secret ...

CMD ["python", "server.py"]
