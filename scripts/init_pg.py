# -*- coding: utf-8 -*-
"""PostgreSQL 初始化：建库 → 建表建索引 →（可选）注入种子数据。

替代已删除的 `migrate_to_pg.py`（那个脚本的唯一职责是把 SQLite 搬进 PG，
已于 2026-11-23 完成使命；SQLite 后端在 2026-11-24 彻底移除）。

用法（在项目根目录执行，任意 cwd 亦可，脚本内部会定位项目根）：
    python scripts/init_pg.py                   # 建库 + 建表建索引（幂等，已存在则跳过）
    python scripts/init_pg.py --seed            # 建库建表，并导入 scripts/seed/*.json
    python scripts/init_pg.py --seed-only       # 只导种子数据（表必须已存在）
    python scripts/init_pg.py --dry-run         # 只打印将做什么：不连库、不建库、不写任何东西
    python scripts/init_pg.py --recreate --yes  # 危险：DROP 四张表后重建（数据全丢）

种子数据是 `scripts/seed/{price_obs,spec_snapshot,product_trend}.json`，
由 `--dump-seed` 从当前库导出，用途是「空库重建后页面立刻有内容 / 离线演示」，
不是业务必需（趋势是平台现成的 30 天窗口，重抓即可得）。

退出码：0 成功 / 1 参数或环境错误 / 2 执行失败。
"""
import argparse
import json
import sys
from pathlib import Path

# 让同目录的 config / db 可被导入，从而支持从任意目录运行本脚本
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import db


# 种子表 + 对应的幂等写入函数（顺序无依赖，四表互不引用）
SEED_TABLES = [
    ("price_obs", db.upsert_observations),
    ("spec_snapshot", db.upsert_spec_snapshot),
    ("product_trend", db.upsert_trend),
]

# 各表除 id 外的列，导出种子时按此顺序取（id 由 SERIAL 重新分配）
EXPORT_COLS = {
    "price_obs": ["obs_date", "fetch_time", "market_id", "market_name",
                  "product_id", "product_name", "spec_id", "spec_name", "price"],
    "spec_snapshot": ["snap_date", "region", "product_id", "product_name",
                      "category", "spec_name", "price", "fetch_time"],
    "product_trend": ["trend_date", "region", "product_id", "product_name",
                      "price", "fetch_time"],
}


def log(msg):
    print(msg, flush=True)


def target_desc():
    return f"{config.DB_USER}@{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}"


# ============================================================
# 建库
# ============================================================
def ensure_database(dry=False):
    """确保目标库存在。返回 True=新建，False=已存在。

    注意：CREATE DATABASE 不能在事务里跑，必须用 autocommit 的独立连接。
    """
    if dry:
        log(f"[dry-run] 将检查/创建数据库 {config.DB_NAME}（{target_desc()}）")
        return False

    import psycopg2
    from psycopg2 import sql

    raw = psycopg2.connect(
        host=config.DB_HOST, port=config.DB_PORT, user=config.DB_USER,
        password=config.DB_PASSWORD, dbname="postgres",
        connect_timeout=config.DB_CONNECT_TIMEOUT,
    )
    try:
        raw.autocommit = True
        with raw.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s",
                        (config.DB_NAME,))
            if cur.fetchone():
                log(f"数据库已存在：{config.DB_NAME}")
                return False
            cur.execute(
                sql.SQL("CREATE DATABASE {} ENCODING 'UTF8'").format(
                    sql.Identifier(config.DB_NAME))
            )
            log(f"已创建数据库：{config.DB_NAME}")
            return True
    finally:
        raw.close()


# ============================================================
# 建表 / 重建
# ============================================================
def drop_tables(conn):
    """DROP 四张表（--recreate 用）。CASCADE 兜住任何残留外键。"""
    for name in ("price_obs", "spec_snapshot", "product_trend", "fetch_log"):
        conn.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
    conn.commit()
    log("已删除四张表（price_obs / spec_snapshot / product_trend / fetch_log）")


# ============================================================
# 种子数据
# ============================================================
def seed_files():
    """返回 [(表名, 路径)]，只列存在的文件。"""
    return [(name, config.SEED_DIR / f"{name}.json")
            for name, _ in SEED_TABLES
            if (config.SEED_DIR / f"{name}.json").exists()]


def import_seed(conn):
    """把 scripts/seed/*.json 幂等导入。返回总行数。"""
    files = seed_files()
    if not files:
        log(f"[跳过] 没有种子文件：{config.SEED_DIR}/*.json"
            f"（可先用 --dump-seed 导出一份）")
        return 0

    total = 0
    for name, path in files:
        rows = json.loads(path.read_text(encoding="utf-8"))
        fn = dict(SEED_TABLES)[name]
        if not rows:
            log(f"   {name}: 空文件，跳过")
            continue
        fn(conn, rows)
        total += len(rows)
        log(f"   {name}: 导入 {len(rows)} 行")
    return total


def dump_seed(conn):
    """把当前库内容导出成种子 JSON（不含 id，便于在任何库重建）。"""
    config.SEED_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, cols in EXPORT_COLS.items():
        collist = ", ".join(cols)
        rows = [dict(r) for r in
                conn.execute(f"SELECT {collist} FROM {name} ORDER BY 1, 2").fetchall()]
        path = config.SEED_DIR / f"{name}.json"
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=0) + "\n",
                        encoding="utf-8")
        total += len(rows)
        log(f"   {name}: 导出 {len(rows)} 行 → {path.relative_to(config.ROOT)}")
    return total


# ============================================================
# 主流程
# ============================================================
def main():
    ap = argparse.ArgumentParser(
        description="PostgreSQL 初始化：建库 / 建表 / 种子数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python scripts/init_pg.py --seed")
    ap.add_argument("--seed", action="store_true",
                    help="建库建表后导入 scripts/seed/*.json")
    ap.add_argument("--seed-only", action="store_true",
                    help="只导种子数据，不动表结构（表须已存在）")
    ap.add_argument("--dump-seed", action="store_true",
                    help="把当前库内容导出为 scripts/seed/*.json（用于重建/演示）")
    ap.add_argument("--recreate", action="store_true",
                    help="DROP 四张表后重建（清空数据，必须同时给 --yes）")
    ap.add_argument("--yes", action="store_true",
                    help="确认执行 --recreate 这类破坏性操作")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印将执行的步骤，不连库、不写库")
    args = ap.parse_args()

    if args.recreate and not args.yes:
        log("[拒绝] --recreate 会删除全部采集数据，请加 --yes 明确确认")
        return 1
    if args.dry_run:
        log("=== DRY-RUN：以下步骤不会真正执行，也不会连接数据库 ===")

    log(f"目标库：{target_desc()}")

    if args.dry_run:
        ensure_database(dry=True)
        if not args.seed_only:
            log("[dry-run] 将建表建索引：price_obs / spec_snapshot / product_trend / fetch_log")
            if args.recreate:
                log("[dry-run] 将先 DROP 上述四张表（--recreate）")
        if args.dump_seed:
            log("[dry-run] 将导出种子文件到 " + str(config.SEED_DIR))
        if args.seed or args.seed_only:
            dry_total = sum(len(json.loads(p.read_text(encoding="utf-8")))
                            for _, p in seed_files())
            log(f"[dry-run] 将导入种子：{dry_total} 行（来自 {len(seed_files())} 个文件）")
        log("=== DRY-RUN 结束，未做任何改动 ===")
        return 0

    failures = 0
    try:
        if not args.seed_only:
            ensure_database()
            conn = db.connect()
            if args.recreate:
                drop_tables(conn)
            db.init_schema(conn)
            log("表结构就绪（4 张表 + 索引）")
        else:
            conn = db.connect()

        if args.dump_seed:
            log("=== 导出种子 ===")
            dump_seed(conn)

        if args.seed or args.seed_only:
            log("=== 导入种子 ===")
            n = import_seed(conn)
            log(f"种子导入完成：{n} 行（幂等，重复执行不会重复插入）")

        counts = db.table_counts(conn)
        log("=== 当前各表条数 ===")
        for t, n in counts.items():
            log(f"   {t:<16}{n:>8}")
        conn.close()
    except Exception as e:  # noqa: BLE001 - CLI 边界，统一打印
        log(f"[失败] {type(e).__name__}: {e}")
        failures += 1

    if failures:
        return 2
    log("[完成] 初始化成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())
