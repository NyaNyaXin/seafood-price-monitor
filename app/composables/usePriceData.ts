/**
 * 看板数据层：所有页面共享一次请求，字段派生逻辑集中在此。
 * 数据源 /api/price-data —— Nitro 服务端直连 PostgreSQL，无 JSON 中间层。
 * 接口已带 Cache-Control: no-store，采集入库后刷新即见新数据。
 */

export interface Observation {
  obs_date: string
  market_id: number
  market_name: string
  product_id: number
  product_name: string
  spec_id: number | string
  spec_name: string
  price: number
}

export interface SpecRow {
  snap_date: string
  region: 'cn' | 'ln'
  product_id: number
  product_name: string
  category: string
  spec_name: string
  price: number
  fetch_time: string
}

export interface Trend {
  name: string
  x: string[]
  cn: (number | null)[]
  ln: (number | null)[]
}

export interface PriceMeta {
  generated_at: string
  latest_date: string
  total_obs: number
  total_specs: number
  total_trend_products: number
  total_markets: number
  markets: Record<string, string>
  market_tiers: Record<string, MarketTier>
  alert_threshold: number
  stale_days: number
  frozen_only: boolean
  catalog_total: number
  catalog: Record<string, string>
}

export type MarketTier = 'core' | 'province' | 'national'

export interface PriceData {
  meta: PriceMeta
  observations: Observation[]
  spec_snapshot: SpecRow[]
  trends: Record<string, Trend>
}

export interface Series {
  key: string
  market_id: number
  product_id: number
  spec_id: number | string
  market: string
  product: string
  spec: string
  pts: { date: string; price: number }[]
}

export const pct = (cur: number, prev: number): number | null =>
  prev && prev > 0 ? ((cur - prev) / prev) * 100 : null

/** 沈阳两家的固定简称；其余市场按名称清洗后展示（全名放 title） */
const MKT_ALIAS: Record<number, string> = {
  537: '于洪 · 沈阳水产',
  538: '新民 · 前当堡',
}

/** 长市场名做展示清洗：去公司后缀、截断。仅影响显示，不改数据事实。 */
export function tidyMarket(full: string): string {
  const s = full
    .replace(/(股份)?有限公司.*$/, '')
    .replace(/经营管理$/, '')
    .replace(/有限责任公司.*$/, '')
    .trim()
  return s.length > 14 ? s.slice(0, 13) + '…' : s
}

export const shortMkt = (id: number, meta?: PriceMeta): string => {
  const alias = MKT_ALIAS[id]
  if (alias) return alias
  const full = meta?.markets?.[String(id)]
  return full ? tidyMarket(full) : `市场${id}`
}

/** 市场全名（悬停用） */
export const fullMkt = (id: number, meta?: PriceMeta): string =>
  meta?.markets?.[String(id)] || `市场${id}`

export const marketTier = (id: number, meta?: PriceMeta): MarketTier =>
  meta?.market_tiers?.[String(id)] ?? 'national'

export function changeAt(s: Series, idx: number): number | null {
  if (idx <= 0) return null
  // Nuxt 默认开 noUncheckedIndexedAccess，索引取值可能是 undefined，先收窄再说
  const cur = s.pts[idx]
  const prev = s.pts[idx - 1]
  if (!cur || !prev) return null
  return pct(cur.price, prev.price)
}

export function changeDaysAgo(s: Series, idx: number, days: number): number | null {
  const cur = s.pts[idx]
  if (!cur) return null
  const target = new Date(cur.date + 'T00:00:00').getTime() - days * 86400000
  for (let j = idx - 1; j >= 0; j--) {
    const p = s.pts[j]
    if (!p) continue
    if (new Date(p.date + 'T00:00:00').getTime() <= target) {
      return pct(cur.price, p.price)
    }
  }
  return null
}

export function usePriceData() {
  // server:false —— 纯看板，客户端取数即可，避免 SSR 阶段重复请求
  const { data, error, pending, refresh } = useFetch<PriceData>('/api/price-data', {
    server: false,
    cache: 'no-store',
  })

  const meta = computed(() => data.value?.meta || ({} as PriceMeta))
  const obs = computed(() => data.value?.observations || [])
  const specs = computed(() => data.value?.spec_snapshot || [])
  const trends = computed(() => data.value?.trends || {})
  const THR = computed(() => meta.value.alert_threshold || 0.1)

  const seriesMap = computed<Record<string, Series>>(() => {
    const map: Record<string, Series> = {}
    for (const o of obs.value) {
      const k = `${o.market_id}|${o.product_id}|${o.spec_id}`
      if (!map[k]) {
        map[k] = {
          key: k,
          market_id: o.market_id,
          product_id: o.product_id,
          spec_id: o.spec_id,
          market: o.market_name,
          product: o.product_name,
          spec: o.spec_name,
          pts: [],
        }
      }
      map[k].pts.push({ date: o.obs_date, price: o.price })
    }
    for (const s of Object.values(map)) s.pts.sort((a, b) => a.date.localeCompare(b.date))
    return map
  })

  const series = computed(() => Object.values(seriesMap.value))
  const latest = computed(() => obs.value.filter(o => o.obs_date === meta.value.latest_date))

  const freshness = computed(() => {
    const d = meta.value.latest_date
    if (!d) return { text: '—', cls: 'fresh' }
    const days = Math.floor((Date.now() - new Date(d + 'T00:00:00').getTime()) / 86400000) - 1
    if (days > (meta.value.stale_days ?? 3)) return { text: `⚠ 已 ${days} 天未更新`, cls: 'fresh bad' }
    if (days >= 1) return { text: `⏳ 滞后 ${days} 天`, cls: 'fresh warn' }
    return { text: '数据新鲜', cls: 'fresh' }
  })

  /** 带时间戳重载数据（用户手动刷新按钮用） */
  function reload() {
    return refresh()
  }

  return {
    data, error, pending, reload,
    meta, obs, specs, trends, THR,
    seriesMap, series, latest, freshness,
  }
}
