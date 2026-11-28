<script setup lang="ts">
import { usePriceData, shortMkt, fullMkt, marketTier, changeAt, changeDaysAgo } from '~/composables/usePriceData'

useHead({ title: '潮汐 TIDE · 沈阳水产鲜度日报' })

const { meta, latest, seriesMap, THR, pending } = usePriceData()

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

/** 首屏列表入场动画覆盖的行数：大屏一屏大约 25–35 行，取 30 */
const ENTER_ROWS = 30

const todayRows = computed(() => {
  const src = rangeRows.value
    .filter((o) => marketFilter.value === RANGE_ALL || String(o.market_id) === marketFilter.value)
    .filter((o) => productFilter.value === RANGE_ALL || String(o.product_id) === productFilter.value)
  return src.map(o => {
    const s = seriesMap.value[o.market_id + '|' + o.product_id + '|' + o.spec_id]
    const idx = s ? s.pts.findIndex(p => p.date === o.obs_date) : -1
    const d1 = s ? changeAt(s, idx) : null
    const d7 = s ? changeDaysAgo(s, idx, 7) : null
    // 上期价 = 同一「市场+品种+规格」序列里的上一次有效观测
    const prevPrice = s && idx > 0 ? (s.pts[idx - 1]?.price ?? null) : null
    return {
      ...o,
      market: shortMkt(o.market_id, meta.value),
      marketFull: fullMkt(o.market_id, meta.value),
      tier: marketTier(o.market_id, meta.value),
      spec: o.spec_name && o.spec_name !== '/' ? o.spec_name : '—',
      d1, d7,
      prevPrice,
      alert: d1 != null && Math.abs(d1) / 100 >= THR.value,
    }
  })
})

const marketCount = computed(() => new Set(todayRows.value.map(r => r.market_id)).size)

/** 当日异动：涨幅最大与跌幅最大各一条（无对比数据时为 null） */
const topUp = computed(() => {
  let best: (typeof todayRows.value)[number] | null = null
  for (const r of todayRows.value) {
    if (r.d1 == null || r.d1 <= 0) continue
    if (!best || r.d1 > (best.d1 ?? 0)) best = r
  }
  return best
})
const topDown = computed(() => {
  let best: (typeof todayRows.value)[number] | null = null
  for (const r of todayRows.value) {
    if (r.d1 == null || r.d1 >= 0) continue
    if (!best || r.d1 < (best.d1 ?? 0)) best = r
  }
  return best
})
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
function feedCls(v: number | null) {
  if (v == null) return 'flat'
  return v > 0 ? 'up' : v < 0 ? 'down' : 'flat'
}
function chgText(v: number | null) {
  if (v == null) return '—'
  return (v > 0 ? '+' : '') + v.toFixed(1) + '%'
}
</script>

<template>
  <div>
    <div v-if="pending" class="loadbar" />
    <PageHero
      :slim="false"
      pill="FRESH DAILY · NO.001"
      en="TIDE / SEAFOOD PRICE DAILY"
      title="潮汐 · 水产鲜度日报"
      sub="全国水产技术推广总站「水产时价云」官方数据 · 沈阳核心 + 辽宁 + 全国 59 个批发市场 · 仅冷冻水产"
    >
      <template #aside>
        <div class="feed">
          <div class="feed-head"><span class="dot" />当日异动 · TOP MOVERS</div>
          <template v-if="topUp || topDown">
            <div v-if="topUp" class="feed-row">
              <div class="feed-main">
                <span class="feed-name"><em class="feed-tag up">涨</em>{{ topUp.product_name }}</span>
                <b class="feed-chg" :class="feedCls(topUp.d1)">{{ chgText(topUp.d1) }}</b>
              </div>
              <div class="feed-sub">{{ topUp.market }} · {{ topUp.spec }} · {{ topUp.price.toFixed(2) }} 元/kg</div>
            </div>
            <div v-if="topDown" class="feed-row">
              <div class="feed-main">
                <span class="feed-name"><em class="feed-tag down">跌</em>{{ topDown.product_name }}</span>
                <b class="feed-chg" :class="feedCls(topDown.d1)">{{ chgText(topDown.d1) }}</b>
              </div>
              <div class="feed-sub">{{ topDown.market }} · {{ topDown.spec }} · {{ topDown.price.toFixed(2) }} 元/kg</div>
            </div>
          </template>
          <template v-else>
            <div class="feed-main"><span class="feed-name">今日暂无异动</span></div>
            <div class="feed-sub">同序列需两次观测才能算出涨跌</div>
          </template>
        </div>
      </template>
    </PageHero>

    <div class="tape">
      <div class="tape-cell">
        <span class="k">当日报价 / Quotes</span>
        <b class="v"><span v-if="pending" class="sk sk-num" /><AnimatedNumber v-else :value="todayRows.length" /></b>
        <span class="u"><span v-if="pending" class="sk short" style="width:72%" /><template v-else>{{ marketCount }} 个市场 · {{ marketFilter === RANGE_ALL ? rangeLabel[range] : selectedMarketLabel }}</template></span>
      </div>
      <div class="tape-cell">
        <span class="k">品种规格 / Series</span>
        <b class="v"><span v-if="pending" class="sk sk-num" /><AnimatedNumber v-else :value="seriesCount" /></b>
        <span class="u">当前范围在跟踪的曲线</span>
      </div>
      <div class="tape-cell" :class="{ hot: upCnt > 0 }">
        <span class="k">上涨 / Advancing</span>
        <b class="v"><span v-if="pending" class="sk sk-num" /><AnimatedNumber v-else :value="upCnt" /></b>
        <span class="u">较上一观测 · 红 = 涨</span>
      </div>
      <div class="tape-cell" :class="{ cool: downCnt > 0 }">
        <span class="k">下跌 / Declining</span>
        <b class="v"><span v-if="pending" class="sk sk-num" /><AnimatedNumber v-else :value="downCnt" /></b>
        <span class="u">较上一观测 · 绿 = 跌</span>
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
              <th style="width:15%">市场</th><th style="width:15%">品种</th><th style="width:23%">规格</th>
              <th class="num" style="width:11%">报价 元/kg</th><th class="num" style="width:10%">上期 元/kg</th>
              <th class="num" style="width:9%">约合 元/斤</th>
              <th class="num" style="width:9%">较上期</th><th class="num" style="width:8%">较7天前</th>
            </tr></thead>
            <TableSkeleton v-if="pending" :rows="8" :cols="8" />
            <tbody v-else>
              <tr v-if="!todayRows.length">
                <td colspan="8" class="empty-row">没有符合当前筛选的报价，试试放宽市场或品种条件</td>
              </tr>
              <tr
                v-for="(r, i) in todayRows"
                :key="i"
                :class="{ alert: r.alert, enter: i < ENTER_ROWS, up: r.d1 != null && r.d1 > 0, down: r.d1 != null && r.d1 < 0 }"
                :style="i < ENTER_ROWS ? { animationDelay: i * 18 + 'ms' } : undefined"
              >
                <td data-label="市场"><span class="mkt" :class="{ b: r.market_id === 538 }" :title="r.marketFull">{{ r.market }}</span></td>
                <td class="prod" data-label="品种">{{ r.product_name }}</td>
                <td class="spec" data-label="规格">{{ r.spec }}</td>
                <td class="num" data-label="报价"><span class="price">{{ r.price.toFixed(2) }}</span></td>
                <td class="num" data-label="上期"><span class="price-prev">{{ r.prevPrice != null ? r.prevPrice.toFixed(2) : '—' }}</span></td>
                <td class="num" data-label="约合元/斤"><span class="price-jin">{{ (r.price / 2).toFixed(2) }}</span></td>
                <td class="num" data-label="较上期"><span :class="chgClass(r.d1)">{{ chgText(r.d1) }}</span></td>
                <td class="num" data-label="较7天前"><span :class="chgClass(r.d7)">{{ chgText(r.d7) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="legend">
          涨跌按「市场+品种+规格」各自序列计算，取最近一次有效观测（跳过缺报日，不补 0）。<b class="up">红=涨</b>、<b class="down">绿=跌</b>；黄底行为涨跌超 ±{{ (THR * 100).toFixed(0) }}% 的异常项。
          「上期」为同一序列的上一次有效观测价，首日或无历史时显示「—」。
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
