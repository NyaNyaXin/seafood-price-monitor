<script setup lang="ts">
const props = withDefaults(defineProps<{ source?: string; extra?: string }>(), {
  source: 'GetPriceNow',
})
</script>

<template>
  <footer class="foot">
    数据源 全国水产技术推广总站「水产时价云」<code>{{ source }}</code> · 仅冷冻水产 · 每日 07:00 自动采集<br>
    <slot />
  </footer>
</template>
