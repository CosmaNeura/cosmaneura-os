FROM python:3.13-slim@sha256:cc9dffa47c8294ba9bb795a8dfaeb7b76f2b30acade2c52a461a2999d127eb00
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH=/app/.venv/bin:$PATH \
    COSMAS_ENV=synth_os
COPY pyproject.toml uv.lock README.md ./
RUN printf '%s\n' 'uv==0.12.5 --hash=sha256:3e195ccf1ed60c8bb24a6447ce306441a4181d54b602407e09bc56e963911c15' >/tmp/uv-bootstrap.lock \
    && python -m pip install --no-cache-dir --require-hashes --only-binary=:all: --requirement /tmp/uv-bootstrap.lock \
    && uv export --offline --frozen --no-dev --no-emit-project --format requirements-txt --output-file /tmp/requirements.lock \
    && mkdir -p /wheels \
    && python -m pip download --require-hashes --only-binary=:all: --dest /wheels --requirement /tmp/requirements.lock
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN --network=none python -m pip install --no-index --find-links=/wheels --require-hashes --requirement /tmp/requirements.lock \
    && rm -rf /wheels /tmp/requirements.lock /tmp/uv-bootstrap.lock /root/.cache/uv \
    && /usr/local/bin/python -m pip uninstall --yes uv setuptools pip
COPY fixtures ./fixtures
COPY docs/third-party ./docs/third-party
RUN groupadd --gid 10001 cosmas \
    && useradd --uid 10001 --gid cosmas --no-create-home --shell /usr/sbin/nologin cosmas \
    && mkdir -p /data/blobs \
    && chown -R cosmas:cosmas /data/blobs
USER 10001:10001
EXPOSE 8000 8001
CMD ["uvicorn", "cosmas_os.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
