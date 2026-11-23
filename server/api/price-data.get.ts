/**
 * GET /api/price-data
 *
 * 看板全量数据：服务端直接查 PostgreSQL，不再经过 public/data.json 中间层。
 * 前端四个页面共用这一个接口（数据量小：观测 ~15 行 / 规格 ~42 行 / 趋势 ~1100 行）。
 *
 * 冻品过滤下推到 SQL，关键词来自 shared/reference.json → frozen_rules，
 * 与采集端 scripts/config.py::is_frozen 共用同一份定义。
 */
import reference from '../../shared/reference.json'

interface Observation {
  obs_date: string
  market_id: number
  market_name: string
  product_id: number
  product_name: string
  spec_id: number
  spec_name: string | null
  price: number
}

interface SpecRow {
  snap_date: string
  region: 'cn' | 'ln'
  product_id: number
  product_name: string
  category: string | null
  spec_name: string
  price: number
  fetch_time: string
}

interface Trend {
  name: string
  x: string[]
  cn: (number | null)[]
  ln: (number | null)[]
}

const rules = reference.frozen_rules
const toLike = (keywords: string[]) => keywords.map((k) => `%${k}%`)

const EXCLUDE_SPEC = toLike(rules.exclude_spec_keywords)
const FROZEN_PRODUCT = toLike(rules.frozen_product_keywords)
const FROZEN_SPEC = toLike([
  ...rules.frozen_spec_keywords,
  ...rules.extra_frozen_spec_keywords,
])

// 判定顺序与 is_frozen 一致：
//   规格名含 鲜/活 → 排除；品名含 进口/冰/冻 → 保留；规格名含 冻/冰/统货 → 保留。
const OBS_SQL = `
  SELECT obs_date, market_id, market_name, product_id, product_name,
         spec_id, spec_name, price
  FROM price_obs
  WHERE NOT (COALESCE(spec_name, '') LIKE ANY($1::text[]))
    AND (
      product_name LIKE ANY($2::text[])
      OR COALESCE(spec_name, '') LIKE ANY($3::text[])
    )
  ORDER BY obs_date, market_id, product_id, spec_id
`

const SPEC_SQL = `
  SELECT snap_date, region, product_id, product_name, category,
         spec_name, price, fetch_time
  FROM spec_snapshot
  ORDER BY region, product_id, spec_name
`

const TREND_SQL = `
  SELECT trend_date, region, product_id, product_name, price
  FROM product_trend
  ORDER BY product_id, region, trend_date
`

export default defineEventHandler(async (event) => {
  setHeader(event, 'Cache-Control', 'no-store')

  const pool = getPool()

  const [obsRes, specRes, trendRes, latestRes, genRes] = await Promise.all([
    pool.query<Observation>(OBS_SQL, [EXCLUDE_SPEC, FROZEN_PRODUCT, FROZEN_SPEC]),
    pool.query<SpecRow>(SPEC_SQL),
    pool.query<{ trend_date: string; region: string; product_id: number; product_name: string; price: number }>(TREND_SQL),
    pool.query<{ d: string | null }>('SELECT MAX(obs_date) AS d FROM price_obs'),
    pool.query<{ t: string | null }>(
      "SELECT MAX(fetch_time) AS t FROM fetch_log WHERE status = 'OK'",
    ),
  ])

  const observations = obsRes.rows
  const specSnapshot = specRes.rows

  // 30 天趋势：按品种把 (日期, 地区) 的行主转成双线序列（与 db.all_trends 口径一致）
  const trends: Record<string, Trend> = {}
  const lnPts: Record<string, Array<[string, number]>> = {}
  const cnPts: Record<string, Record<string, number>> = {}

  for (const r of trendRes.rows) {
    const pid = String(r.product_id)
    // 用局部引用，避免在 noUncheckedIndexedAccess 下反复对 Record 索引做非空断言
    let t = trends[pid]
    let ln = lnPts[pid]
    let cn = cnPts[pid]
    if (!t || !ln || !cn) {
      t = { name: r.product_name, x: [], cn: [], ln: [] }
      ln = []
      cn = {}
      trends[pid] = t
      lnPts[pid] = ln
      cnPts[pid] = cn
    }
    if (r.region === 'ln') ln.push([r.trend_date, r.price])
    else cn[r.trend_date] = r.price
  }

  for (const pid of Object.keys(trends)) {
    const t = trends[pid]
    if (!t) continue
    const ln = lnPts[pid] ?? []
    const cn = cnPts[pid] ?? {}
    // 以辽宁日期为基准对齐；辽宁无价时用全国日期兜底（两者日期序列同源）
    const dates = ln.length ? ln.map(([d]) => d) : Object.keys(cn).sort()
    t.x = dates
    t.ln = ln.length ? ln.map(([, v]) => v) : dates.map(() => null)
    t.cn = dates.map((d) => cn[d] ?? null)
  }

  const catalog: Record<string, string> = {}
  for (const p of reference.frozen_products) catalog[String(p.id)] = p.name

  // markets 在 reference.json 里是 { id: {name, tier} } 结构：
  // 前端只要 id→名称（下拉/简称），tier 单独给，用于「沈阳 / 辽宁 / 全国」范围筛选。
  const marketNames: Record<string, string> = {}
  const marketTiers: Record<string, 'core' | 'province' | 'national'> = {}
  for (const [id, m] of Object.entries(reference.markets)) {
    marketNames[id] = m.name
    marketTiers[id] = m.tier as 'core' | 'province' | 'national'
  }

  return {
    meta: {
      generated_at: genRes.rows[0]?.t ?? new Date().toISOString(),
      latest_date: latestRes.rows[0]?.d ?? null,
      total_obs: observations.length,
      total_specs: specSnapshot.length,
      total_trend_products: Object.keys(trends).length,
      total_markets: new Set(observations.map((o) => o.market_id)).size,
      markets: marketNames,
      market_tiers: marketTiers,
      alert_threshold: reference.alert_threshold,
      stale_days: reference.stale_days,
      frozen_only: true,
      catalog_total: reference.frozen_products.length,
      catalog,
    },
    observations,
    spec_snapshot: specSnapshot,
    trends,
  }
})
