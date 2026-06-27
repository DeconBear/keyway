FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
COPY web/ web/

RUN pip install --no-cache-dir .

ENV KEYWAY_HOST=0.0.0.0
ENV KEYWAY_PORT=9233
ENV KEYWAY_DATA_DIR=/data

VOLUME /data
EXPOSE 9233

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9233/health')" || exit 1

CMD ["python", "-m", "keyway"]
