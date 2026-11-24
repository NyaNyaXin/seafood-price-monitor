<script setup lang="ts">
/**
 * 日期选择器：Reka DatePicker 封装（headless，样式全部自写）。
 * 对外用 `YYYY-MM-DD` 字符串（'' = 全部日期），内部转成 @internationalized/date 的 DateValue，
 * 这样历史明细页的字符串日期不需要为 UI 库改数据模型。
 */
import { parseDate, today, getLocalTimeZone, type DateValue } from '@internationalized/date'

/** 空值时给日历一个默认落点（今天），段才能渲染出占位数字而不是空白 */
const todayPlaceholder = today(getLocalTimeZone())

const props = withDefaults(defineProps<{
  modelValue: string
  /** 可选范围，限制在无数据以外的年份乱翻；空串表示不限制 */
  min?: string
  max?: string
  /** 实际有报送的日期，日历上打荧光小点，避免用户选到空日期 */
  availableDates?: string[]
}>(), {
  min: '',
  max: '',
  availableDates: () => [],
})

const emit = defineEmits<{ 'update:modelValue': [string] }>()

const selected = computed<DateValue | null>({
  get: () => (props.modelValue ? parseDate(props.modelValue) : null),
  set: (d) => emit('update:modelValue', d ? d.toString() : ''),
})

const minValue = computed(() => (props.min ? parseDate(props.min) : undefined))
const maxValue = computed(() => (props.max ? parseDate(props.max) : undefined))
const available = computed(() => new Set(props.availableDates))

/** month.value 是该网格代表的月份（跨月日期由 outsideView 过滤掉） */
function hasData(monthValue: DateValue, dayValue: string) {
  const key = `${monthValue.year}-${String(monthValue.month).padStart(2, '0')}-${String(dayValue).padStart(2, '0')}`
  return available.value.has(key)
}

function clear() { emit('update:modelValue', '') }
</script>

<template>
  <div class="dp-wrap">
    <DatePickerRoot
      v-model="selected"
      :min-value="minValue"
      :max-value="maxValue"
      locale="zh-CN"
      :week-starts-on="1"
      weekday-format="short"
      :fixed-weeks="true"
      :close-on-select="true"
      :placeholder="todayPlaceholder"
    >
      <div class="dp-field" :class="{ empty: !modelValue }">
        <DatePickerField v-slot="{ segments }" class="dp-field-inner">
          <div class="dp-segments">
            <DatePickerInput
              v-for="(s, i) in segments"
              :key="`${s.part}-${i}`"
              :part="s.part"
              class="dp-seg"
            >{{ s.value }}</DatePickerInput>
          </div>
        </DatePickerField>
        <span class="dp-icon-slot">
          <svg class="dp-icon" viewBox="0 0 24 24" aria-hidden="true">
            <rect x="3" y="5" width="18" height="16" rx="1" />
            <path d="M3 10h18M8 3v4M16 3v4" />
          </svg>
          <!-- Reka Trigger 透明覆盖图标区，只负责打开弹层；布局由外层 .dp-icon-slot 掌控 -->
          <DatePickerTrigger class="dp-trigger" aria-label="打开日期选择器" />
        </span>
        <!-- 清除融入字段内：竖线分隔、带文字，热区更大；弹层内不再重复放清除按钮 -->
        <button
          v-if="modelValue"
          type="button"
          class="dp-clear-inline"
          aria-label="清除日期筛选"
          @click="clear"
        >清除 ×</button>
      </div>

      <DatePickerContent class="dp-content" :side-offset="6" :collision-padding="8">
        <DatePickerCalendar v-slot="{ grid, weekDays }" class="dp-cal">
          <!-- 刊头取代原月份导航：min/max 已把范围锁在当月，翻月箭头是死控件，
               换成「日期 / DATE + 当月 + 有数据天数」，顺带告诉用户这个月只有几天有报送 -->
          <div class="dp-masthead">
            <span>日期 / DATE</span>
            <b v-if="grid[0]">{{ grid[0].value.year }}.{{ String(grid[0].value.month).padStart(2, '0') }}
              <i>· {{ availableDates.length }} 天</i></b>
          </div>

          <DatePickerGrid class="dp-grid">
            <DatePickerGridHead>
              <DatePickerGridRow class="dp-row">
                <DatePickerHeadCell v-for="(w, i) in weekDays" :key="i" class="dp-th">{{ w }}</DatePickerHeadCell>
              </DatePickerGridRow>
            </DatePickerGridHead>
            <DatePickerGridBody>
              <template v-for="(month, mi) in grid" :key="mi">
                <DatePickerGridRow v-for="(week, wi) in month.rows" :key="wi" class="dp-row">
                  <DatePickerCell v-for="d in week" :key="d.toString()" :date="d" class="dp-td">
                    <DatePickerCellTrigger
                      :day="d"
                      :month="month.value"
                      v-slot="{ dayValue, outsideView }"
                      class="dp-day"
                    >
                      <span :class="{ 'has-data': !outsideView && hasData(month.value, dayValue) }">{{ dayValue }}</span>
                      <i v-if="!outsideView && hasData(month.value, dayValue)" class="dp-dot" />
                    </DatePickerCellTrigger>
                  </DatePickerCell>
                </DatePickerGridRow>
              </template>
            </DatePickerGridBody>
          </DatePickerGrid>

          <div class="dp-foot">
            <span><i class="dp-dot" /> 有报送数据 · 点击日期筛选</span>
          </div>
        </DatePickerCalendar>
      </DatePickerContent>
    </DatePickerRoot>
  </div>
</template>
