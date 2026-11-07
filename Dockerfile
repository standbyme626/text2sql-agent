FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/

COPY backend /app/backend
COPY deploy/docker-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# 前端静态产物通过 volume 挂载（backend/static），不打进镜像
EXPOSE 3388
CMD ["/usr/local/bin/entrypoint.sh"]
