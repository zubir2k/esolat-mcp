FROM python:3.11-alpine

WORKDIR /app

RUN apk add --no-cache gcc musl-dev libffi-dev

RUN pip install --no-cache-dir \
    "mcp[cli]>=1.23.0,<2.0" \
    "fastapi>=0.115" \
    "uvicorn[standard]" \
    httpx

COPY server.py .

EXPOSE 8626

ENV PORT=8626
ENV MCP_WEBHOOK_TOKEN=esolat_secure_token

CMD ["python", "server.py"]