/**
 * 本机「立即采集」任务执行器。
 *
 * 只支持本机（pnpm dev / 从项目根 `node .output/server/index.mjs`）：
 * 线上 web 镜像只有 .output，没有 Python 与 scripts/，此时 enabled=false，按钮禁用。
 *
 * 状态挂在 globalThis 上，抵抗 Nitro HMR 重载（与 server/utils/pg.ts 的单例思路一致）。
 * 不修改 scripts/fetch.py，只负责起进程、收集日志、从日志行推导阶段进度。
 */
import { createHash, timingSafeEqual } from 'node:crypto'
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import reference from '../../shared/reference.json'

type DisabledReason = 'ok' | 'no_script' | 'no_token'
type FetchPhase = 'idle' | 'snapshot' | 'specs' | 'retry' | 'done'

export interface FetchProgress {
  phase: FetchPhase
  done: number
  total: number
  percent: number
}

interface FetchRunState {
  running: boolean
  startedAt: string | null
  finishedAt: string | null
  ok: boolean | null
  exitCode: number | null
  message: string
  logLines: string[]
  /** stdout/stderr 可能把一行拆到两个 chunk，这里暂存未闭合的半行 */
  partial: string
  progress: FetchProgress
  seenSpecs: Set<number>
  retryTotal: number
  retryDone: number
  timer: ReturnType<typeof setTimeout> | null
  kill: (() => void) | null
}

export interface FetchStatusPayload {
  enabled: boolean
  reason: DisabledReason
  running: boolean
  started_at: string | null
  finished_at: string | null
  ok: boolean | null
  exit_code: number | null
  duration_s: number | null
  message: string
  progress: FetchProgress
  log_tail: string[]
}

interface RunnerHolder {
  __seafoodFetchRun?: FetchRunState
}

const MAX_LOG_LINES = 500
const LOG_TAIL_LINES = 120
const MAX_LINE_CHARS = 300
const TIMEOUT_MS = 10 * 60 * 1000
const SPEC_TOTAL = reference.frozen_products.length || 29

function idleProgress(): FetchProgress {
  return { phase: 'idle', done: 0, total: 0, percent: 0 }
}

function getState(): FetchRunState {
  const holder = globalThis as unknown as RunnerHolder
  if (!holder.__seafoodFetchRun) {
    holder.__seafoodFetchRun = {
      running: false,
      startedAt: null,
      finishedAt: null,
      ok: null,
      exitCode: null,
      message: '',
      logLines: [],
      partial: '',
      progress: idleProgress(),
      seenSpecs: new Set<number>(),
      retryTotal: 0,
      retryDone: 0,
      timer: null,
      kill: null,
    }
  }
  return holder.__seafoodFetchRun
}

export function getFetchConfig() {
  const scriptPath = path.resolve(process.cwd(), 'scripts', 'fetch.py')
  return {
    scriptPath,
    hasScript: existsSync(scriptPath),
    token: process.env.FETCH_TOKEN ?? '',
    pythonBin: process.env.FETCH_PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  }
}

export function fetchAvailability(): { enabled: boolean; reason: DisabledReason } {
  const cfg = getFetchConfig()
  if (!cfg.hasScript) return { enabled: false, reason: 'no_script' }
  if (!cfg.token) return { enabled: false, reason: 'no_token' }
  return { enabled: true, reason: 'ok' }
}

/** 定长摘要后再比较，避免口令长度与时序泄漏 */
export function verifyToken(input: string | undefined): boolean {
  const expected = getFetchConfig().token
  if (!expected || !input) return false
  const a = createHash('sha256').update(input).digest()
  const b = createHash('sha256').update(expected).digest()
  return timingSafeEqual(a, b)
}

/**
 * 从 fetch.py 的日志行推导进度。阶段顺序：
 *   快照分页 → 29 个品种分规格 → 补偿轮 → 入库完成
 * 只做区间估算，不追求精确到秒；日志格式见 scripts/fetch.py。
 */
function trackProgress(state: FetchRunState, line: string) {
  const page = /第 (\d+)\/(\d+) 页/.exec(line)
  if (page) {
    const done = Number(page[1])
    const total = Number(page[2]) || 3
    state.progress = {
      phase: 'snapshot',
      done,
      total,
      percent: Math.min(10, 2 + (8 * done) / total),
    }
    return
  }

  const retry = /补偿轮: 重试 (\d+) 个/.exec(line)
  if (retry) {
    state.retryTotal = Number(retry[1])
    state.retryDone = 0
    state.progress = {
      phase: 'retry',
      done: 0,
      total: state.retryTotal,
      percent: 96,
    }
    return
  }

  const spec = /\[规格\] pid=(\d+)/.exec(line)
  if (spec) {
    const pid = Number(spec[1])
    if (state.progress.phase === 'retry') {
      state.retryDone += 1
      const total = Math.max(1, state.retryTotal)
      state.progress = {
        phase: 'retry',
        done: state.retryDone,
        total,
        percent: Math.min(99, 95 + (4 * state.retryDone) / total),
      }
    } else if (!state.seenSpecs.has(pid)) {
      state.seenSpecs.add(pid)
      const done = state.seenSpecs.size
      state.progress = {
        phase: 'specs',
        done,
        total: SPEC_TOTAL,
        percent: Math.min(95, 10 + (85 * done) / SPEC_TOTAL),
      }
    }
    return
  }

  const specDone = /\[规格\] 完成: (\d+)\/(\d+)/.exec(line)
  if (specDone) {
    state.progress = {
      phase: 'specs',
      done: Number(specDone[1]),
      total: Number(specDone[2]) || SPEC_TOTAL,
      percent: 95,
    }
    return
  }

  if (/入库:/.test(line)) {
    state.progress = { phase: 'done', done: 1, total: 1, percent: 100 }
  }
}

function ingest(state: FetchRunState, chunk: Buffer) {
  const parts = (state.partial + chunk.toString('utf-8')).split(/\r?\n/)
  state.partial = parts.pop() ?? ''
  for (const raw of parts) {
    const line = raw.trim()
    if (!line) continue
    const clipped = line.slice(0, MAX_LINE_CHARS)
    state.logLines.push(clipped)
    if (state.logLines.length > MAX_LOG_LINES) state.logLines.shift()
    trackProgress(state, clipped)
  }
}

function flushPartial(state: FetchRunState) {
  const line = state.partial.trim()
  state.partial = ''
  if (!line) return
  const clipped = line.slice(0, MAX_LINE_CHARS)
  state.logLines.push(clipped)
  if (state.logLines.length > MAX_LOG_LINES) state.logLines.shift()
  trackProgress(state, clipped)
}

/** fetch.py 成功时最后一行是 JSON：{"status":"OK","snapshot":..,"specs":..,"trends":..} */
function summarize(lines: string[]): string {
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i]
    if (!line || !line.startsWith('{')) continue
    try {
      const obj = JSON.parse(line) as {
        status?: string
        snapshot?: number
        specs?: number
        trends?: number
      }
      if (obj.status === 'OK') {
        return `快照 ${obj.snapshot ?? 0} 条 / 规格 ${obj.specs ?? 0} 条 / 趋势 ${obj.trends ?? 0} 条`
      }
    } catch {
      // 非 JSON 行（脚本的普通日志）直接跳过
    }
  }
  return ''
}

function lastLine(lines: string[]): string {
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i]
    if (line) return line
  }
  return ''
}

function clearTimer(state: FetchRunState) {
  if (state.timer) {
    clearTimeout(state.timer)
    state.timer = null
  }
  state.kill = null
}

export interface StartResult {
  conflict: boolean
  startedAt?: string
}

export function startFetch(): StartResult {
  const state = getState()
  if (state.running) return { conflict: true }

  const cfg = getFetchConfig()
  const startedAt = new Date().toISOString()

  state.running = true
  state.startedAt = startedAt
  state.finishedAt = null
  state.ok = null
  state.exitCode = null
  state.message = ''
  state.logLines = []
  state.partial = ''
  state.progress = { phase: 'snapshot', done: 0, total: 3, percent: 2 }
  state.seenSpecs = new Set<number>()
  state.retryTotal = 0
  state.retryDone = 0

  const child = spawn(cfg.pythonBin, ['-u', cfg.scriptPath], {
    cwd: process.cwd(),
    shell: false,
    windowsHide: true,
    env: {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
      PYTHONUNBUFFERED: '1',
      TZ: process.env.TZ || 'Asia/Shanghai',
    },
  })

  state.kill = () => child.kill()

  child.stdout?.on('data', (chunk: Buffer) => ingest(state, chunk))
  child.stderr?.on('data', (chunk: Buffer) => ingest(state, chunk))

  let timedOut = false

  child.on('error', (err: Error) => {
    state.running = false
    state.ok = false
    state.finishedAt = new Date().toISOString()
    state.exitCode = null
    state.message = err.message.includes('ENOENT')
      ? '未找到 Python 解释器，可用 FETCH_PYTHON 指定'
      : `启动采集失败：${err.message}`
    clearTimer(state)
  })

  child.on('close', (code: number | null) => {
    flushPartial(state)
    state.running = false
    state.finishedAt = new Date().toISOString()
    state.exitCode = code
    if (timedOut) {
      state.ok = false
      state.message = '采集超时（10 分钟），已终止'
      state.progress = { ...state.progress, percent: 100 }
    } else if (code === 0) {
      state.ok = true
      state.message = summarize(state.logLines) || '采集完成'
      state.progress = { phase: 'done', done: 1, total: 1, percent: 100 }
    } else {
      state.ok = false
      state.message = lastLine(state.logLines) || `采集失败（退出码 ${code ?? '未知'}）`
    }
    clearTimer(state)
  })

  state.timer = setTimeout(() => {
    timedOut = true
    state.message = '采集超时（10 分钟），正在终止'
    state.kill?.()
    setTimeout(() => {
      if (state.running && !child.killed) child.kill('SIGKILL')
    }, 5_000)
  }, TIMEOUT_MS)
  state.timer.unref?.()

  return { conflict: false, startedAt }
}

export function getFetchStatus(): FetchStatusPayload {
  const state = getState()
  const { enabled, reason } = fetchAvailability()

  let duration: number | null = null
  if (state.startedAt) {
    const start = new Date(state.startedAt).getTime()
    const end = state.finishedAt ? new Date(state.finishedAt).getTime() : Date.now()
    duration = Math.max(0, Math.round((end - start) / 1000))
  }

  return {
    enabled,
    reason,
    running: state.running,
    started_at: state.startedAt,
    finished_at: state.finishedAt,
    ok: state.ok,
    exit_code: state.exitCode,
    duration_s: duration,
    message: state.message,
    progress: state.progress,
    log_tail: state.logLines.slice(-LOG_TAIL_LINES),
  }
}
