<script setup lang="ts">
/** 表格骨架：与真实表格共用 th 宽度，行数固定，不做逐行动画（会抖）。 */
withDefaults(defineProps<{ rows?: number; cols?: number }>(), {
  rows: 8,
  cols: 7,
})

const widths = ['68%', '52%', '60%', '44%', '38%', '34%', '34%']
const widthAt = (i: number) => widths[i % widths.length] ?? '50%'
</script>

<template>
  <tbody>
    <tr v-for="r in rows" :key="r" class="sk-row">
      <td v-for="c in cols" :key="c">
        <span class="sk" :style="{ width: widthAt(r + c), opacity: 1 - r * 0.045 }" />
      </td>
    </tr>
  </tbody>
</template>
