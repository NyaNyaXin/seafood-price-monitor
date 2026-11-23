/**
 * PostgreSQL 连接池（Nitro 服务端专用）。
 *
 * 连接参数优先级：环境变量 DB_* > runtimeConfig（NUXT_DB_*）> nuxt.config.ts 默认值。
 * 用 DB_* 是为了和 Python 采集端（scripts/config.py）共用同一套变量，
 * 线上一个 EnvironmentFile 就能同时喂给 Web 与采集两个进程。
 */
import { Pool, type PoolConfig } from 'pg'

const POOL_KEY = Symbol.for('seafood.price.pgPool')

interface PoolHolder {
  [POOL_KEY]?: Pool
}

export function getPool(): Pool {
  const holder = globalThis as unknown as PoolHolder
  if (holder[POOL_KEY]) return holder[POOL_KEY] as Pool

  const rt = useRuntimeConfig()
  const config: PoolConfig = {
    host: process.env.DB_HOST ?? rt.dbHost,
    port: Number(process.env.DB_PORT ?? rt.dbPort),
    user: process.env.DB_USER ?? rt.dbUser,
    password: process.env.DB_PASSWORD ?? rt.dbPassword,
    database: process.env.DB_NAME ?? rt.dbName,
    max: Number(rt.dbPoolMax) || 5,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: Number(rt.dbConnectTimeout) || 8_000,
  }

  const pool = new Pool(config)
  pool.on('error', (err) => {
    console.error('[pg] idle client error:', err.message)
  })
  holder[POOL_KEY] = pool
  return pool
}
