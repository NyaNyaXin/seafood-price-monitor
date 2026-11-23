# -*- coding: utf-8 -*-
"""采集主脚本：
  A) GetPriceNow    —— 沈阳两市场当日商户快照（只留冻品规格）
  B) GetPriceList   —— 重点冻品品种的分规格价 + 30天历史（全国/辽宁）

两条链路都幂等入库（PostgreSQL）。看板由 Nuxt 服务端直接查库，不再生成 JSON 中间文件。
用法（在项目根目录执行）：
    python scripts/fetch.py               # 抓一次全量（本机手动执行 / 容器调度）
    python scripts/fetch.py --once        # 同上（兼容旧参数）
    python scripts/fetch.py --skip-list   # 只抓 A，跳过 B（调试用）
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

# 让同目录的 config / db 可被导入，从而支持从任意目录运行本脚本
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import db

# 采集日志文件句柄：由 run() 打开，log() 同步落盘，便于事后排查
_LOG_FH = None


def log(msg, verbose=True):
    stamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{stamp}] {msg}"
    if verbose:
        print(line, flush=True)
    fh = _LOG_FH
    if fh is not None:
        try:
            fh.write(line + "\n")
            fh.flush()
        except OSError:
            pass


def http_get_json(url, params, retries=config.RETRY_TIMES,
                  timeout=config.HTTP_TIMEOUT, verbose=True):
    """带重试的 GET JSON。失败抛异常。"""
    query = urllib.parse.urlencode(params)
    full = f"{url}?{query}"
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(full, headers=config.HTTP_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("Status") not in (0, 200, "0", "200", None, True):
                raise ValueError(f"接口 Status 异常: {data.get('Status')} "
                                 f"msg={data.get('Message')}")
            return data
        except Exception as e:  # noqa: BLE001 - 采集脚本需吞掉所有异常并重试
            last_err = e
            log(f"请求失败({attempt}/{retries}): {e}", verbose)
            if attempt < retries:
                time.sleep(min(config.RETRY_BACKOFF * attempt, 4))
    raise RuntimeError(f"请求最终失败: {last_err}")


# ==================== A. 市场当日快照 ====================

def fetch_all_markets(verbose=True):
    """分页拉取全国全部报价（rid=0，59 个市场 / 约 1047 条 / 3 页）。
    白名单过滤在 clean() 里做，这里只负责把原始数据取全。
    """
    all_items = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        data = http_get_json(
            config.BASE_URL + config.API_PATH,
            {"token": config.TOKEN, "rid": config.RID_NATION,
             "PageNum": page, "pageSize": config.PAGE_SIZE},
            verbose=verbose,
        )
        d = data.get("Data") or {}
        items = d.get("Items") or []
        all_items.extend(items)
        total_pages = int(d.get("TotalPageCount") or 1)
        log(f"[快照] 第 {page}/{total_pages} 页，本页 {len(items)} 条，"
            f"累计 {len(all_items)}/{d.get('TotalItemCount') or '?'}", verbose)
        if not items:
            break
        page += 1
    return all_items


CN_DATE_RE = re.compile(r"(\d{1,2})月(\d{1,2})日")


def resolve_date(month, day, fetch_dt):
    """把平台给的「无年份 (月, 日)」补成 ISO 日期。

    平台只给 `11月23日` / `10.23` 这类不含年份的标签，年份必须自己推：
      1. 先按抓取日当年拼；
      2. 若拼出的日期**晚于抓取日**，说明落在跨年窗口里
         （如 11 月抓到趋势点 `12.07`，实为去年 12 月），年份 -1。

    这里刻意**不留任何未来日期容差**：行情数据不存在"明天"的报价，
    一旦补年结果超前，只能是跨年窗口或平台数据异常，回退一年更安全
    （退一年最多让该点落在时间轴之外、图表不显示；留容差则会在图上多出一个
    "未来"的假点，2026-11-24 就因此残留 2 条 501 的 `2026-11-25`）。

    旧实现只在 `fetch_dt.month <= 2` 时回退年份，导致 3~12 月抓到的 `11.29`~`12.28`
    这类趋势点被算成当年年底 —— 入库后变成未来日期，在 /trend 页横轴上多出一截。
    2026-11-24 用 `> 今天` 反查出 52 条 trend + 2 条 spec 脏数据（549/368/501）。
    """
    for year in (fetch_dt.year, fetch_dt.year - 1):
        try:
            cand = date(year, month, day)
        except ValueError:      # 2月29日等非法组合，换一年再试
            continue
        if cand <= fetch_dt.date():
            return cand.isoformat()
    return None


def parse_obs_date(cn_date, fetch_dt):
    """'11月23日' -> '2026-11-23'；跨年规则见 resolve_date。"""
    m = CN_DATE_RE.search(str(cn_date))
    if not m:
        raise ValueError(f"无法解析日期: {cn_date!r}")
    d = resolve_date(int(m.group(1)), int(m.group(2)), fetch_dt)
    if not d:
        raise ValueError(f"无法解析日期: {cn_date!r}")
    return d


def clean(items, fetch_dt, verbose=True):
    """白名单市场 + 只留冻品 + 清洗。返回 (rows, stats)。"""
    rows = []
    seen = set()
    stat = {"raw": len(items), "core": 0, "province": 0, "national": 0,
            "fresh": 0, "zero": 0, "dup": 0}
    for it in items:
        market_id = int(it.get("unit_id") or 0)
        if market_id not in config.MARKETS:
            continue
        tier = config.MARKET_TIERS.get(market_id, "national")
        stat[tier] = stat.get(tier, 0) + 1
        product_name = str(it.get("product") or "")
        spec_name = str(it.get("standard") or "")
        if not config.is_frozen(product_name, spec_name):
            stat["fresh"] += 1
            continue
        try:
            price = float(it.get("value"))
        except (TypeError, ValueError):
            stat["zero"] += 1
            continue
        if config.DROP_ZERO and price <= 0:
            stat["zero"] += 1
            continue
        obs_date = parse_obs_date(it.get("date"), fetch_dt)
        product_id = int(it.get("product_id") or 0)
        spec_id = int(it.get("standard_id") or 0)
        key = (obs_date, market_id, product_id, spec_id)
        if key in seen:
            stat["dup"] += 1
            continue
        seen.add(key)
        rows.append({
            "obs_date": obs_date,
            "fetch_time": fetch_dt.isoformat(timespec="seconds"),
            "market_id": market_id,
            "market_name": config.MARKETS[market_id],
            "product_id": product_id,
            "product_name": product_name,
            "spec_id": spec_id,
            "spec_name": spec_name,
            "price": price,
        })
    markets_hit = len({r["market_id"] for r in rows})
    log(f"[快照] 原始{stat['raw']} → 白名单{stat['core'] + stat['province'] + stat['national']} "
        f"(沈阳{stat['core']}/辽宁其他{stat['province']}/全国{stat['national']}) "
        f"→ 冻品{len(rows)}条/{markets_hit}市场 "
        f"(剔鲜活{stat['fresh']}, 去0值{stat['zero']}, 重复{stat['dup']})", verbose)
    return rows, stat


# ==================== B. 分规格 + 30天历史 ====================

MD_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})")


def parse_md_date(md, fetch_dt):
    """'10.23' -> '2026-10-23'；跨年规则见 resolve_date。解析失败返回 None。"""
    m = MD_DATE_RE.search(str(md))
    if not m:
        return None
    return resolve_date(int(m.group(1)), int(m.group(2)), fetch_dt)


def fetch_product_detail(pid, verbose=True, timeout=None):
    """GetPriceList：一次返回全国+辽宁分规格价与30天趋势。"""
    return http_get_json(
        config.BASE_URL + config.API_PATH_LIST,
        {"token": config.TOKEN, "rid": config.RID_LIAONING, "pid": pid},
        retries=1,
        timeout=config.PRODUCT_TIMEOUT if timeout is None else timeout,
        verbose=verbose,  # 品种多，单品种快速失败跳过
    )


def clean_product_detail(pid, data, fetch_dt, verbose=True):
    """解析出 (spec_rows, trend_rows)。只保留冻品规格档。"""
    d = data.get("Data") or {}
    name, cat = config.FROZEN_PRODUCTS[pid]
    snap_date = parse_obs_date(d.get("date"), fetch_dt)
    st = d.get("standar") or {}
    specs = st.get("x") or []
    ys = st.get("y") or []
    y_cn = ys[0] if len(ys) > 0 else []
    y_ln = ys[1] if len(ys) > 1 else []

    spec_rows = []
    for i, spec in enumerate(specs):
        if not config.is_frozen(name, spec):
            continue
        for region, arr in (("cn", y_cn), ("ln", y_ln)):
            v = arr[i] if i < len(arr) else 0
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if v <= 0:  # 0=该区无报送，跳过
                continue
            spec_rows.append({
                "snap_date": snap_date, "region": region,
                "product_id": pid, "product_name": name,
                "category": cat, "spec_name": spec,
                "price": v, "fetch_time": fetch_dt.isoformat(timespec="seconds"),
            })

    # 30天趋势：带鱼等品名非"冻"字，但整个品种清单都是冻品重点品种，全收
    trend_rows = []
    tr = d.get("trend") or {}
    xs = tr.get("x") or []
    ty = tr.get("y") or []
    t_cn = ty[0] if len(ty) > 0 else []
    t_ln = ty[1] if len(ty) > 1 else []
    for i, md in enumerate(xs):
        td = parse_md_date(md, fetch_dt)
        if not td:
            continue
        for region, arr in (("cn", t_cn), ("ln", t_ln)):
            v = arr[i] if i < len(arr) else 0
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if v <= 0:
                continue
            trend_rows.append({
                "trend_date": td, "region": region,
                "product_id": pid, "product_name": name,
                "price": v, "fetch_time": fetch_dt.isoformat(timespec="seconds"),
            })
    log(f"[规格] pid={pid} {name}: 冻品规格{len(spec_rows)}条, 趋势{len(trend_rows)}条", verbose)
    return spec_rows, trend_rows


def fetch_all_products(verbose=True):
    """遍历重点冻品品种，抓分规格价+30天历史。
    两轮：首轮全量 + 失败品种补偿轮（平台偶发超时）。返回 (spec_rows, trend_rows, stat)。
    """
    spec_rows, trend_rows = [], []
    pids = list(config.FROZEN_PRODUCTS)
    stat = {"total": len(pids), "ok": 0, "fail": 0}
    failed = []
    for i, pid in enumerate(pids, 1):
        try:
            data = fetch_product_detail(pid, verbose=False)
            s, t = clean_product_detail(pid, data, datetime.now(), verbose)
            spec_rows.extend(s)
            trend_rows.extend(t)
            stat["ok"] += 1
        except Exception as e:  # noqa: BLE001 - 单品种失败不拖垮全批
            failed.append(pid)
            log(f"[规格] pid={pid} 失败(首轮): {e}", verbose)
        if i < len(pids):
            time.sleep(config.PRODUCT_FETCH_INTERVAL)

    # 补偿轮：对失败品种再试一次，间隔稍长
    if failed:
        log(f"[规格] 补偿轮: 重试 {len(failed)} 个失败品种", verbose)
        time.sleep(1.0)
        still_failed = []
        for pid in failed:
            try:
                # 补偿轮：平台对部分品种固定慢查询 16~25s（非限流），超时放到 35s
                data = fetch_product_detail(pid, verbose=False,
                                            timeout=config.PRODUCT_RETRY_TIMEOUT)
                s, t = clean_product_detail(pid, data, datetime.now(), verbose)
                spec_rows.extend(s)
                trend_rows.extend(t)
                stat["ok"] += 1
                stat["fail"] -= 1
            except Exception as e:  # noqa: BLE001
                still_failed.append(pid)
                log(f"[规格] pid={pid} 仍失败: {e}", verbose)
            time.sleep(0.6)
        stat["fail"] = len(still_failed)

    log(f"[规格] 完成: {stat['ok']}/{stat['total']} 品种成功, "
        f"规格{len(spec_rows)}条, 趋势{len(trend_rows)}条", verbose)
    return spec_rows, trend_rows, stat


# ==================== 主流程 ====================

def run(verbose=True, skip_list=False):
    global _LOG_FH
    fetch_dt = datetime.now()

    # 采集日志落盘：手动执行/容器无人值守时靠它排查
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    _LOG_FH = open(config.LOG_FILE, "a", encoding="utf-8")
    _LOG_FH.write(f"\n===== {fetch_dt:%Y-%m-%d %H:%M:%S} 开始采集 =====\n")

    conn = db.connect()
    db.init_schema(conn)
    try:
        # A. 市场快照（全国白名单市场）
        items = fetch_all_markets(verbose=verbose)
        rows, stat = clean(items, fetch_dt, verbose=verbose)
        db.upsert_observations(conn, rows)

        # B. 分规格 + 30天历史
        spec_rows, trend_rows, pstat = ([], [], {"ok": 0, "total": 0})
        if not skip_list:
            spec_rows, trend_rows, pstat = fetch_all_products(verbose=verbose)
            db.upsert_spec_snapshot(conn, spec_rows)
            db.upsert_trend(conn, trend_rows)

        db.export_csv(conn)
        db.log_fetch(conn, "OK", stat["raw"] + pstat["total"],
                     len(rows) + len(spec_rows) + len(trend_rows))
        log(f"入库: 快照{len(rows)} + 规格{len(spec_rows)} + 趋势{len(trend_rows)} "
            f"| 日期 {db.latest_date(conn)}", verbose)
        return {"status": "OK", "snapshot": len(rows),
                "specs": len(spec_rows), "trends": len(trend_rows),
                "products_ok": pstat["ok"], "products_total": pstat["total"]}
    except Exception as e:  # noqa: BLE001
        db.log_fetch(conn, "ERROR", 0, 0, str(e))
        raise
    finally:
        conn.close()
        if _LOG_FH is not None:
            _LOG_FH.write(f"===== {datetime.now():%Y-%m-%d %H:%M:%S} 结束 =====\n")
            _LOG_FH.close()
            _LOG_FH = None


def main():
    ap = argparse.ArgumentParser(description="沈阳冻品水产批发报价采集")
    ap.add_argument("--once", action="store_true", help="立即抓一次（默认行为）")
    ap.add_argument("--verbose", action="store_true",
                    help="兼容旧参数：当前默认就打印明细，加不加效果相同")
    ap.add_argument("--skip-list", action="store_true", help="跳过分规格接口（调试用）")
    args = ap.parse_args()
    try:
        result = run(verbose=True, skip_list=args.skip_list)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)
    except Exception as e:  # noqa: BLE001
        print(f"[FATAL] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
