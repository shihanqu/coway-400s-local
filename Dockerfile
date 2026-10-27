FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && useradd --uid 10001 --create-home coway \
    && mkdir /data && chown coway:coway /data
USER coway
ENV COWAY_DATA_DIR=/data
EXPOSE 1053/udp 9090/tcp 8080/tcp
CMD ["coway400s", "serve"]
