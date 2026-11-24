FROM python:3.11-alpine

WORKDIR /app

RUN apk add --no-cache gcc musl-dev libffi-dev && \
    pip install --no-cache-dir \
    "mcp[cli]>=1.23.0,<2.0" \
    "fastapi>=0.115" \
    "uvicorn[standard]" \
    httpx \
    "cachetools>=5.0" \
    "python-jejakmasjid>=0.3.5" \
    "python-esolat>=0.1.0" && \
    apk del gcc musl-dev libffi-dev && \
    adduser -D -u 1000 appuser

COPY server.py .

RUN chown appuser:appuser /app/server.py

USER appuser

EXPOSE 8626

ENV PORT=8626
# MCP_WEBHOOK_TOKEN must be provided at runtime -- no default intentionally.
# Example: docker run -e MCP_WEBHOOK_TOKEN=your_strong_random_secret ...

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost:${PORT}/ || exit 1

CMD ["python", "server.py"]
