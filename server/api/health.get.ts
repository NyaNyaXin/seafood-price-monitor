/**
 * GET /api/health
 *
 * 容器健康探针。
 *   默认            → 只回进程状态，不碰数据库（存活探针用，库挂不该触发容器重启）
 *   ?db=1 或 ?db=true → 额外跑一次 SELECT 1，用于部署后确认库连通（就绪探针）
 *
 * 例：
 *   curl -s localhost:3000/api/health
 *   curl -s "localhost:3000/api/health?db=1"
 */
export default defineEventHandler(async (event) => {
  const q = getQuery(event)
  const probeDb = q.db === '1' || q.db === 'true'

  const body: Record<string, unknown> = {
    status: 'ok',
    uptime_s: Math.round(process.uptime()),
    time: new Date().toISOString(),
  }

  if (probeDb) {
    const started = Date.now()
    try {
      await getPool().query('SELECT 1')
      body.db = { ok: true, latency_ms: Date.now() - started }
    } catch (err) {
      // 探针本身不抛 500：HTTP 200 + degraded，方便 curl / 脚本判断细节
      body.status = 'degraded'
      body.db = {
        ok: false,
        latency_ms: Date.now() - started,
        error: (err as Error).message,
      }
    }
  }

  return body
})
