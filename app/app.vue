<script setup lang="ts">
// 数据来自 /api/price-data（服务端直连 PostgreSQL）。
// 这里只取 error 做全局提示，避免库连不上时页面只剩空表。
const { error } = usePriceData()
</script>

<template>
  <div class="wrap">
    <SiteNav />
    <div v-if="error" class="db-error">
      数据加载失败：{{ (error as any)?.message || error }}
    </div>
    <NuxtPage />
  </div>
</template>
