<script setup lang="ts">
import { usePriceData } from '~/composables/usePriceData'

withDefaults(defineProps<{
  pill: string
  en: string
  title: string
  sub: string
  slim?: boolean
}>(), { slim: true })

const { meta, obs, freshness, pending, reload } = usePriceData()
const gen = computed(() => (meta.value.generated_at || '').replace('T', ' ').slice(0, 16))
</script>

<template>
  <header class="hero" :class="{ slim }">
    <div class="hero-main">
      <div class="brand">
        <span class="pill">{{ pill }}</span>
        <h1><span class="en">{{ en }}</span>{{ title }}</h1>
        <div class="sub">{{ sub }}</div>
      </div>
      <div class="hero-aside">
        <slot name="aside">
          <div class="live"><span class="dot" />DATA FEED</div>
        </slot>
      </div>
    </div>
    <div class="hero-foot">
      <span><em>数据日期</em><b>{{ meta.latest_date || '—' }}</b><span v-if="!pending" :class="freshness.cls">{{ freshness.text }}</span></span>
      <span><em>生成</em><b>{{ gen || '—' }}</b></span>
      <span><em>观测</em><b>{{ pending ? '—' : (meta.total_obs ?? obs.length) }}</b> 条</span>
      <button class="refresh" type="button" :disabled="pending" @click="reload()">
        {{ pending ? '读取中' : '刷新数据' }}
      </button>
    </div>
  </header>
</template>
