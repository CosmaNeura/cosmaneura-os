FROM python:3.13-slim@sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81
# Apply the verified Debian security fix omitted by this pinned base.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libpcre2-8-0=10.46-1~deb13u3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH=/app/.venv/bin:$PATH \
    COSMAS_ENV=synth_os
COPY pyproject.toml uv.lock README.md ./
RUN printf '%s\n' 'uv==0.12.5 --hash=sha256:3e195ccf1ed60c8bb24a6447ce306441a4181d54b602407e09bc56e963911c15' >/tmp/uv-bootstrap.lock \
    && python -m pip install --no-cache-dir --require-hashes --only-binary=:all: --requirement /tmp/uv-bootstrap.lock \
    && uv export --offline --frozen --extra efax-inbound --no-dev --no-emit-project --format requirements-txt --output-file /tmp/requirements.lock \
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
    && test "$(readlink -f /usr/bin/mount)" = /usr/bin/mount \
    && test "$(readlink -f /usr/bin/umount)" = /usr/bin/umount \
    && chmod a-s /usr/bin/mount /usr/bin/umount \
    && mkdir -p /data/blobs \
    && chown -R cosmas:cosmas /data/blobs
USER 10001:10001
EXPOSE 8000 8001
CMD ["uvicorn", "cosmas_os.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
