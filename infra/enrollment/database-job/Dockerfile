# APP_IMAGE must be the reviewed application ACR image@sha256:digest.
# This one-purpose image adds only the database administrative entrypoint.
ARG APP_IMAGE
FROM ${APP_IMAGE}
COPY --chown=10001:10001 infra/enrollment/database-job/database.py /app/enrollment_database_admin.py
ENTRYPOINT ["python", "/app/enrollment_database_admin.py"]
