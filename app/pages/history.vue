<script setup lang="ts">
import { usePriceData, shortMkt, fullMkt } from '~/composables/usePriceData'

useHead({ title: '历史明细' })

const { obs, meta, pending } = usePriceData()

const ALL = '__all__'
const marketFilter = ref<string>(ALL)
const productFilter = ref<string>(ALL)

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

const hist = computed(() => obs.value
  .filter(o => marketFilter.value === ALL || String(o.market_id) === marketFilter.value)
  .filter(o => productFilter.value === ALL || String(o.product_id) === productFilter.value)
  .slice()
  .sort((a, b) => b.obs_date.localeCompare(a.obs_date) || a.market_id - b.market_id)
  .slice(0, 50))
</script>

<template>
  <div>
    <PageHero
      pill="ARCHIVE · LATEST 50"
      en="OBSERVATION ARCHIVE"
      title="历史明细"
      sub="本地每日自存的市场成交报价 · 按市场筛选 · 仅冷冻水产"
    />

    <section class="card">
      <div class="card-head">
        <span class="badge"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg></span>
        <h2>历史明细</h2><span class="hint">Latest 50 / 倒序</span>
      </div>
      <div class="card-body">
        <div class="filters">
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
              <th style="width:11%">日期</th><th style="width:26%">市场</th><th style="width:20%">品种</th>
              <th style="width:23%">规格</th><th class="num" style="width:10%">价格 元/kg</th>
              <th class="num" style="width:10%">约合 元/斤</th>
            </tr></thead>
            <TableSkeleton v-if="pending" :rows="10" :cols="6" />
            <tbody v-else>
              <tr v-if="!hist.length">
                <td colspan="6" class="empty-row">没有符合当前筛选的记录，试试放宽市场或品种条件</td>
              </tr>
              <tr v-for="(o, i) in hist" :key="i">
                <td class="spec">{{ o.obs_date }}</td>
                <td><span class="mkt" :class="{ b: o.market_id === 538 }" :title="fullMkt(o.market_id, meta)">{{ shortMkt(o.market_id, meta) }}</span></td>
                <td class="prod">{{ o.product_name }}</td>
                <td class="spec">{{ o.spec_name && o.spec_name !== '/' ? o.spec_name : '—' }}</td>
                <td class="num"><span class="price">{{ o.price.toFixed(2) }}</span></td>
                <td class="num"><span class="price-jin">{{ (o.price / 2).toFixed(2) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="legend">本表为本地采集脚本每日自存的报价流水（<code>GetPriceNow</code> 快照，全国 59 市场白名单），与走势页的平台现成 30 天序列口径不同。</div>
      </div>
    </section>

    <SiteFooter source="GetPriceNow · PostgreSQL">
      <NuxtLink to="/">今日概览</NuxtLink> ·
      <NuxtLink to="/trend">价格走势</NuxtLink> ·
      <NuxtLink to="/specs">全国规格</NuxtLink>
    </SiteFooter>
  </div>
</template>
