<script setup lang="ts">
import { usePriceData } from '~/composables/usePriceData'

withDefaults(defineProps<{
  pill: string
  en: string
  title: string
  sub: string
  slim?: boolean
}>(), { slim: true })

const { meta, obs, freshness } = usePriceData()
const gen = computed(() => (meta.value.generated_at || '').replace('T', ' '))
</script>

<template>
  <header class="hero" :class="{ slim }">
    <span class="bubble b1" /><span class="bubble b2" /><span class="bubble b3" />
    <div class="hero-main">
      <div class="brand">
        <span class="pill">{{ pill }}</span>
        <h1><span class="en">{{ en }}</span>{{ title }}</h1>
        <div class="sub">{{ sub }}</div>
      </div>
      <div class="live"><span class="dot" />DATA FEED</div>
    </div>
    <div class="hero-foot">
      <span>📅 数据日期 <b>{{ meta.latest_date || '—' }}</b><span :class="freshness.cls">{{ freshness.text }}</span></span>
      <span>🕒 生成 <b>{{ gen }}</b></span>
      <span>📊 观测 <b>{{ meta.total_obs ?? obs.length }}</b> 条</span>
    </div>
  </header>
</template>
