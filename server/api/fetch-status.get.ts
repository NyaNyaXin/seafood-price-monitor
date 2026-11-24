/**
 * GET /api/fetch-status
 *
 * 「立即采集」按钮的状态探针：是否可启用（脚本 + 口令）、当前是否在跑、上次结果。
 * enabled=false 时前端禁用按钮并显示 reason 对应文案。
 */
export default defineEventHandler((event) => {
  setHeader(event, 'Cache-Control', 'no-store')
  return getFetchStatus()
})
