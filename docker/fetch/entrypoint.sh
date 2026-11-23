#!/bin/sh
# 采集容器入口：按需先跑一次，之后每天 FETCH_AT（容器本地时区，默认 Asia/Shanghai）跑一次。
#
# 为什么不用 cron / systemd timer：
#   - 单进程前台循环，容器停掉就干净退出，日志直接进 docker logs；
#   - 不额外装 cron 守护进程，镜像小、无需额外权限。
#
# 环境变量：
#   FETCH_AT       每天几点跑，格式 HH:MM（默认 07:00）
#   RUN_ON_START   true=容器启动立刻跑一次（默认），false=等到下一个时间点
set -eu

# 允许覆盖入口直接执行命令，便于手动排障：
#   docker compose run --rm fetch python /app/scripts/fetch.py --verbose
if [ "$#" -gt 0 ]; then
  exec "$@"
fi

FETCH_AT="${FETCH_AT:-07:00}"
RUN_ON_START="${RUN_ON_START:-true}"

# FETCH_AT 写错（如 7:00、0700、24:00）会让 date 直接报错退出，这里先兜住
if ! date -d "today ${FETCH_AT}" >/dev/null 2>&1; then
  echo "[scheduler] FETCH_AT=${FETCH_AT} 无法解析，回退 07:00（格式应为 HH:MM）" >&2
  FETCH_AT=07:00
fi

run_once() {
  echo "[scheduler] $(date '+%F %T') 开始采集"
  if python /app/scripts/fetch.py --verbose; then
    echo "[scheduler] $(date '+%F %T') 采集完成"
  else
    # 单次失败不退出：数据源偶发 403 / 平台慢查询，等下一轮即可；
    # 失败原因同时写进 /app/logs/fetch.log 与 Postgres 的 fetch_log 表。
    code=$?
    echo "[scheduler] $(date '+%F %T') 采集失败（退出码 ${code}），等待下一轮" >&2
  fi
}

if [ "${RUN_ON_START}" = "true" ]; then
  run_once
fi

while :; do
  now=$(date +%s)
  next=$(date -d "today ${FETCH_AT}" +%s)
  # 今天的点已过（或正好等于当前秒）→ 排到明天
  if [ "${next}" -le "${now}" ]; then
    next=$(date -d "tomorrow ${FETCH_AT}" +%s)
  fi

  wait_s=$((next - now))
  echo "[scheduler] 下一次采集 $(date -d "@${next}" '+%F %T')（${wait_s}s 后）"
  sleep "${wait_s}"

  run_once
done
