FROM python:3.13-slim@sha256:d0a9e379c0c588befb0e427db17ca9731751d281f32c6cb1a90a1277b680bdad
# Apply verified Debian security fixes when the pinned base omits them.
# CVE-2026-109518 (apt / libapt-pkg7.0) is fixed in 3.0.4; keep the
# libpcre2 pin from the prior base refresh.
# zlib1g 1:1.3.dfsg+really1.3.1-1+deb13u1 closes CVE-2026-76844 and
# CVE-2026-85091 (DSA-6613-1) on Debian trixie.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        apt=3.0.4 \
        libapt-pkg7.0=3.0.4 \
        libpcre2-8-0=10.46-1~deb13u3 \
        zlib1g=1:1.3.dfsg+really1.3.1-1+deb13u1 \
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
    && uv export --offline --locked --extra efax-inbound --no-dev --no-emit-project --format requirements-txt --output-file /tmp/requirements.lock \
    && mkdir -p /wheels \
    && python -m pip download --require-hashes --only-binary=:all: --dest /wheels --requirement /tmp/requirements.lock
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN --network=none python -m pip install --no-index --find-links=/wheels --require-hashes --requirement /tmp/requirements.lock \
    && python -B -c "import cosmas_os.api.app; from cosmas_os.plugins.runtime import PluginRuntime; from jsonschema import Draft202012Validator; Draft202012Validator.check_schema({'type': 'object'})" \
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
COPY scripts/remove_runtime_mount.py /tmp/remove_runtime_mount.py
RUN --network=none python -B /tmp/remove_runtime_mount.py && rm /tmp/remove_runtime_mount.py
# Remove unused executable surfaces after account creation; retain package metadata
# and required libraries. This reduces exposure without claiming vendor CVE fixes.
COPY scripts/harden_runtime_tools.py /tmp/harden_runtime_tools.py
RUN --network=none python -B /tmp/harden_runtime_tools.py && rm /tmp/harden_runtime_tools.py
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
USER 10001:10001
EXPOSE 8000 8001
CMD ["uvicorn", "cosmas_os.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
