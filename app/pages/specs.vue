<script setup lang="ts">
import { usePriceData } from '~/composables/usePriceData'

useHead({ title: '全国品类规格' })

const { meta, specs, pending } = usePriceData()

const region = ref<'cn' | 'ln'>('cn')
const keyword = ref('')

// 覆盖率：以采集清单为准
const catalog = computed(() => meta.value.catalog || {})
const total = computed(() => Object.keys(catalog.value).length || meta.value.catalog_total || 29)
const cnPids = computed(() => [...new Set(specs.value.filter(s => s.region === 'cn').map(s => s.product_id))])
const covered = computed(() => cnPids.value.length)
const coverWidth = computed(() => total.value ? (covered.value / total.value * 100).toFixed(1) + '%' : '0%')
const coverText = computed(() => `${covered.value} / ${total.value} 品种 · ${specs.value.filter(s => s.region === 'cn').length} 档`)
const missing = computed(() => Object.keys(catalog.value)
  .filter(pid => !cnPids.value.includes(+pid))
  .map(pid => catalog.value[pid]))

const rows = computed(() => specs.value.filter(s =>
  s.region === region.value && (!keyword.value || s.product_name.includes(keyword.value))))

interface ProductGroup { name: string; cat: string; items: typeof specs.value }
const groups = computed(() => {
  const map = new Map<string, ProductGroup>()
  for (const s of rows.value) {
    const k = (s.category || '其他') + '|' + s.product_id
    if (!map.has(k)) map.set(k, { name: s.product_name, cat: s.category || '其他', items: [] })
    map.get(k)!.items.push(s)
  }
  const byCat = new Map<string, ProductGroup[]>()
  for (const g of map.values()) {
    if (!byCat.has(g.cat)) byCat.set(g.cat, [])
    byCat.get(g.cat)!.push(g)
  }
  return [...byCat.entries()].map(([cat, list]) => ({ cat, count: list.length, products: list }))
})
</script>

<template>
  <div>
    <PageHero
      pill="SPEC REFERENCE · NATIONWIDE"
      en="NATIONWIDE GRADE PRICES"
      title="全国品类规格"
      sub="按品种分规格的比价参考 · 全国 / 辽宁双区域 · 仅冷冻水产"
    />

    <section class="card">
      <div class="card-head">
        <span class="badge"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/></svg></span>
        <h2>全国品类规格</h2><span class="hint">分规格参考价 / 元·KG⁻¹</span>
      </div>
      <div class="card-body">
        <div class="cover-bar">
          <span class="lbl">数据覆盖</span>
          <div class="track"><div class="fill" :style="{ width: pending ? '0%' : coverWidth }" /></div>
          <span v-if="pending" class="sk short" style="width:132px" />
          <span v-else class="val">{{ coverText }}</span>
          <span v-if="!pending" class="miss">缺 {{ missing.length }} 种：{{ missing.join('、') }}</span>
        </div>
        <div class="nation-note">
          辽宁本地市场分规格报送不全（多数只有 1~2 档）。这里展示<strong>全国各市场的分规格报价</strong>作参考——
          <span class="region-tag cn">全国</span> 是全国均价、<span class="region-tag ln">辽宁</span> 是辽宁报送价。与首页的沈阳成交报价口径不同，仅供规格比价参考。
        </div>

        <div class="spec-tabs" style="margin-bottom:14px">
          <TabsRoot v-model="region" class="ui-tabs">
            <TabsList class="ui-tabs-list">
              <TabsTrigger value="cn" class="ui-tabs-trigger">全国</TabsTrigger>
              <TabsTrigger value="ln" class="ui-tabs-trigger">辽宁</TabsTrigger>
            </TabsList>
          </TabsRoot>
          <input v-model="keyword" class="spec-search" placeholder="搜索品种名，如 带鱼 / 对虾 / 扇贝…">
          <span class="hint" style="white-space:nowrap">{{ rows.length }} 档</span>
        </div>

        <div v-if="pending" class="spec-grid">
          <div v-for="n in 8" :key="'sk' + n" class="spec-card">
            <div class="spec-card-head">
              <span class="sk short" style="width:52%" />
              <span class="sk short" style="width:14%;margin-left:auto" />
            </div>
            <div v-for="m in 3" :key="m" class="spec-line">
              <span class="sk short" :style="{ width: (30 + m * 5) + '%' }" />
              <span class="sk short" style="width:22%" />
            </div>
          </div>
        </div>
        <template v-else>
          <div v-if="!rows.length" class="empty-inline">该区域暂无分规格报送数据</div>
          <div v-for="g in groups" :key="g.cat" class="cat-group">
            <div class="cat-title">{{ g.cat }} <span class="n">{{ g.count }} 个品种</span></div>
            <div class="spec-grid">
              <div v-for="p in g.products" :key="p.name" class="spec-card">
                <div class="spec-card-head">
                  <span class="nm">{{ p.name }}</span>
                  <span class="region-tag" :class="region">{{ region === 'cn' ? '全国' : '辽宁' }}</span>
                  <span class="cnt">{{ p.items.length }} 档</span>
                </div>
                <div
                  v-for="it in [...p.items].sort((a, b) => b.price - a.price)"
                  :key="it.product_id + it.spec_name"
                  class="spec-line"
                >
                  <span class="sp">{{ it.spec_name }}</span>
                  <span class="pr"><b>{{ it.price.toFixed(2) }}</b><i>¥{{ (it.price / 2).toFixed(2) }}</i></span>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>
    </section>

    <SiteFooter source="GetPriceList">
      <NuxtLink to="/">今日概览</NuxtLink> ·
      <NuxtLink to="/trend">价格走势</NuxtLink> ·
      <NuxtLink to="/history">历史明细</NuxtLink>
    </SiteFooter>
  </div>
</template>
