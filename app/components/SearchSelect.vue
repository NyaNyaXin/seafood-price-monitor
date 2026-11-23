<script setup lang="ts">
/**
 * 可搜索下拉：Reka Combobox 封装，输入即过滤，选中后input回填label。
 * 替代原生 Select —— Select 不支持搜索，且长列表在 content 里滚动更可靠。
 *
 * 用法：
 *   <SearchSelect v-model="marketId" :options="marketOptions" placeholder="搜索市场" />
 */
interface Option {
  value: string
  label: string
  /** 悬停提示，通常是未截断的全名 */
  hint?: string
}

const props = withDefaults(defineProps<{
  modelValue: string
  options: Option[]
  placeholder?: string
  ariaLabel?: string
  /** 传入时在列表首项插入「全部」，值为 __all__ */
  allLabel?: string
}>(), {
  placeholder: '搜索…',
  ariaLabel: '搜索并选择',
  allLabel: '',
})

const emit = defineEmits<{ 'update:modelValue': [string] }>()

/** 「全部」项与调用方的哨兵值保持一致（项目统一用 __all__） */
const ALL = '__all__'
const allOptions = computed<Option[]>(() =>
  props.allLabel ? [{ value: ALL, label: props.allLabel }, ...props.options] : props.options,
)

// Combobox 用 displayValue 决定输入框在「非搜索态」显示什么
const labelOf = (v: unknown): string =>
  allOptions.value.find((o) => o.value === String(v))?.label ?? ''

const isOpen = ref(false)
const isEmpty = computed(() => props.options.length === 0)

function onSelect(v: unknown) {
  emit('update:modelValue', v == null ? '' : String(v))
}
</script>

<template>
  <ComboboxRoot
    :model-value="modelValue"
    :open-on-click="true"
    :reset-search-term-on-blur="true"
    @update:model-value="onSelect"
    @update:open="(v: boolean) => (isOpen = v)"
  >
    <ComboboxAnchor class="ui-combo" :class="{ open: isOpen, empty: isEmpty }">
      <ComboboxInput
        class="ui-combo-input"
        :display-value="labelOf"
        :placeholder="isEmpty ? '无可选项' : placeholder"
        :aria-label="ariaLabel"
        :disabled="isEmpty"
        @focus="(e: FocusEvent) => (e.target as HTMLInputElement).select()"
      />
      <ComboboxTrigger class="ui-combo-trigger" :aria-label="ariaLabel">
        <span class="ui-combo-caret">▾</span>
      </ComboboxTrigger>
    </ComboboxAnchor>

    <ComboboxPortal>
      <ComboboxContent class="ui-select-content ui-combo-content" position="popper" :side-offset="6" :collision-padding="8">
        <ComboboxItem
          v-for="o in allOptions"
          :key="o.value"
          :value="o.value"
          class="ui-select-item"
          :title="o.hint || o.label"
        >
          <ComboboxItemText>{{ o.label }}</ComboboxItemText>
          <ComboboxItemIndicator class="ui-select-indicator">✓</ComboboxItemIndicator>
        </ComboboxItem>
        <ComboboxEmpty class="ui-combo-empty">没有匹配项</ComboboxEmpty>
      </ComboboxContent>
    </ComboboxPortal>
  </ComboboxRoot>
</template>
