<script setup lang="ts">
import * as echarts from 'echarts'
import { usePriceData } from '~/composables/usePriceData'

useHead({ title: '价格走势' })

const { trends } = usePriceData()

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

// ECharts —— 静态引入：本页是独立路由 chunk，只有访问 /trend 才加载，
// 体积与动态 import 相当，但不会出现「import() 请求挂起、回调永不返回」的坑。
const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

async function drawChart() {
  const t = chosen.value
  if (!t || !hasSeries.value) return
  await nextTick()
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value, undefined, { renderer: 'canvas' })
  const palette = ['#0ea5e9', '#10b981']
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
    textStyle: { fontFamily: 'IBM Plex Mono, monospace', color: '#5b6b7c' },
    title: { text: t.name + ' · 30天价格走势', left: 'center', top: 0,
      textStyle: { fontSize: 13, color: '#1f2a37', fontWeight: 700 } },
    tooltip: { trigger: 'axis', backgroundColor: '#ffffff', borderColor: '#d6e3e6', borderWidth: 1,
      padding: [10, 13], textStyle: { color: '#1f2a37', fontFamily: 'IBM Plex Mono, monospace', fontSize: 12 },
      extraCssText: 'box-shadow:0 8px 24px rgba(31,42,55,.14);border-radius:10px;',
      valueFormatter: (v: unknown) => {
        const n = typeof v === 'number' ? v : Number(v)
        return Number.isFinite(n) ? `${n.toFixed(2)} 元/kg · ${(n / 2).toFixed(2)} 元/斤` : '—'
      } },
    legend: { type: 'plain', top: 28, textStyle: { color: '#5b6b7c', fontSize: 11 },
      data: [...(hasCn ? ['全国'] : []), ...(hasLn ? ['辽宁'] : [])] },
    grid: { left: 56, right: 26, top: 64, bottom: 56 },
    xAxis: { type: 'category', data: dates, boundaryGap: false,
      // 只显示月-日，避免完整日期挤在一起；完整日期留在 tooltip
      axisLabel: { color: '#94a3b8', fontSize: 10.5, hideOverlap: true,
        formatter: (v: string) => v.slice(5) },
      axisLine: { lineStyle: { color: '#d6e3e6' } }, axisTick: { show: false } },
    yAxis: { type: 'value', name: '元/kg', scale: true,
      nameTextStyle: { color: '#94a3b8', fontSize: 10, padding: [0, 0, 0, -34] },
      axisLabel: { color: '#94a3b8', fontSize: 10.5 }, axisLine: { show: false },
      splitLine: { lineStyle: { color: 'rgba(31,42,55,.06)' } } },
    dataZoom: [
      { type: 'slider', height: 16, bottom: 12, start: 0, end: 100,
        borderColor: '#d6e3e6', fillerColor: 'rgba(16,185,129,.10)',
        handleStyle: { color: '#10b981', borderColor: '#10b981' },
        moveHandleStyle: { color: '#10b981' },
        dataBackground: { lineStyle: { color: '#0ea5e9', opacity: .4 }, areaStyle: { color: '#10b981', opacity: .10 } },
        textStyle: { color: '#94a3b8', fontSize: 10 } },
      { type: 'inside' }],
    series: [
      { name: '全国', type: 'line', data: valid.map(r => r.cn), connectNulls: false,
        smooth: false, symbol: 'circle', symbolSize: 5,
        lineStyle: { width: 2.4, color: palette[0] }, itemStyle: { color: palette[0] } },
      { name: '辽宁', type: 'line', data: valid.map(r => r.ln), connectNulls: false,
        smooth: false, symbol: 'circle', symbolSize: 5,
        lineStyle: { width: 2.4, color: palette[1] }, itemStyle: { color: palette[1] } },
    ],
  }, true)
  // 首帧高度可能受上方 guide→chart 切换影响，强制校正一次
  chart.resize()
}

watch(productId, () => {
  if (productId.value) nextTick(drawChart)
  else chart?.clear()
})

function onResize() { chart?.resize() }
onMounted(() => window.addEventListener('resize', onResize))
onUnmounted(() => { window.removeEventListener('resize', onResize); chart?.dispose(); chart = null })
</script>

<template>
  <div>
    <PageHero
      pill="PRICE TREND · 30D"
      en="30-DAY PRICE CURVE"
      title="价格走势"
      sub="平台现成 30 天序列 · 全国 / 辽宁双线 · 选品种后单独展示"
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
          <div class="big">📈</div>
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
        </div>
        <div class="chart-note">
          <span class="range-chip" :class="{ warn: pointInfo.stale }">
            数据区间 {{ pointInfo.text }} · 共 {{ pointInfo.count }} 个有效点
            <template v-if="pointInfo.stale">· 该品种近期无报送，展示的是历史片段</template>
          </span>
          <br />
          全国线为平台全国报送均价，辽宁线为辽宁报送均价（平台现成 30 天序列，非本系统自攒）。断点=当日该区无报送。口径为平台聚合价，与首页市场成交报价不同；曲线不按单个市场拆分。
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
