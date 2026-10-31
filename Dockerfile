FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/cafmie/cafmie"
LABEL org.opencontainers.image.description="写真をこのPCの中で立体モデルにします"
LABEL org.opencontainers.image.version="0.1.0"

WORKDIR /opt/imageto3d
COPY pyproject.toml README.md MANIFEST.in ./
COPY imageto3d ./imageto3d
RUN pip install --no-cache-dir . \
    && useradd --create-home --shell /usr/sbin/nologin imageto3d
USER imageto3d
EXPOSE 7860
ENTRYPOINT ["imageto3d"]
CMD ["serve", "--host", "0.0.0.0", "--port", "7860"]
