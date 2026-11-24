<script setup lang="ts">
/**
 * 「立即采集」按钮：本机触发一次 scripts/fetch.py。
 *
 * 交互：点击 → 无口令则展开输入浮层 → POST /api/fetch-run（异步）→
 * 每 3 秒轮询 /api/fetch-status → 完成后 reload() 刷新看板。
 * 线上（无 scripts/ 或无 FETCH_TOKEN）接口返回 enabled=false，按钮禁用。
 */
import { usePriceData } from '~/composables/usePriceData'

interface FetchProgress {
  phase: 'idle' | 'snapshot' | 'specs' | 'retry' | 'done'
  done: number
  total: number
  percent: number
}

interface FetchStatus {
  enabled: boolean
  reason: 'ok' | 'no_script' | 'no_token'
  running: boolean
  started_at: string | null
  finished_at: string | null
  ok: boolean | null
  exit_code: number | null
  duration_s: number | null
  message: string
  /** 旧状态（HMR 前创建的单例）可能没有该字段，取值时兜底 */
  progress?: FetchProgress
  log_tail: string[]
}

const TOKEN_KEY = 'tide.fetch.token'
const { reload } = usePriceData()

const status = ref<FetchStatus | null>(null)
const phase = ref<'idle' | 'token' | 'running' | 'done' | 'error'>('idle')
const tokenInput = ref('')
const tokenEl = ref<HTMLInputElement | null>(null)
const tip = ref('')
const elapsed = ref(0)
const logVisible = ref(false)
const logEl = ref<HTMLDivElement | null>(null)
let autoOpened = false

let pollTimer: ReturnType<typeof setTimeout> | null = null
let tickTimer: ReturnType<typeof setInterval> | null = null
let resetTimer: ReturnType<typeof setTimeout> | null = null

const enabled = computed(() => status.value?.enabled ?? false)

const reasonText = computed(() => {
  if (!status.value) return '正在检查采集能力…'
  if (status.value.enabled) return ''
  return status.value.reason === 'no_script'
    ? '当前环境没有采集脚本（线上 web 容器不含 Python），无法触发采集'
    : '未配置 FETCH_TOKEN，无法触发采集'
})

const label = computed(() => {
  if (phase.value === 'running') return `采集中 ${formatElapsed(elapsed.value)}`
  if (phase.value === 'done') return '已更新'
  if (phase.value === 'error') return '重试'
  return '立即采集'
})

const title = computed(() =>
  enabled.value ? tip.value || '立即运行一次采集（约 2–3 分钟）' : reasonText.value,
)

const progress = computed<FetchProgress>(() =>
  status.value?.progress ?? { phase: 'idle', done: 0, total: 0, percent: 0 },
)
const percent = computed(() => Math.round(Math.min(100, Math.max(0, progress.value.percent))))
const logs = computed(() => status.value?.log_tail ?? [])
const canShowLog = computed(() => logs.value.length > 0 || phase.value === 'running')

const phaseText = computed(() => {
  switch (progress.value.phase) {
    case 'snapshot': return '市场快照'
    case 'specs': return '分规格 / 趋势'
    case 'retry': return '补偿轮'
    case 'done': return '已入库'
    default: return '准备中'
  }
})
const progressDetail = computed(() => {
  const p = progress.value
  if (p.phase === 'done') return '完成'
  return p.total > 0 ? `${p.done} / ${p.total}` : ''
})

// 新日志到达时保持滚动在底部（用户手动上翻时不打扰，简单起见只在抽屉打开时贴底）
watch([() => logs.value.length, logVisible], () => {
  if (!logVisible.value) return
  void nextTick(() => {
    const el = logEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
})

function formatElapsed(total: number): string {
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function startTicking() {
  stopTicking()
  tickTimer = setInterval(() => {
    const startedAt = status.value?.started_at
    elapsed.value = startedAt
      ? Math.max(0, Math.round((Date.now() - new Date(startedAt).getTime()) / 1000))
      : elapsed.value + 1
  }, 1000)
}

function stopTicking() {
  if (tickTimer) {
    clearInterval(tickTimer)
    tickTimer = null
  }
}

function schedulePoll(delay = 3000) {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = setTimeout(() => { void refreshStatus() }, delay)
}

function scheduleReset() {
  if (resetTimer) clearTimeout(resetTimer)
  resetTimer = setTimeout(() => {
    if (phase.value === 'done') phase.value = 'idle'
  }, 2500)
}

async function finish(s: FetchStatus) {
  stopTicking()
  if (s.ok) {
    phase.value = 'done'
    tip.value = s.message
    await reload()
    scheduleReset()
  } else {
    phase.value = 'error'
    tip.value = s.message || '采集失败'
  }
}

async function refreshStatus() {
  try {
    const s = await $fetch<FetchStatus>('/api/fetch-status')
    status.value = s
    if (s.running) {
      if (phase.value !== 'running') {
        phase.value = 'running'
        startTicking()
      }
      // 页面首次加载就发现任务在跑时，自动把日志抽屉打开一次
      if (!autoOpened) {
        autoOpened = true
        logVisible.value = true
      }
      schedulePoll()
      return
    }
    if (phase.value === 'running') await finish(s)
  } catch (err) {
    status.value = null
    tip.value = (err as Error).message
  }
}

async function run(token: string) {
  tip.value = ''
  try {
    await $fetch('/api/fetch-run', {
      method: 'POST',
      headers: { 'x-fetch-token': token },
    })
    sessionStorage.setItem(TOKEN_KEY, token)
    phase.value = 'running'
    elapsed.value = 0
    autoOpened = true
    logVisible.value = true
    startTicking()
    schedulePoll(1000)
  } catch (err) {
    const e = err as { statusCode?: number; data?: { error?: string } }
    if (e.statusCode === 401) {
      sessionStorage.removeItem(TOKEN_KEY)
      phase.value = 'token'
      tip.value = '口令错误'
      return
    }
    // 409：另一个入口已经启动了采集，直接进入轮询观察它
    if (e.statusCode === 409) {
      phase.value = 'running'
      startTicking()
      schedulePoll(1000)
      return
    }
    phase.value = 'error'
    tip.value = e.data?.error === 'disabled' ? reasonText.value : '启动采集失败'
  }
}

function openToken() {
  phase.value = 'token'
  tokenInput.value = ''
  tip.value = ''
  void nextTick(() => tokenEl.value?.focus())
}

function closeToken() {
  phase.value = 'idle'
  tip.value = ''
  tokenInput.value = ''
}

function submitToken() {
  const token = tokenInput.value.trim()
  if (!token) {
    tip.value = '请输入口令'
    return
  }
  void run(token)
}

function onClick() {
  if (!enabled.value || phase.value === 'running') return
  if (phase.value === 'token') {
    closeToken()
    return
  }
  const saved = sessionStorage.getItem(TOKEN_KEY)
  if (!saved) {
    openToken()
    return
  }
  void run(saved)
}

onMounted(() => { void refreshStatus() })

onBeforeUnmount(() => {
  if (pollTimer) clearTimeout(pollTimer)
  if (resetTimer) clearTimeout(resetTimer)
  stopTicking()
})
</script>

<template>
  <div class="fetch-wrap">
    <button
      class="refresh fetch-btn"
      :class="phase"
      type="button"
      :disabled="!enabled || phase === 'running'"
      :title="title"
      @click="onClick"
    >{{ label }}</button>

    <button
      v-if="canShowLog"
      class="refresh fetch-log-toggle"
      :class="{ active: logVisible }"
      type="button"
      title="查看采集日志与进度"
      @click="logVisible = !logVisible"
    >日志</button>

    <div v-if="phase === 'token'" class="fetch-token-pop">
      <div class="fetch-token-row">
        <input
          ref="tokenEl"
          v-model="tokenInput"
          class="fetch-token-input"
          :class="{ invalid: !!tip }"
          type="password"
          placeholder="采集口令"
          aria-label="采集口令"
          @keydown.enter.prevent="submitToken"
          @keydown.esc="closeToken"
        >
        <button class="refresh fetch-token-ok" type="button" @click="submitToken">确认</button>
      </div>
      <span v-if="tip" class="fetch-tip">{{ tip }}</span>
    </div>
  </div>

  <Teleport to="body">
    <Transition name="fetch-log">
      <section v-if="logVisible" class="fetch-log" aria-label="采集日志">
        <header class="fetch-log-head">
          <span class="fetch-log-title">FETCH LOG</span>
          <span class="fetch-log-phase" :class="phase">{{ phaseText }}</span>
          <span class="fetch-log-count">{{ progressDetail }}</span>
          <span class="fetch-log-pct">{{ percent }}%</span>
          <button class="fetch-log-close" type="button" aria-label="关闭日志" @click="logVisible = false">×</button>
        </header>

        <div class="fetch-log-bar"><i :style="{ width: percent + '%' }" /></div>

        <div ref="logEl" class="fetch-log-body">
          <div v-if="!logs.length" class="fetch-log-empty">等待输出…</div>
          <div v-for="(line, i) in logs" :key="i" class="ln">{{ line }}</div>
        </div>

        <footer class="fetch-log-foot">
          <span>{{ phase === 'running' ? `已用时 ${formatElapsed(elapsed)}` : (status?.duration_s ? `耗时 ${status.duration_s}s` : '') }}</span>
          <span class="fetch-log-msg">{{ status?.message || '' }}</span>
        </footer>
      </section>
    </Transition>
  </Teleport>
</template>
