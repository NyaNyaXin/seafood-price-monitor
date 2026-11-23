# -*- coding: utf-8 -*-
"""数据层封装：建表、幂等写入、查询、CSV 导出。

**唯一后端是 PostgreSQL**（psycopg2 + RealDictCursor）。SQLite 后端已于 2026-11-24 移除，
本地库文件归档在 `data/archive/`，因此这里不再有 `?` / `:name` 的占位符兼容层：
SQL 统一写 psycopg2 原生占位符 —— 位置参数用 `%s`，命名参数用 `%(name)s`。

查询返回的行是 dict 风格（`r["col"]` / `dict(r)`），可直接 `json.dumps`。
"""
import csv
from datetime import datetime

import config


# ============================================================
# 表结构
# ============================================================
# 注意：价格列在 PG 里必须用 DOUBLE PRECISION（8 字节）。
#   - PG 的 REAL 是 float4（约 6 位有效数字），40.67 会变成 40.669998…，
#     污染涨跌计算与前端展示。
#   - 不能用 NUMERIC：psycopg2 读回 decimal.Decimal，json.dumps 会直接报错。
# psycopg2 不支持一次 execute 多条语句，因此建表语句逐条列出。
_PG_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS price_obs (
           id           SERIAL PRIMARY KEY,
           obs_date     TEXT NOT NULL,
           fetch_time   TEXT NOT NULL,
           market_id    INTEGER NOT NULL,
           market_name  TEXT NOT NULL,
           product_id   INTEGER NOT NULL,
           product_name TEXT NOT NULL,
           spec_id      INTEGER NOT NULL,
           spec_name    TEXT,
           price        DOUBLE PRECISION NOT NULL,
           UNIQUE(obs_date, market_id, product_id, spec_id)
       )""",
    "CREATE INDEX IF NOT EXISTS idx_obs_date ON price_obs(obs_date)",
    "CREATE INDEX IF NOT EXISTS idx_obs_series ON price_obs(market_id, product_id, spec_id, obs_date)",
    """CREATE TABLE IF NOT EXISTS spec_snapshot (
           id           SERIAL PRIMARY KEY,
           snap_date    TEXT NOT NULL,
           region       TEXT NOT NULL,
           product_id   INTEGER NOT NULL,
           product_name TEXT NOT NULL,
           category     TEXT,
           spec_name    TEXT NOT NULL,
           price        DOUBLE PRECISION NOT NULL,
           fetch_time   TEXT NOT NULL,
           UNIQUE(snap_date, region, product_id, spec_name)
       )""",
    "CREATE INDEX IF NOT EXISTS idx_spec_date ON spec_snapshot(snap_date, region)",
    """CREATE TABLE IF NOT EXISTS product_trend (
           id           SERIAL PRIMARY KEY,
           trend_date   TEXT NOT NULL,
           region       TEXT NOT NULL,
           product_id   INTEGER NOT NULL,
           product_name TEXT NOT NULL,
           price        DOUBLE PRECISION NOT NULL,
           fetch_time   TEXT NOT NULL,
           UNIQUE(trend_date, region, product_id)
       )""",
    "CREATE INDEX IF NOT EXISTS idx_trend ON product_trend(product_id, region, trend_date)",
    """CREATE TABLE IF NOT EXISTS fetch_log (
           id          SERIAL PRIMARY KEY,
           fetch_time  TEXT NOT NULL,
           status      TEXT NOT NULL,
           raw_count   INTEGER DEFAULT 0,
           kept_count  INTEGER DEFAULT 0,
           error_msg   TEXT
       )""",
]


# ============================================================
# 连接
# ============================================================
class Conn:
    """psycopg2 连接的薄封装：execute / executemany 复用同一游标并直接返回它。

    行的形状由 RealDictCursor 决定（dict 风格），上层不需要再适配 sqlite3.Row。
    """

    def __init__(self, raw):
        self._raw = raw
        self._cur = raw.cursor()

    def execute(self, sql, params=None):
        self._cur.execute(sql, params)
        return self._cur

    def executemany(self, sql, seq_of_params):
        self._cur.executemany(sql, seq_of_params)
        return self._cur

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        try:
            self._cur.close()
        finally:
            self._raw.close()


def ensure_dirs():
    for d in (config.DATA_DIR, config.EXPORT_DIR, config.LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def connect(database=None):
    """连 PostgreSQL。

    database=None 时用 `config.DB_NAME`；建库/维护场景传 `"postgres"`。
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor

    ensure_dirs()
    raw = psycopg2.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        dbname=database or config.DB_NAME,
        connect_timeout=config.DB_CONNECT_TIMEOUT,
        cursor_factory=RealDictCursor,
    )
    return Conn(raw)


def init_schema(conn):
    """建表 + 建索引（IF NOT EXISTS，幂等）。"""
    for stmt in _PG_STATEMENTS:
        conn.execute(stmt)
    conn.commit()


# ============================================================
# 写入（幂等）
# ============================================================
def upsert_observations(conn, rows):
    """幂等写入市场快照。rows: list of dict。返回 (新增数, 更新数)。"""
    before = conn.execute("SELECT COUNT(*) AS n FROM price_obs").fetchone()["n"]
    conn.executemany(
        """
        INSERT INTO price_obs
            (obs_date, fetch_time, market_id, market_name,
             product_id, product_name, spec_id, spec_name, price)
        VALUES
            (%(obs_date)s, %(fetch_time)s, %(market_id)s, %(market_name)s,
             %(product_id)s, %(product_name)s, %(spec_id)s, %(spec_name)s, %(price)s)
        ON CONFLICT (obs_date, market_id, product_id, spec_id)
        DO UPDATE SET
            fetch_time = excluded.fetch_time,
            market_name = excluded.market_name,
            product_name = excluded.product_name,
            spec_name = excluded.spec_name,
            price = excluded.price
        """,
        rows,
    )
    conn.commit()
    after = conn.execute("SELECT COUNT(*) AS n FROM price_obs").fetchone()["n"]
    return after - before, len(rows) - (after - before)


def upsert_spec_snapshot(conn, rows):
    """幂等写入分规格快照。rows 需含 snap_date/region/product_id/spec_name。"""
    conn.executemany(
        """INSERT INTO spec_snapshot
             (snap_date, region, product_id, product_name, category,
              spec_name, price, fetch_time)
           VALUES (%(snap_date)s, %(region)s, %(product_id)s, %(product_name)s,
                   %(category)s, %(spec_name)s, %(price)s, %(fetch_time)s)
           ON CONFLICT (snap_date, region, product_id, spec_name)
           DO UPDATE SET
             product_name = excluded.product_name,
             category = excluded.category,
             price = excluded.price,
             fetch_time = excluded.fetch_time""",
        rows,
    )
    conn.commit()
    return len(rows)


def upsert_trend(conn, rows):
    """幂等写入 30 天趋势。rows 需含 trend_date/region/product_id。"""
    conn.executemany(
        """INSERT INTO product_trend
             (trend_date, region, product_id, product_name, price, fetch_time)
           VALUES (%(trend_date)s, %(region)s, %(product_id)s, %(product_name)s,
                   %(price)s, %(fetch_time)s)
           ON CONFLICT (trend_date, region, product_id)
           DO UPDATE SET
             product_name = excluded.product_name,
             price = excluded.price,
             fetch_time = excluded.fetch_time""",
        rows,
    )
    conn.commit()
    return len(rows)


# ============================================================
# 查询
# ============================================================
def all_spec_snapshot(conn):
    cur = conn.execute(
        """SELECT snap_date, region, product_id, product_name, category,
                  spec_name, price, fetch_time
           FROM spec_snapshot ORDER BY region, product_id, spec_name"""
    )
    return [dict(r) for r in cur.fetchall()]


def all_trends(conn):
    """返回 {pid: {name, x:[日期], ln:[价], cn:[价]}}。"""
    cur = conn.execute(
        """SELECT trend_date, region, product_id, product_name, price
           FROM product_trend ORDER BY product_id, region, trend_date"""
    )
    out = {}
    for r in cur.fetchall():
        pid = r["product_id"]
        if pid not in out:
            out[pid] = {"name": r["product_name"], "x": [], "ln": [], "cn": {}}
        # cn 用 dict 暂存以便按日期对齐
        bucket = "ln" if r["region"] == "ln" else "cn"
        if bucket == "cn":
            out[pid]["cn"][r["trend_date"]] = r["price"]
        else:
            out[pid]["ln"].append((r["trend_date"], r["price"]))
    # 以辽宁日期为基准对齐；辽宁无价时用全国日期兜底（两者日期序列同源）
    for pid, t in out.items():
        cn_map = t.pop("cn")
        if t["ln"]:
            dates = [d for d, _ in t["ln"]]
            t["ln"] = [v for _, v in t["ln"]]
        else:
            dates = sorted(cn_map.keys())
            t["ln"] = [None] * len(dates)
        t["x"] = dates
        t["cn"] = [cn_map.get(d) for d in dates]
    return out


def log_fetch(conn, status, raw_count, kept_count, error_msg=""):
    conn.execute(
        """INSERT INTO fetch_log
           (fetch_time, status, raw_count, kept_count, error_msg)
           VALUES (%s, %s, %s, %s, %s)""",
        (datetime.now().isoformat(timespec="seconds"),
         status, raw_count, kept_count, error_msg),
    )
    conn.commit()


def all_observations(conn, frozen_only=True):
    cur = conn.execute(
        """SELECT obs_date, market_id, market_name, product_id, product_name,
                  spec_id, spec_name, price, fetch_time
           FROM price_obs ORDER BY obs_date, market_id, product_id, spec_id"""
    )
    rows = [dict(r) for r in cur.fetchall()]
    if frozen_only:
        rows = [r for r in rows
                if config.is_frozen(r["product_name"], r["spec_name"])]
    return rows


def latest_date(conn):
    row = conn.execute("SELECT MAX(obs_date) AS d FROM price_obs").fetchone()
    return row["d"] if row else None


def table_counts(conn):
    """各表条数，便于初始化和自检时一眼看全。"""
    out = {}
    for t in ("price_obs", "spec_snapshot", "product_trend", "fetch_log"):
        out[t] = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
    return out


def export_csv(conn, path=None):
    """导出全部观测为 CSV。"""
    path = path or (config.EXPORT_DIR / "prices.csv")
    rows = all_observations(conn)
    if not rows:
        return path, 0
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path, len(rows)


def fetch_logs(conn, limit=20):
    cur = conn.execute(
        "SELECT * FROM fetch_log ORDER BY id DESC LIMIT %s", (limit,)
    )
    return [dict(r) for r in cur.fetchall()]
