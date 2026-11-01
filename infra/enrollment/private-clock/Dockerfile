# Exact accepted application image in the owned ACR, including private_clock_lab.
ARG APP_IMAGE
FROM ${APP_IMAGE}
COPY --chown=10001:10001 infra/enrollment/private-clock/database.py /app/private_clock_database.py
ENTRYPOINT ["python", "/app/private_clock_database.py"]
