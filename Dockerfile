FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH=/app/.venv/bin:$PATH \
    COSMAS_ENV=synth_os
RUN pip install --no-cache-dir uv==0.12.5
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY fixtures ./fixtures
RUN uv sync --frozen --no-dev
EXPOSE 8000
CMD ["uvicorn", "cosmas_os.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
