<script setup lang="ts">
import { usePriceData, shortMkt, fullMkt } from '~/composables/usePriceData'

useHead({ title: '历史明细' })

const { obs, meta, pending } = usePriceData()

const ALL = '__all__'
/** 日期用原生日期值：'' = 全部日期（组件内部转成 DateValue） */
const dateFilter = ref<string>('')
const marketFilter = ref<string>(ALL)
const productFilter = ref<string>(ALL)

/** 实际有报送的日期（倒序）与条数：日历打点 + 限定可翻范围 */
const dateStats = computed(() => {
  const count = new Map<string, number>()
  for (const o of obs.value) count.set(o.obs_date, (count.get(o.obs_date) ?? 0) + 1)
  return [...count.entries()]
    .sort((a, b) => b[0].localeCompare(a[0]))
    .map(([date, count]) => ({ date, count }))
})
const availableDates = computed(() => dateStats.value.map(s => s.date))
const dateBounds = computed(() => {
  const ds = availableDates.value
  return { min: ds[ds.length - 1] ?? '', max: ds[0] ?? '' }
})

const marketOptions = computed(() => {
  const ids = [...new Set(obs.value.map(o => o.market_id))]
  return ids
    .map(id => ({ value: String(id), label: shortMkt(id, meta.value), hint: fullMkt(id, meta.value) }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh'))
})

const productOptions = computed(() => {
  const m = new Map<number, string>()
  for (const o of obs.value) m.set(o.product_id, o.product_name)
  return [...m.entries()]
    .map(([id, name]) => ({ value: String(id), label: name }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh'))
})

/** 三个条件过滤后的完整结果（倒序），条数与截断判定都基于它 */
const filtered = computed(() => obs.value
  .filter(o => !dateFilter.value || o.obs_date === dateFilter.value)
  .filter(o => marketFilter.value === ALL || String(o.market_id) === marketFilter.value)
  .filter(o => productFilter.value === ALL || String(o.product_id) === productFilter.value)
  .slice()
  .sort((a, b) => b.obs_date.localeCompare(a.obs_date) || a.market_id - b.market_id))

/**
 * 客户端分页：每页 50 条。数据来自 /api/price-data 的全量观测，
 * 统一分页后不再区分「是否选了日期」——某天记录超过 50 条也能翻页看完。
 */
const PAGE_SIZE = 50
const page = ref(1)
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)))
const hist = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE
  return filtered.value.slice(start, start + PAGE_SIZE)
})
const countHint = computed(() => `${filtered.value.length} 条 · 倒序`)

/** 翻页后回到表头，避免停留在页面底部看不到新一页的数据 */
const tableEl = ref<HTMLElement | null>(null)
function scrollToTable() {
  const el = tableEl.value
  if (!el) return
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
}

async function prevPage() {
  if (page.value <= 1) return
  page.value--
  await nextTick()
  scrollToTable()
}
async function nextPage() {
  if (page.value >= pageCount.value) return
  page.value++
  await nextTick()
  scrollToTable()
}

// 筛选条件变化回到第一页；数据刷新后页码越界自动收回
watch([dateFilter, marketFilter, productFilter], () => { page.value = 1 })
watch(pageCount, (n) => { if (page.value > n) page.value = n })
</script>

<template>
  <div>
    <PageHero
      pill="ARCHIVE · BY DATE"
      en="OBSERVATION ARCHIVE"
      title="历史明细"
      sub="本地每日自存的市场成交报价 · 按日期 / 市场 / 品种筛选 · 仅冷冻水产"
    />

    <section class="card">
      <div class="card-head">
        <span class="badge"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg></span>
        <h2>历史明细</h2><span class="hint">{{ countHint }}</span>
      </div>
      <div class="card-body">
        <div class="filters">
          <div class="fg">
            <label>日期 / DATE <span class="fg-note">{{ dateStats.length }} 天有报送</span></label>
            <DateField
              v-model="dateFilter"
              :min="dateBounds.min"
              :max="dateBounds.max"
              :available-dates="availableDates"
            />
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

        <div ref="tableEl" class="tbl-wrap">
          <table>
            <thead><tr>
              <th style="width:11%">日期</th><th style="width:26%">市场</th><th style="width:20%">品种</th>
              <th style="width:23%">规格</th><th class="num" style="width:10%">价格 元/kg</th>
              <th class="num" style="width:10%">约合 元/斤</th>
            </tr></thead>
            <TableSkeleton v-if="pending" :rows="10" :cols="6" />
            <tbody v-else>
              <tr v-if="!hist.length">
                <td colspan="6" class="empty-row">没有符合当前筛选的记录，试试放宽日期、市场或品种条件</td>
              </tr>
              <tr v-for="(o, i) in hist" :key="i">
                <td class="spec" data-label="日期">{{ o.obs_date }}</td>
                <td data-label="市场"><span class="mkt" :class="{ b: o.market_id === 538 }" :title="fullMkt(o.market_id, meta)">{{ shortMkt(o.market_id, meta) }}</span></td>
                <td class="prod" data-label="品种">{{ o.product_name }}</td>
                <td class="spec" data-label="规格">{{ o.spec_name && o.spec_name !== '/' ? o.spec_name : '—' }}</td>
                <td class="num" data-label="价格"><span class="price">{{ o.price.toFixed(2) }}</span></td>
                <td class="num" data-label="约合元/斤"><span class="price-jin">{{ (o.price / 2).toFixed(2) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="pageCount > 1" class="pager">
          <span>共 {{ filtered.length }} 条</span>
          <button type="button" :disabled="page <= 1" @click="prevPage">上一页</button>
          <span>第 <b>{{ page }}</b> / {{ pageCount }} 页</span>
          <button type="button" :disabled="page >= pageCount" @click="nextPage">下一页</button>
        </div>
        <div class="legend">本表为本地采集脚本每日自存的报价流水（<code>GetPriceNow</code> 快照，全国 59 市场白名单），与走势页的平台现成 30 天序列口径不同。日期为采集当日的本地日期（<code>Asia/Shanghai</code>）；按日期、市场、品种筛选后分页展示，每页 50 条。</div>
      </div>
    </section>

    <SiteFooter source="GetPriceNow · PostgreSQL">
      <NuxtLink to="/">今日概览</NuxtLink> ·
      <NuxtLink to="/trend">价格走势</NuxtLink> ·
      <NuxtLink to="/specs">全国规格</NuxtLink>
    </SiteFooter>
  </div>
</template>
