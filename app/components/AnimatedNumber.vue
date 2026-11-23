<script setup lang="ts">
/**
 * 数字滚动：行情板的核心微交互。
 * 尊重 prefers-reduced-motion，直接给终值。
 */
const props = withDefaults(defineProps<{ value: number; duration?: number }>(), {
  duration: 650,
})

const display = ref(0)
let raf = 0

function animate(to: number) {
  if (typeof window === 'undefined') {
    display.value = to
    return
  }
  cancelAnimationFrame(raf)
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    display.value = to
    return
  }
  const from = display.value
  const t0 = performance.now()
  const tick = (t: number) => {
    const p = Math.min(1, (t - t0) / props.duration)
    const eased = 1 - (1 - p) ** 3
    display.value = Math.round(from + (to - from) * eased)
    if (p < 1) raf = requestAnimationFrame(tick)
  }
  raf = requestAnimationFrame(tick)
}

watch(() => props.value, (v) => animate(Number.isFinite(v) ? v : 0), { immediate: true })
onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<template>
  <span>{{ display }}</span>
</template>
