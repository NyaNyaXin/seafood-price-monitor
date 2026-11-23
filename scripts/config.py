# -*- coding: utf-8 -*-
"""配置中心：所有可调参数集中于此，改配置不用动业务代码。

注意：品种清单、市场、冻品判定关键词、阈值等「参考数据」不在本文件里写死，
统一放在 shared/reference.json —— Node 服务端（server/）也读同一份，
避免前后端各维护一份导致漂移。
"""
import json
import os
from pathlib import Path

# ---------- 路径（项目根 = scripts/ 的上一级，Windows/WSL 通用）----------
ROOT = Path(__file__).resolve().parent.parent
SHARED_DIR = ROOT / "shared"

# ---------- 共享参考数据（Python 采集 + Node API 单一事实源）----------
_REF = json.loads((SHARED_DIR / "reference.json").read_text(encoding="utf-8"))

# ---------- 数据源 ----------
BASE_URL = "http://znyj.nftec.agri.cn:8089"
API_PATH = "/API/Product/GetPriceNow"
API_PATH_LIST = "/API/Product/GetPriceList"   # 品种分规格价 + 30天历史（平台聚合口径）
TOKEN = "0000000000000000"          # 平台公开 token
RID_LIAONING = 4                    # 实测 4=辽宁（21=福建，勿改）；GetPriceList 用它取辽宁线
RID_NATION = 0                      # 全国：GetPriceNow 取全国 59 市场全量，GetPriceList 的 y[0] 也是全国
PAGE_SIZE = 500                     # GetPriceNow 实测支持 500/页，全国 1047 条约 3 页拉完

# ---------- 重点冻品品种（GetPriceList 按品种查，避开375全量限流）----------
# 只关注冷冻水产：海水鱼冻品 / 冻虾 / 冻贝 / 冻头足。淡水鱼、鲜活、干制品不采。
# 清单维护在 shared/reference.json → frozen_products（29 个重点品种）。
FROZEN_PRODUCTS = {
    int(p["id"]): (p["name"], p["category"]) for p in _REF["frozen_products"]
}

# 冻品判定规则：规格名含 exclude 词 → 非冻品；品名含 product 词 → 冻品；
# 否则规格名含 spec 词或 extra 词 → 冻品。
_RULES = _REF["frozen_rules"]
EXCLUDE_SPEC_KEYWORDS = tuple(_RULES["exclude_spec_keywords"])
FROZEN_PRODUCT_KEYWORDS = tuple(_RULES["frozen_product_keywords"])
FROZEN_SPEC_KEYWORDS = tuple(_RULES["frozen_spec_keywords"])
EXTRA_FROZEN_SPEC_KEYWORDS = tuple(_RULES["extra_frozen_spec_keywords"])
# 请求频率与超时（2026-11-23 实测诊断后定值）
# 诊断结论：不是限流。正常品种连打 15 次无间隔全部 0.2s 返回、无 403/429、无延迟递增。
# 慢是平台后端对特定品种（进口鱼/虾贝类 368/413/414/415/501/549）的固定查询耗时，
# 每个稳定 16~25s，与请求频率无关；返回体仅 ~1KB，排除数据量因素。
PRODUCT_FETCH_INTERVAL = 0.25      # 品种间隔秒：仅礼貌性限速，非必需（实测无频率限制）
PRODUCT_TIMEOUT = 8                # 首轮超时：快品种 0.2s 就回，8s 足够；慢品种快速失败留给补偿轮
PRODUCT_RETRY_TIMEOUT = 35         # 补偿轮超时：覆盖最慢实测 25.5s，留 ~10s 余量


def is_frozen(product_name, spec_name):
    """只关注冷冻水产：规格含'冻/冰/统货'，或品名本身是进口/冻/冰品。
    '统货'在冻品批发市场即冻品统货，且是辽宁本地少数有价的档位，保留。
    明确带'鲜/活'的鲜活档一律排除。

    关键词来自 shared/reference.json → frozen_rules，
    与 server/utils/frozen.ts 的 SQL 过滤条件保持同一份定义。
    """
    p = str(product_name or "")
    s = str(spec_name or "")
    if any(k in s for k in EXCLUDE_SPEC_KEYWORDS):
        return False
    if any(k in p for k in FROZEN_PRODUCT_KEYWORDS):
        return True
    return any(k in s for k in FROZEN_SPEC_KEYWORDS + EXTRA_FROZEN_SPEC_KEYWORDS)

# ---------- 关注的市场 ----------
# 清单来自 shared/reference.json → markets（59 个，tier 区分 core/province/national）
# core=沈阳两家（核心），province=辽宁其他 4 家，national=全国参考市场 53 家
MARKETS = {int(k): v["name"] for k, v in _REF["markets"].items()}
MARKET_TIERS = {int(k): v["tier"] for k, v in _REF["markets"].items()}

# ---------- 抓取 ----------
FETCH_TIME = "07:00"                # 仅供 Docker 采集容器（FETCH_AT）参考；本机为手动执行
RETRY_TIMES = 3                     # 失败重试次数
RETRY_BACKOFF = 2                   # 退避基数秒：2/4/8
HTTP_TIMEOUT = 15                   # 单次请求超时秒

# ---------- 数据规则 ----------
ALERT_THRESHOLD = _REF["alert_threshold"]   # 涨跌异常阈值 ±10%
STALE_DAYS = _REF["stale_days"]             # 超过 N 天未更新则告警
DROP_ZERO = True                    # 剔除 value=0.00 缺报占位

# ---------- 数据库（PostgreSQL，唯一后端）----------
# SQLite 已于 2026-11-24 彻底移除：历史数据已全部在 PG，本地库文件归档到 data/archive/。
# 线上部署用环境变量覆盖；Node 服务端（server/utils/pg.ts）读同一套 DB_* 变量，
# 因此两个进程可以共用一个 .env / systemd EnvironmentFile。
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")       # 本机 pg_hba 为 trust；线上填密码
DB_NAME = os.getenv("DB_NAME", "seafood_price")  # 专用库，与其它业务库隔离
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "8"))

# ---------- 路径（ROOT 已在文件顶部定义，供 reference.json 定位）----------
DATA_DIR = ROOT / "data"
EXPORT_DIR = DATA_DIR / "export"
SEED_DIR = ROOT / "scripts" / "seed"          # init_pg.py --seed 的种子数据（JSON）
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "fetch.log"    # 采集日志（手动执行/容器均写这里便于排查）

HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0 Safari/537.36"),
    "Referer": BASE_URL + "/",
}
