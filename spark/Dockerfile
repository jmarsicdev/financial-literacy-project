
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PYSPARK_PYTHON=python3
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jre-headless \
    procps \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    pyspark==3.5.7 \
    numpy==1.26.4 \
    psycopg2-binary==2.9.10 \
    pytest==9.1.1

WORKDIR /opt/spark-app

CMD ["bash", "-lc", "sleep infinity"]
