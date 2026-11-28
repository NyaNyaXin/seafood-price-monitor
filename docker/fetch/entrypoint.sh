#!/bin/sh
# 采集容器入口：按需先跑一次，之后每天在 FETCH_AT 列出的时间点各跑一次。
#
# FETCH_AT 支持逗号分隔多个时间点，例如 12:00,17:00（容器本地时区）。
# 为什么不用 cron / systemd timer：
#   - 单进程前台循环，容器停掉就干净退出，日志直接进 docker logs；
#   - 不额外装 cron 守护进程，镜像小、无需额外权限。
#
# 环境变量：
#   FETCH_AT       每天采集时刻，HH:MM，可逗号分隔（默认 12:00,17:00）
#   RUN_ON_START   true=容器启动立刻跑一次（默认），false=等到下一个时间点
set -eu

# 允许覆盖入口直接执行命令，便于手动排障：
#   docker compose run --rm fetch python /app/scripts/fetch.py --verbose
if [ "$#" -gt 0 ]; then
  exec "$@"
fi

FETCH_AT="${FETCH_AT:-12:00,17:00}"
RUN_ON_START="${RUN_ON_START:-true}"

# 逐个校验时间点，过滤掉写错的（如 7:00、17点、24:00），全空则回退默认值
VALID=""
OLD_IFS=$IFS
IFS=','
for slot in $FETCH_AT; do
  slot=$(printf '%s' "$slot" | tr -d ' ')
  if [ -n "$slot" ] && date -d "today $slot" >/dev/null 2>&1; then
    VALID="${VALID:+$VALID,}$slot"
  else
    echo "[scheduler] 忽略无法解析的时间点 '$slot'（格式应为 HH:MM）" >&2
  fi
done
IFS=$OLD_IFS
if [ -z "$VALID" ]; then
  echo "[scheduler] FETCH_AT='$FETCH_AT' 无可解析时间点，回退 12:00,17:00" >&2
  VALID="12:00,17:00"
fi
FETCH_AT="$VALID"

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

# 取 FETCH_AT 里距离当前最近的下一个时间点（今天的点已过则顺延到明天）
next_run_ts() {
  now=$(date +%s)
  best=""
  OLD_IFS=$IFS
  IFS=','
  for slot in $FETCH_AT; do
    ts=$(date -d "today $slot" +%s)
    if [ "$ts" -le "$now" ]; then
      ts=$(date -d "tomorrow $slot" +%s)
    fi
    if [ -z "$best" ] || [ "$ts" -lt "$best" ]; then
      best=$ts
    fi
  done
  IFS=$OLD_IFS
  printf '%s' "$best"
}

if [ "${RUN_ON_START}" = "true" ]; then
  run_once
fi

while :; do
  now=$(date +%s)
  next=$(next_run_ts)
  wait_s=$((next - now))
  if [ "$wait_s" -lt 0 ]; then
    wait_s=0
  fi

  echo "[scheduler] 下一次采集 $(date -d "@${next}" '+%F %T')（${wait_s}s 后）"
  sleep "$wait_s"

  run_once
  # 避免同一秒内重复触发
  sleep 1
done
