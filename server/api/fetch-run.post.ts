/**
 * POST /api/fetch-run
 *
 * 在本机启动一次 scripts/fetch.py（异步，立即返回）。
 * 口令只走请求头 x-fetch-token，不进 URL；未配置 FETCH_TOKEN 时整体禁用。
 * 进度与结果由 GET /api/fetch-status 轮询获取。
 */
export default defineEventHandler((event) => {
  const availability = fetchAvailability()
  if (!availability.enabled) {
    setResponseStatus(event, 503)
    return { error: 'disabled', reason: availability.reason }
  }

  const token = getHeader(event, 'x-fetch-token') ?? ''
  if (!verifyToken(token)) {
    setResponseStatus(event, 401)
    return { error: 'unauthorized' }
  }

  const result = startFetch()
  if (result.conflict) {
    setResponseStatus(event, 409)
    return { error: 'already_running', started_at: getFetchStatus().started_at }
  }

  setHeader(event, 'Cache-Control', 'no-store')
  return { started: true, started_at: result.startedAt ?? null }
})
