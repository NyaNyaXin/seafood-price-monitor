<script setup lang="ts">
import { usePriceData, shortMkt, fullMkt, marketTier, changeAt, changeDaysAgo } from '~/composables/usePriceData'

useHead({ title: '潮汐 TIDE · 沈阳水产鲜度日报' })

const { meta, latest, seriesMap, THR } = usePriceData()

// 范围分层：core=沈阳两家，ln=辽宁（core+province），national=全国参考市场
const RANGE_ALL = '__all__'
const RANGE_CORE = 'core'
const RANGE_LN = 'ln'
const RANGE_NATL = 'national'
const range = ref<string>(RANGE_ALL)
const marketFilter = ref<string>(RANGE_ALL)
const productFilter = ref<string>(RANGE_ALL)

const rangeLabel: Record<string, string> = {
  [RANGE_ALL]: '全部市场',
  [RANGE_CORE]: '沈阳',
  [RANGE_LN]: '辽宁',
  [RANGE_NATL]: '全国参考',
}

const rangeRows = computed(() => {
  const r = range.value
  return latest.value.filter((o) => {
    const t = marketTier(o.market_id, meta.value)
    if (r === RANGE_CORE) return t === 'core'
    if (r === RANGE_LN) return t === 'core' || t === 'province'
    if (r === RANGE_NATL) return t === 'national'
    return true
  })
})

/** 当前范围下出现过的市场（按名称排序），供下拉筛选 */
const marketOptions = computed(() => {
  const ids = [...new Set(rangeRows.value.map((o) => o.market_id))]
  return ids
    .map((id) => ({ value: String(id), label: shortMkt(id, meta.value), hint: fullMkt(id, meta.value) }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh'))
})

/** 当前范围下出现过的品种（供品种搜索） */
const productOptions = computed(() => {
  const m = new Map<number, string>()
  for (const o of rangeRows.value) m.set(o.product_id, o.product_name)
  return [...m.entries()]
    .map(([id, name]) => ({ value: String(id), label: name }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh'))
})

watch(range, () => { marketFilter.value = RANGE_ALL; productFilter.value = RANGE_ALL })

const upCnt = computed(() => todayRows.value.filter(r => r.d1 != null && r.d1 > 0).length)
const downCnt = computed(() => todayRows.value.filter(r => r.d1 != null && r.d1 < 0).length)

const todayRows = computed(() => {
  const src = rangeRows.value
    .filter((o) => marketFilter.value === RANGE_ALL || String(o.market_id) === marketFilter.value)
    .filter((o) => productFilter.value === RANGE_ALL || String(o.product_id) === productFilter.value)
  return src.map(o => {
    const s = seriesMap.value[o.market_id + '|' + o.product_id + '|' + o.spec_id]
    const idx = s ? s.pts.findIndex(p => p.date === o.obs_date) : -1
    const d1 = s ? changeAt(s, idx) : null
    const d7 = s ? changeDaysAgo(s, idx, 7) : null
    return {
      ...o,
      market: shortMkt(o.market_id, meta.value),
      marketFull: fullMkt(o.market_id, meta.value),
      tier: marketTier(o.market_id, meta.value),
      spec: o.spec_name && o.spec_name !== '/' ? o.spec_name : '—',
      d1, d7,
      alert: d1 != null && Math.abs(d1) / 100 >= THR.value,
    }
  })
})

const marketCount = computed(() => new Set(todayRows.value.map(r => r.market_id)).size)
// 不用 SelectValue 自动解析（列表项不在 SelectViewport 内时它取不到文本）
const selectedMarketLabel = computed(() => {
  if (marketFilter.value === RANGE_ALL) return '全部市场'
  return marketOptions.value.find(o => o.value === marketFilter.value)?.label || '全部市场'
})
// 曲线数跟随筛选，避免「报价 7 / 曲线 120」这种口径打架
const seriesCount = computed(
  () => new Set(todayRows.value.map(r => r.market_id + '|' + r.product_id + '|' + r.spec_id)).size,
)

function chgClass(v: number | null) {
  if (v == null) return 'chg flat'
  return 'chg ' + (v > 0 ? 'up' : v < 0 ? 'down' : 'flat')
}
function chgText(v: number | null) {
  if (v == null) return '—'
  return (v > 0 ? '+' : '') + v.toFixed(1) + '%'
}
</script>

<template>
  <div>
    <PageHero
      :slim="false"
      pill="FRESH DAILY · NO.001"
      en="TIDE / SEAFOOD PRICE DAILY"
      title="潮汐 · 水产鲜度日报"
      sub="全国水产技术推广总站「水产时价云」官方数据 · 沈阳核心 + 辽宁 + 全国 59 个批发市场 · 仅冷冻水产"
    />

    <div class="stats">
      <div class="stat">
        <div class="ic"><svg viewBox="0 0 24 24"><path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/></svg></div>
        <div class="lbl">当日报价 / QUOTES</div><div class="num">{{ todayRows.length }}</div>
        <div class="foot">{{ marketCount }} 个市场 · {{ marketFilter === RANGE_ALL ? rangeLabel[range] : selectedMarketLabel }}</div>
      </div>
      <div class="stat">
        <div class="ic"><svg viewBox="0 0 24 24"><path d="M12 2v20M2 12h20"/><circle cx="12" cy="12" r="9"/></svg></div>
        <div class="lbl">品种规格 / SERIES</div><div class="num">{{ seriesCount }}</div><div class="foot">当前范围 · 在跟踪的曲线</div>
      </div>
      <div class="stat">
        <div class="ic"><svg viewBox="0 0 24 24"><path d="M3 17l6-6 4 4 8-8"/><path d="M21 7v6h-6"/></svg></div>
        <div class="lbl">上涨 / ADVANCING</div><div class="num">{{ upCnt }}</div><div class="foot">较上一观测</div>
      </div>
      <div class="stat">
        <div class="ic"><svg viewBox="0 0 24 24"><path d="M3 7l6 6 4-4 8 8"/><path d="M21 17v-6h-6"/></svg></div>
        <div class="lbl">下跌 / DECLINING</div><div class="num">{{ downCnt }}</div><div class="foot">较上一观测</div>
      </div>
    </div>

    <section class="card">
      <div class="card-head">
        <span class="badge"><svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h16"/></svg></span>
        <h2>当日报价</h2><span class="hint">AS OF {{ meta.latest_date || '—' }}</span>
      </div>
      <div class="card-body">
        <div class="filters">
          <div class="fg">
            <label>范围 / SCOPE</label>
            <div class="seg">
              <button
                v-for="r in [RANGE_ALL, RANGE_CORE, RANGE_LN, RANGE_NATL]"
                :key="r" type="button" :class="{ active: range === r }"
                @click="range = r"
              >{{ rangeLabel[r] }}</button>
            </div>
          </div>
          <div class="fg">
            <label>市场 / MARKET</label>
            <SearchSelect
              v-model="marketFilter"
              :options="marketOptions"
              all-label="全部市场"
              placeholder="搜索市场"
              aria-label="搜索市场"
            />
          </div>
          <div class="fg">
            <label>品种 / PRODUCT</label>
            <SearchSelect
              v-model="productFilter"
              :options="productOptions"
              all-label="全部品种"
              placeholder="搜索品种"
              aria-label="搜索品种"
            />
          </div>
        </div>

        <div class="tbl-wrap">
          <table>
            <thead><tr>
              <th>市场</th><th>品种</th><th>规格</th>
              <th class="num">报价 元/kg</th><th class="num">约合 元/斤</th><th class="num">较上期</th><th class="num">较7天前</th>
            </tr></thead>
            <tbody>
              <tr v-if="!todayRows.length">
                <td colspan="7" class="empty-row">没有符合当前筛选的报价，试试放宽市场或品种条件</td>
              </tr>
              <tr v-for="(r, i) in todayRows" :key="i" :class="{ alert: r.alert }">
                <td><span class="mkt" :class="{ b: r.market_id === 538 }" :title="r.marketFull">{{ r.market }}</span></td>
                <td class="prod">{{ r.product_name }}</td>
                <td class="spec">{{ r.spec }}</td>
                <td class="num"><span class="price">{{ r.price.toFixed(2) }}</span></td>
                <td class="num"><span class="price-jin">{{ (r.price / 2).toFixed(2) }}</span></td>
                <td class="num"><span :class="chgClass(r.d1)">{{ chgText(r.d1) }}</span></td>
                <td class="num"><span :class="chgClass(r.d7)">{{ chgText(r.d7) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="legend">
          涨跌按「市场+品种+规格」各自序列计算，取最近一次有效观测（跳过缺报日，不补 0）。<b class="up">红=涨</b>、<b class="down">绿=跌</b>；黄底行为涨跌超 ±{{ (THR * 100).toFixed(0) }}% 的异常项。
          沈阳两家为每日核心观测，辽宁其他与全国市场为同平台参考报价，跨市场价差主要来自产地、规格与运输成本。
          新纳入的市场需累积 2 天以上，才会出现「较上期」对比值。
        </div>
      </div>
    </section>

    <SiteFooter>
      <NuxtLink to="/trend">价格走势</NuxtLink> ·
      <NuxtLink to="/specs">全国规格</NuxtLink> ·
      <NuxtLink to="/history">历史明细</NuxtLink>
    </SiteFooter>
  </div>
</template>
