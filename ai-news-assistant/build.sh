#!/usr/bin/env bash
# 构建镜像并打 tag（默认 latest，可传版本号）
# 用法：./build.sh            # ai-news-assistant:latest
#      ./build.sh v1.0.0     # ai-news-assistant:v1.0.0
set -euo pipefail
cd "$(dirname "$0")"

TAG="${1:-latest}"
docker build -t "ai-news-assistant:${TAG}" .
echo "✅ 镜像构建完成：ai-news-assistant:${TAG}"
echo "启动：docker compose up -d"
