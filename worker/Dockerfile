FROM python:3.11.13-slim-bookworm@sha256:86adf8dbadc3d6e82ee5dd2c74bec2e1c2467cdad47886280501df722372d2e1

WORKDIR /app
COPY local_synthesis /app/local_synthesis
COPY config/model-manifest.json /app/config/model-manifest.json
COPY config/worker.example.json /app/config/worker.json

RUN mkdir -p /state /models /run/secrets \
    && chown -R 65532:65532 /state /run/secrets \
    && chmod -R a-w /app /models \
    && chmod 0555 /models \
    && chmod 0700 /state /run/secrets

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 65532:65532
EXPOSE 8787
ENTRYPOINT ["python", "-m", "local_synthesis"]
CMD ["--config", "/app/config/worker.json"]
