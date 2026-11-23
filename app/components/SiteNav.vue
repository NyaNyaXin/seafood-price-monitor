<script setup lang="ts">
const links = [
  { to: '/', label: '今日概览' },
  { to: '/trend', label: '价格走势' },
  { to: '/specs', label: '全国规格' },
  { to: '/history', label: '历史明细' },
]
const route = useRoute()
</script>

<template>
  <nav class="nav">
    <NuxtLink class="nav-brand" to="/"><i>🌊</i>潮汐 <span>TIDE</span></NuxtLink>
    <div class="nav-links">
      <NuxtLink
        v-for="l in links"
        :key="l.to"
        :to="l.to"
        :class="{ active: route.path === l.to }"
      >{{ l.label }}</NuxtLink>
    </div>
  </nav>
</template>
