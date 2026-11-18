# Squad Radio - KOOK always-on password bot
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 依赖单独复制，利用构建缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码与入口
COPY main.py ./
COPY squad_radio/ ./squad_radio/

# 以非 root 用户运行
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/data /app/logs \
    && chown -R appuser:appuser /app
USER appuser

# 运行时数据卷（密码缓存、状态、日志）
VOLUME ["/app/data", "/app/logs"]

# 默认健康检查端口；可用 -e SQUAD_RADIO_HEALTH_PORT 覆盖
ENV SQUAD_RADIO_HEALTH_PORT=8080
EXPOSE 8080

# KOOK_TOKEN 通过 -e 或 --env-file 注入，绝不写进镜像
CMD ["python", "main.py"]
