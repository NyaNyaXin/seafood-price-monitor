/**
 * 本机「立即采集」任务执行器。
 *
 * 只支持本机（pnpm dev / 从项目根 `node .output/server/index.mjs`）：
 * 线上 web 镜像只有 .output，没有 Python 与 scripts/，此时 enabled=false，按钮禁用。
 *
 * 状态挂在 globalThis 上，抵抗 Nitro HMR 重载（与 server/utils/pg.ts 的单例思路一致）。
 * 不修改 scripts/fetch.py，只负责起进程、收集尾部日志、给出退出结果。
 */
import { createHash, timingSafeEqual } from 'node:crypto'
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'

type DisabledReason = 'ok' | 'no_script' | 'no_token'

interface FetchRunState {
  running: boolean
  startedAt: string | null
  finishedAt: string | null
  ok: boolean | null
  exitCode: number | null
  message: string
  logLines: string[]
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
  log_tail: string[]
}

interface RunnerHolder {
  __seafoodFetchRun?: FetchRunState
}

const MAX_LOG_LINES = 200
const MAX_LINE_CHARS = 300
const TIMEOUT_MS = 10 * 60 * 1000

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

function pushLines(state: FetchRunState, chunk: Buffer) {
  for (const raw of chunk.toString('utf-8').split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    state.logLines.push(line.slice(0, MAX_LINE_CHARS))
    if (state.logLines.length > MAX_LOG_LINES) state.logLines.shift()
  }
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

  child.stdout?.on('data', (chunk: Buffer) => pushLines(state, chunk))
  child.stderr?.on('data', (chunk: Buffer) => pushLines(state, chunk))

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
    state.running = false
    state.finishedAt = new Date().toISOString()
    state.exitCode = code
    if (timedOut) {
      state.ok = false
      state.message = '采集超时（10 分钟），已终止'
    } else if (code === 0) {
      state.ok = true
      state.message = summarize(state.logLines) || '采集完成'
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
    log_tail: state.logLines.slice(-20),
  }
}
