FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Asia/Shanghai \
    HOST=0.0.0.0 \
    PORT=8080

# 时区数据（固定北京时间）
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用构建缓存）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 源码与 Web 模板
COPY ai_news ./ai_news
COPY web ./web

# 数据目录骨架（挂载卷时由卷接管）
RUN mkdir -p /app/data/reports /app/data/memory /app/data/cache /app/data/logs

# 非 root 运行
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"

CMD ["python", "-m", "web.app"]
