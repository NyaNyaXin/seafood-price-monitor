# syntax=docker/dockerfile:1
#
# 采集镜像（Python 3.11）
#   容器内自带「每天 FETCH_AT 跑一次」的调度循环（docker/fetch/entrypoint.sh），
#   不依赖宿主机的 cron / 任务计划程序，也不依赖 systemd timer。
#
# 只需要 scripts/ + shared/：品种清单、冻品判定关键词在 shared/reference.json，
# Python 与 Node 共用同一份，镜像里也必须带上。

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    FETCH_AT=07:00 \
    RUN_ON_START=true

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 app \
 && useradd --uid 10001 --gid app --create-home --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

# 依赖层单独放，改业务代码不重装依赖
COPY scripts/requirements.txt /app/scripts/requirements.txt
RUN pip install --no-cache-dir -r /app/scripts/requirements.txt

COPY scripts /app/scripts
COPY shared /app/shared
COPY docker/fetch/entrypoint.sh /usr/local/bin/entrypoint.sh

# logs/ 与 data/export/ 预建并授权：命名卷挂上来时继承属主，非 root 也能写
RUN chmod +x /usr/local/bin/entrypoint.sh \
 && mkdir -p /app/logs /app/data/export \
 && chown -R app:app /app

USER app

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
