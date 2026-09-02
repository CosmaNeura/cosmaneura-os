FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    COSMAS_ENV=synth_os
RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY fixtures ./fixtures
RUN uv pip install --system -e ".[dev]"
EXPOSE 8000
CMD ["uvicorn", "cosmas_os.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
