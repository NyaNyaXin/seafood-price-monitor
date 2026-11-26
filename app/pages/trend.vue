<script setup lang="ts">
import * as echarts from 'echarts'
import { usePriceData } from '~/composables/usePriceData'

useHead({ title: '价格走势' })

const { trends, obs } = usePriceData()

// 只看品种：曲线是平台「全国 / 辽宁」的区域聚合价，
// 与单个市场无关，所以这里不设市场筛选（设了反而会误导）。
const productId = ref('')

const productOptions = computed(() =>
  Object.entries(trends.value)
    .map(([pid, t]) => ({ value: pid, label: t?.name || `品种${pid}` }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh')),
)

const chosen = computed(() => (productId.value ? trends.value[+productId.value] ?? null : null))
const hasSeries = computed(() => !!(chosen.value?.x?.length))

/**
 * 实际数据区间：平台对长期无报送的品种（如进口带鱼）会返回很久以前的 30 条，
 * 标题写「30天」会误导，这里标出真实首末日期与点数，跨度超 45 天给警示。
 */
const pointInfo = computed(() => {
  const t = chosen.value
  if (!t) return { text: '—', count: 0, stale: false }
  const pts = t.x
    .map((d, i) => ({ d, has: t.cn[i] != null || t.ln[i] != null }))
    .filter((p) => p.has)
  const first = pts[0]
  const last = pts[pts.length - 1]
  if (!first || !last) return { text: '—', count: 0, stale: false }
  const span = (new Date(last.d + 'T00:00:00').getTime() - new Date(first.d + 'T00:00:00').getTime()) / 86400000
  return { text: `${first.d} ~ ${last.d}`, count: pts.length, stale: span > 45 }
})

/**
 * 本地采集分档走势：只用 price_obs（每日市场快照），按规格档位分线，
 * 同一档位同一天跨市场取中位数，不做跨档位平均（避免统货/小规格互相拉偏）。
 * 只保留至少 2 天数据的档位，最多 8 条，按数据点数降序。
 */
interface LocalSpecSeries {
  name: string
  pts: { date: string; price: number }[]
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  const hi = sorted[mid]
  const lo = sorted[mid - 1]
  if (sorted.length % 2 === 1) return hi ?? 0
  return lo != null && hi != null ? (lo + hi) / 2 : (hi ?? lo ?? 0)
}

const localSpecs = computed<LocalSpecSeries[]>(() => {
  const pid = Number(productId.value)
  if (!pid) return []
  const bySpec = new Map<string, Map<string, number[]>>()
  for (const o of obs.value) {
    if (o.product_id !== pid) continue
    const spec = (o.spec_name || '').trim()
    if (!spec || spec === '/') continue
    let dates = bySpec.get(spec)
    if (!dates) {
      dates = new Map<string, number[]>()
      bySpec.set(spec, dates)
    }
    const arr = dates.get(o.obs_date)
    if (arr) arr.push(o.price)
    else dates.set(o.obs_date, [o.price])
  }

  const out: LocalSpecSeries[] = []
  for (const [name, dates] of bySpec) {
    const pts = [...dates.entries()]
      .map(([date, prices]) => ({ date, price: median(prices) }))
      .sort((a, b) => a.date.localeCompare(b.date))
    if (pts.length < 2) continue
    out.push({ name, pts })
  }
  return out.sort((a, b) => b.pts.length - a.pts.length).slice(0, 8)
})

const localRange = computed(() => {
  const dates = localSpecs.value.flatMap((s) => s.pts.map((p) => p.date)).sort()
  const first = dates[0]
  const last = dates[dates.length - 1]
  return first && last ? `${first} ~ ${last}` : '—'
})

// ECharts —— 静态引入：本页是独立路由 chunk，只有访问 /trend 才加载，
// 体积与动态 import 相当，但不会出现「import() 请求挂起、回调永不返回」的坑。
const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

/**
 * ECharts 拿不到 CSS 变量，必须显式给色值。
 * 主题切换时重绘：暗色下全国线用浅色、辽宁线用亮蓝，否则近黑线在暗底上看不见。
 */
const SCHEMES = {
  light: {
    strong: '#0f1113', text: '#4a5054', muted: '#8b908f',
    axis: '#0f1113', split: '#ecece4',
    tipBg: '#ffffff', tipBorder: '#0f1113', tipShadow: 'rgba(15,17,19,.10)',
    l1: '#0f1113', l2: '#1f4e79', fill: 'rgba(15,17,19,.05)',
  },
  dark: {
    strong: '#e9edf0', text: '#a2abb2', muted: '#6b747b',
    axis: '#3a4249', split: '#1f2428',
    tipBg: '#14181b', tipBorder: '#3a4249', tipShadow: 'rgba(0,0,0,.55)',
    l1: '#e9edf0', l2: '#63a4dd', fill: 'rgba(233,237,240,.06)',
  },
}
const isDark = ref(false)

async function drawChart() {
  const t = chosen.value
  if (!t || !hasSeries.value) return
  await nextTick()
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value, undefined, { renderer: 'canvas' })
  const c = isDark.value ? SCHEMES.dark : SCHEMES.light
  const palette = [c.l1, c.l2]
  const valid = t.x.map((d, i) => ({ d, cn: t.cn[i], ln: t.ln[i] }))
    .filter(r => r.cn != null || r.ln != null)
  const dates = valid.map(r => r.d)
  const hasLn = valid.some(r => r.ln != null)
  const hasCn = valid.some(r => r.cn != null)

  chart.setOption({
    // 关掉入场动画：容器在首次 setOption 时可能正因 guide->chart 切换而重排，
    // 动画被打断会停在首帧（表现为只画出第一个点）。30 点小图不需要动画。
    animation: false,
    backgroundColor: 'transparent', color: palette,
    textStyle: { fontFamily: 'JetBrains Mono, monospace', color: c.text },
    title: { text: t.name + ' · 30天价格走势', left: 'center', top: 0,
      textStyle: { fontSize: 13, color: c.strong, fontWeight: 700,
        fontFamily: 'Microsoft YaHei, PingFang SC, sans-serif' } },
    tooltip: { trigger: 'axis', backgroundColor: c.tipBg, borderColor: c.tipBorder, borderWidth: 1,
      padding: [9, 12], textStyle: { color: c.strong, fontFamily: 'JetBrains Mono, monospace', fontSize: 11.5 },
      extraCssText: `box-shadow:4px 4px 0 ${c.tipShadow};border-radius:0;`,
      valueFormatter: (v: unknown) => {
        const n = typeof v === 'number' ? v : Number(v)
        return Number.isFinite(n) ? `${n.toFixed(2)} 元/kg · ${(n / 2).toFixed(2)} 元/斤` : '—'
      } },
    legend: { type: 'plain', top: 30, itemWidth: 16, itemHeight: 2, itemGap: 18,
      textStyle: { color: c.text, fontSize: 11, fontFamily: 'Microsoft YaHei, sans-serif' },
      data: [...(hasCn ? ['全国'] : []), ...(hasLn ? ['辽宁'] : [])] },
    grid: { left: 52, right: 22, top: 66, bottom: 52 },
    xAxis: { type: 'category', data: dates, boundaryGap: false,
      // 只显示月-日，避免完整日期挤在一起；完整日期留在 tooltip
      axisLabel: { color: c.muted, fontSize: 10.5, hideOverlap: true,
        formatter: (v: string) => v.slice(5) },
      axisLine: { lineStyle: { color: c.axis, width: 1 } }, axisTick: { show: false } },
    yAxis: { type: 'value', name: '元/kg', scale: true,
      nameTextStyle: { color: c.muted, fontSize: 10, padding: [0, 0, 0, -32] },
      axisLabel: { color: c.muted, fontSize: 10.5 }, axisLine: { show: false },
      splitLine: { lineStyle: { color: c.split, type: 'solid' } } },
    dataZoom: [
      { type: 'slider', height: 14, bottom: 10, start: 0, end: 100,
        borderColor: c.axis, fillerColor: c.fill,
        handleStyle: { color: c.strong, borderColor: c.strong },
        moveHandleStyle: { color: c.strong },
        dataBackground: { lineStyle: { color: c.l2, opacity: .5 }, areaStyle: { color: c.l1, opacity: .07 } },
        textStyle: { color: c.muted, fontSize: 9.5, fontFamily: 'JetBrains Mono, monospace' } },
      { type: 'inside' }],
    series: [
      { name: '全国', type: 'line', data: valid.map(r => r.cn), connectNulls: false,
        smooth: false, symbol: 'circle', symbolSize: 4,
        lineStyle: { width: 2, color: palette[0] }, itemStyle: { color: palette[0] } },
      { name: '辽宁', type: 'line', data: valid.map(r => r.ln), connectNulls: false,
        smooth: false, symbol: 'circle', symbolSize: 4,
        lineStyle: { width: 2, color: palette[1] }, itemStyle: { color: palette[1] } },
    ],
  }, true)
  // 首帧高度可能受上方 guide→chart 切换影响，强制校正一次
  chart.resize()
}

/* 本地采集线色板：按规格档位分色，亮暗各一套 */
const LOCAL_LIGHT = ['#0f1113', '#1f4e79', '#8a5a00', '#2f6b3a', '#7a2e2e', '#5b4b8a', '#0b6b6b', '#8a6d1f']
const LOCAL_DARK = ['#e9edf0', '#63a4dd', '#e0b050', '#63c98a', '#e07a6e', '#a89ad8', '#5cc9c9', '#d8b56a']

const localEl = ref<HTMLDivElement | null>(null)
let localChart: echarts.ECharts | null = null

function drawLocalChart() {
  if (!localEl.value) return
  const specs = localSpecs.value
  if (!specs.length) {
    localChart?.clear()
    return
  }
  if (!localChart) localChart = echarts.init(localEl.value, undefined, { renderer: 'canvas' })

  const c = isDark.value ? SCHEMES.dark : SCHEMES.light
  const colors = isDark.value ? LOCAL_DARK : LOCAL_LIGHT
  const dates = [...new Set(specs.flatMap((s) => s.pts.map((p) => p.date)))].sort()
  const series = specs.map((s, i) => {
    const color = colors[i % colors.length] ?? c.strong
    const byDate = new Map(s.pts.map((p) => [p.date, p.price]))
    return {
      name: s.name,
      type: 'line' as const,
      data: dates.map((d) => byDate.get(d) ?? null),
      connectNulls: false,
      smooth: false,
      symbol: 'circle',
      symbolSize: 4,
      lineStyle: { width: 1.6, color },
      itemStyle: { color },
    }
  })

  localChart.setOption({
    animation: false,
    backgroundColor: 'transparent',
    color: colors,
    textStyle: { fontFamily: 'JetBrains Mono, monospace', color: c.text },
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.tipBg,
      borderColor: c.tipBorder,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: c.strong, fontFamily: 'JetBrains Mono, monospace', fontSize: 11 },
      extraCssText: `box-shadow:3px 3px 0 ${c.tipShadow};border-radius:0;`,
      valueFormatter: (v: unknown) => {
        const n = typeof v === 'number' ? v : Number(v)
        return Number.isFinite(n) ? `${n.toFixed(2)} 元/kg` : '—'
      },
    },
    legend: {
      type: 'scroll',
      top: 0,
      left: 'center',
      itemWidth: 14,
      itemHeight: 2,
      itemGap: 14,
      textStyle: { color: c.text, fontSize: 10, fontFamily: 'Microsoft YaHei, sans-serif' },
    },
    grid: { left: 52, right: 22, top: 44, bottom: 34 },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLabel: { color: c.muted, fontSize: 10, hideOverlap: true,
        formatter: (v: string) => v.slice(5) },
      axisLine: { lineStyle: { color: c.axis, width: 1 } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: '元/kg',
      scale: true,
      nameTextStyle: { color: c.muted, fontSize: 10, padding: [0, 0, 0, -32] },
      axisLabel: { color: c.muted, fontSize: 10 },
      axisLine: { show: false },
      splitLine: { lineStyle: { color: c.split } },
    },
    series,
  }, true)
  localChart.resize()
}

watch(productId, () => {
  if (productId.value) {
    void nextTick(() => {
      drawChart()
      drawLocalChart()
    })
  } else {
    chart?.clear()
    localChart?.clear()
  }
})

watch(localSpecs, () => {
  if (productId.value) void nextTick(drawLocalChart)
})

function onResize() {
  chart?.resize()
  localChart?.resize()
}

let mql: MediaQueryList | null = null
function onScheme(e: MediaQueryListEvent) {
  isDark.value = e.matches
  if (productId.value) void nextTick(() => { drawChart(); drawLocalChart() })
}

onMounted(() => {
  mql = window.matchMedia('(prefers-color-scheme: dark)')
  isDark.value = mql.matches
  window.addEventListener('resize', onResize)
  mql.addEventListener('change', onScheme)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  mql?.removeEventListener('change', onScheme)
  chart?.dispose()
  chart = null
  localChart?.dispose()
  localChart = null
})
</script>

<template>
  <div>
    <PageHero
      pill="PRICE TREND · 30D"
      en="30-DAY PRICE CURVE"
      title="价格走势"
      sub="平台 30 天序列（全国 / 辽宁） + 本地每日采集分档走势 · 选品种后展示"
    />

    <section class="card">
      <div class="card-head">
        <span class="badge"><svg viewBox="0 0 24 24"><path d="M3 3v18h18"/><path d="M7 14l3-4 3 2 5-6"/></svg></span>
        <h2>价格走势</h2><span class="hint">Price History / 元·KG⁻¹</span>
      </div>
      <div class="card-body">
        <div class="filters">
          <div class="fg">
            <label>品种 / Product</label>
            <SearchSelect
              v-model="productId"
              :options="productOptions"
              placeholder="搜索品种，如 带鱼"
              aria-label="搜索品种"
            />
          </div>
        </div>

        <div v-if="!productId" class="chart-guide">
          <div class="big">30<small>天</small></div>
          <h3>选择一个品种，查看它的 30 天价格曲线</h3>
          <p>平台提供现成的 30 天历史序列（全国 + 辽宁双线），无需等待每日采集累积。选中后此处只展示该品种的走势。</p>
          <div class="steps">
            <span class="step"><b>1</b> 选品种</span>
            <span class="step"><b>2</b> 看曲线</span>
          </div>
        </div>

        <div v-else>
          <div v-show="hasSeries" ref="chartEl" id="chart" />
          <div v-if="!hasSeries" class="empty"><div class="wave">〜 〜 〜</div><div>该品种暂无历史序列</div></div>

          <div class="local-trend">
            <div class="local-trend-head">
              <b>本地采集 · 分档走势</b>
              <span>{{ localRange }} · 同档跨市场取中位</span>
            </div>
            <div class="local-chart-wrap">
              <div ref="localEl" id="local-chart" class="local-chart" />
              <div v-if="!localSpecs.length" class="local-empty">
                该品种暂无本地采集数据，需先采集至少 2 天同一规格
              </div>
            </div>
          </div>
        </div>
        <div class="chart-note">
          <span class="range-chip" :class="{ warn: pointInfo.stale }">
            数据区间 {{ pointInfo.text }} · 共 {{ pointInfo.count }} 个有效点
            <template v-if="pointInfo.stale">· 该品种近期无报送，展示的是历史片段</template>
          </span>
          <br />
          全国线为平台全国报送均价，辽宁线为辽宁报送均价（平台现成 30 天序列，非本系统自攒）。断点=当日该区无报送。口径为平台聚合价，与首页市场成交报价不同；曲线不按单个市场拆分。
          <br />
          下方本地采集线来自每日市场快照（<code>price_obs</code>），按规格档位分线、同档跨市场取中位数，只覆盖本系统开始采集后的日期，与上方平台聚合序列口径不同，不可直接横向比价。
        </div>
      </div>
    </section>

    <SiteFooter source="GetPriceList">
      <NuxtLink to="/">今日概览</NuxtLink> ·
      <NuxtLink to="/specs">全国规格</NuxtLink> ·
      <NuxtLink to="/history">历史明细</NuxtLink>
    </SiteFooter>
  </div>
</template>
