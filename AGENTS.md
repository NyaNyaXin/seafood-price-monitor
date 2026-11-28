# AGENTS.md

给 AI 编码代理的项目说明书。**先读完第 1 节再动手**；人类读者请去 `README.md` / `deploy/README.md`。

---

## 0. 这个项目在做什么

用 Python 抓「全国水产技术推广总站 · 水产时价云」的**冷冻水产**报价（沈阳 2 市场为核心，另含辽宁 4 家与全国 53 家参考市场）→ 写 PostgreSQL → Nitro 接口 `/api/price-data` 直查库 → Nuxt 4 看板渲染（四个页面，涨红跌绿）。

```
scripts/fetch.py ──→ PostgreSQL ←── server/api/price-data.get.ts ──→ app/pages/*
  (本机手动执行 / Docker fetch 容器)      (Nitro 服务端, pg 连接池)      (纯客户端渲染)
```

**本机为手动执行**（2026-11-24 起不再走 Windows 计划任务）；Docker 部署的 `fetch` 容器仍保留每日循环。

最常改的三处：`shared/reference.json`（品种/市场/关键词）、`app/pages/*`（看板）、`scripts/fetch.py`（采集逻辑）。

---

## 1. 硬性约定（改了就出事）

| 约定 | 说明 |
|---|---|
| **包管理器只有 pnpm** | `packageManager: pnpm@12.10.1`。禁止 npm/yarn，禁止生成 `package-lock.json` / `yarn.lock`（`.gitignore`+`.dockerignore` 已挡）。 |
| **Node 22.22.3+ / 24.15+ / 26+** | Nuxt 4.7 的 `engines` 要求；已同步声明在 `package.json`。 |
| **`ssr: false` 不能改** | ECharts/canvas 在 SSR 阶段会崩；数据由客户端 `useFetch` 取。 |
| **不允许 JSON 中间层** | `public/data.json`、`data/data.js` 已删除。前端数据**只能**来自 `/api/price-data`。不要再"顺手导出个 json 给前端读"。 |
| **参考数据只有一个源** | 品种清单 / 市场 / 冻品判定关键词 / 阈值都在 `shared/reference.json`，Python `scripts/config.py` 与 Node `server/api/price-data.get.ts` 共读。**禁止在任一侧硬编码副本**。 |
| **数据库只有 PostgreSQL** | SQLite 后端已于 2026-11-24 **彻底移除**（`db.py` 无 `sqlite3` 导入、无 `DB_BACKEND`、无占位符适配层），SQL 直接用 psycopg2 的 `%s` / `%(name)s`。价格列必须 `DOUBLE PRECISION`（见 §4）。 |
| **建表逻辑只在 `db.init_schema()`** | DDL 定义在 `scripts/db.py::_PG_STATEMENTS`；`fetch.py` 启动时会调它（新库直接跑采集也能建表），日常初始化/种子/重建用 `scripts/init_pg.py`。不要手写 DDL 或恢复已删除的 `migrate_to_pg.py`。 |
| **涨红跌绿** | 中文行情惯例，别按欧美习惯改成绿涨红跌。 |

---

## 2. 目录地图

| 路径 | 职责 | 单一事实源？ |
|---|---|---|
| `tsconfig.json` | Nuxt 4 solution-style 根配置，只 `references` `.nuxt/tsconfig.{app,server,shared,node}.json` | ★ IDE 类型解析入口 |
| `shared/reference.json` | 29 个冻品品种、59 个市场（`tier` 分层）、冻品关键词、阈值 | ★ 是（Python + Node 共读） |
| `scripts/config.py` | 数据源地址/token/超时/重试/路径；读 reference.json | — |
| `scripts/db.py` | 建表、幂等 upsert、查询、CSV 导出；**唯一后端 PostgreSQL**（psycopg2 + RealDictCursor） | ★ 表结构 |
| `scripts/fetch.py` | 采集主脚本（两轮：快照 + 分规格/30天趋势），日志落 `logs/fetch.log` | — |
| `scripts/init_pg.py` | 建库 + 建表 + 索引（幂等）；`--seed` 导种子、`--dump-seed` 导种子文件、`--recreate --yes` 重建 | — |
| `scripts/seed/*.json` | 种子数据（快照，无 id），空库重建/演示用；说明见 `scripts/seed/README.md` | — |
| `server/utils/pg.ts` | `pg` Pool，挂 `globalThis` 防 HMR 重建；读 `process.env.DB_*` 优先 | — |
| `server/api/price-data.get.ts` | 唯一数据接口，冻品过滤下推 SQL | ★ 冻品 SQL 口径 |
| `server/api/health.get.ts` | 存活探针；`?db=1` 额外 `SELECT 1` | — |
| `server/utils/fetchRunner.ts` | 本机「立即采集」任务：spawn `scripts/fetch.py`、`globalThis` 状态单例、口令校验 | — |
| `server/api/fetch-{run,status}.ts` | `POST /api/fetch-run` 触发采集；`GET /api/fetch-status` 轮询进度 | — |
| `app/composables/usePriceData.ts` | 取数 + 全部派生逻辑（series/涨跌/阈值） | ★ 前端派生口径 |
| `app/pages/{index,trend,specs,history}.vue` | 四个路由页面 | — |
| `app/components/FetchButton.vue` | Hero 里的「立即采集」按钮（口令浮层 + 3s 轮询 + 进度/日志抽屉 + 完成自动刷新） | — |
| `app/{components,assets/css}` | 导航/Hero/Footer + 全局样式（含 Reka UI 组件样式） | — |
| `docker/` + `docker-compose.yml` | 线上：web + fetch 两容器，PG 在外部 | — |
| `deploy/` | 部署手册、env 模板、systemd（备选） | — |

---

## 3. 常用命令

```bash
pnpm install              # 依赖（首次或改依赖后）
pnpm dev                  # 开发 → http://localhost:3000
pnpm build                # 生产构建 → .output/
pnpm typecheck            # nuxt typecheck + vue-tsc，0 error 才算过
PORT=3011 node .output/server/index.mjs   # 生产形态启动（验证构建产物）

# 接口自检
curl -s "localhost:3000/api/health?db=1"        # 库连通（db.ok / latency_ms）
curl -s localhost:3000/api/price-data | head -c 200

# 采集 / 初始化（任意 cwd 都可，脚本内部会定位 ROOT）
python scripts/fetch.py                           # 手动抓一次（本机主用法，约 2–3 分钟）
python scripts/fetch.py --skip-list               # 跳过分规格，只抓快照（调试）
python scripts/init_pg.py                         # 建库 + 建表（幂等）
python scripts/init_pg.py --seed                  # 建表 + 导入 scripts/seed/*.json
python scripts/init_pg.py --dry-run               # 只看步骤，不连库不写库

# Docker
docker compose up -d --build
docker compose logs -f --tail=100 fetch
docker compose exec fetch python /app/scripts/fetch.py --verbose
```

> `pnpm build` 会清空重建 `.output`。**没有** `pnpm generate`——本项目必须常驻 Node 进程。

---

## 4. 数据模型（改动前必看）

| 表 | 唯一键（幂等 upsert 依据） | 备注 |
|---|---|---|
| `price_obs` | `(obs_date, market_id, product_id, spec_id)` | 市场当日快照，`obs_date` 为 `YYYY-MM-DD` |
| `spec_snapshot` | `(snap_date, region, product_id, spec_name)` | 分规格价，`region` ∈ `'cn'`/`'ln'` |
| `product_trend` | `(trend_date, region, product_id)` | 30 天趋势，同上 |
| `fetch_log` | 无（纯追加流水，不做幂等） | 采集流水：`status`/`raw_count`/`kept_count`/`error_msg` |

**价格列类型坑（血泪）**：
- 必须 `DOUBLE PRECISION`。PG 的 `REAL` 是 float4（6 位有效数字，`40.67` → `40.669998`），会污染涨跌计算。
- 不能用 `NUMERIC`：psycopg2 回来是 `Decimal`，`json.dumps` 直接抛 `TypeError`。

写入一律走 `scripts/db.py` 的 `upsert_*`，别手写 `INSERT`——重复跑采集必须幂等。
SQL 占位符写 psycopg2 原生形式：位置参数 `%s`、命名参数 `%(name)s`（**不要**再用 `?` / `:name`，适配层已删除）。

---

## 5. 数据链路铁律

1. **冻品判定双端必须同义**：Python `config.is_frozen()` 与 `price-data.get.ts` 里的 SQL（`NOT (... LIKE ANY($1)) AND (... LIKE ANY($2) OR ... LIKE ANY($3))`）是同一套规则的两种实现。改 `frozen_rules` 关键词后，**必须**两端各取一次结果比对（观测条数、规格条数、趋势品种数一致），否则页面数量与采集数量会对不上。
2. **慢品种不是限流**：`PRODUCT_TIMEOUT=8`（首轮快速筛）+ `PRODUCT_RETRY_TIMEOUT=35`（补偿轮）。这是实测结论——368/414/501 等品种平台侧固定 16–25s，与频率无关；**不要靠拉长间隔或降频来"解决"**，那样只是变慢。
3. **采集失败不得让进程退出**：单次失败写 `fetch_log`（ERROR）+ `logs/fetch.log` 后继续；容器入口也只在循环里记日志。本机是手动执行，偶发 403 下次再跑即可自愈。
4. **`obs_date` 取容器/机器本地日期**，所以 `TZ=Asia/Shanghai` 是硬要求，改成 UTC 会整体错一天。
5. **无年份日期按「晚于抓取日就回退一年」补年**：平台只给 `11月23日` / `10.23`，年份得自己拼。规则在 `fetch.py::resolve_date` —— 先按当年拼，若晚于抓取日（+1 天容差）则年份 -1。**别改回「只在 1–2 月回退」的旧逻辑**：那会让 11 月抓到的 `12.07` 变成当年 12 月，入库成未来日期（2026-11-24 清出 52 条 trend + 2 条 spec 脏数据，备份见 `data/archive/future-dates-2026-11-24.json`）。
6. **市场分层是展示口径，不是采集口径**：`reference.json → markets[id].tier` 分 `core`（沈阳 537/538，核心观测）/ `province`（辽宁其他 4 家）/ `national`（全国 53 家参考）。采集**全收**，前端按 tier 过滤。不要把「核心市场」限定写回采集脚本——那会让数据量退回 15 条/天。
7. **新增外部数据源先读 `docs/03-数据源调研.md`**：里面有实测可达性、鉴权、口径差异与不接入的理由（pfsc 价格明细有图形验证码、新发地只有鲜活且单位是斤）。新增源必须先进 `shared/reference.json`，并独立表/独立标识，禁止与冻品序列混绘。

---

## 6. 数据源接口要点

- 基址 `http://znyj.nftec.agri.cn:8089`，公开 token `0000000000000000`，**无 CORS**（所以必须服务端取数，别想着浏览器直连）。
- `GET /API/Product/GetPriceNow?rid=0&PageNum=N&pageSize=500`：**全国**市场当日报价，59 个市场 / 约 1047 条 / 3 页。分页参数**大写 `PageNum`**；`pageSize` 实测支持 500（早期文档写的「每页固定 10 条」是默认值，不是上限）。`rid=4` 是辽宁，`rid=21` 是福建。`unit_id` 过滤参数**无效**，必须全量拉回本地按 `markets` 白名单过滤。
- `GET /API/Product/GetPriceList?pid={品种}&rid={地区}`：`Data.standar.x`=规格档位、`standar.y[0]`=全国、`standar.y[1]`=辽宁（缺报为 0，要剔除）；`Data.trend.x`=30 天日期、`trend.y[0]`/`y[1]`=全国/辽宁逐日价（**曲线来自接口，不用自己攒**）。
- `GET /API/Product/GetCategorys`：375 个品种全目录。
- `GET /API/Product/GetVolumeList`：**名不副实**——返回的是均价 `priceAll`/`price30All`/`rateAll` 与 30 天趋势，**没有成交量字段**，别指望它补量。
- 请求头必须带浏览器 `User-Agent` + `Referer`，否则 `403`。
- 平台只报"代表规格"，缺口（有品种无冻品档、冻档全 0、规格名非冻品）是数据源上限，别当采集 bug 追。

---

## 7. 前端约定

- **Reka UI 无样式**：组件只给行为，样式在 `app/assets/css/main.css` 里自己写。新增组件记得补样式。
- `SelectItem` **不允许空字符串 value**（Radix 限制）——用哨兵值（如 `'__all__'`），别传 `''`。
- **ECharts 用静态 `import * as echarts from 'echarts'`**（写在 `app/pages/trend.vue` 顶部）。该页是独立路由 chunk，只有访问 `/trend` 才加载，体积与动态 import 相当。**不要改回 `await import('echarts')`**——实测会在页面切换时出现 import 请求挂起、回调永不返回，图表永久空白（2026-11-23 排查记录）。
- **下拉一律用 `app/components/SearchSelect.vue`**（Reka Combobox 封装，支持输入过滤、自动回填 label、`allLabel` 注入「全部」项）。不要再手写 `SelectRoot` 组合——它不支持搜索，且长列表会被裁切。`SearchSelect` 的输入框聚焦时会全选，直接在原值上改写。
- **筛选控件统一 38px 高**：`.ui-select` / `.ui-combo` / `.seg` 都是 `height:38px`，同一行必须等高，改样式时别只改一个。
- **`html{scrollbar-gutter:stable}` 不能删**：下拉浮层会触发滚动锁定，没有这行页面会因纵向滚动条出现/消失而左右抖动。
- Reka UI 的 `SelectViewport` 不要用：它会让长列表被 `SelectContent` 的内联 `max-height` 裁切且无法滚动。若必须用原生 Select，把 `<SelectItem>` 直接放进 `SelectContent`，靠 `.ui-select-content` 的 `max-height + overflow-y:auto` 滚动。
- 表格筛选结果为空时要有 `.empty-row` 提示行（`colspan` 占满），否则用户以为页面坏了。
- 数据派生统一放 `usePriceData.ts`（`seriesMap`/`series`/`changeAt`/`THR`/`marketTier`/`tidyMarket`…），页面只做展示，别在页面里重算涨跌。
- **市场显示走 `shortMkt(id, meta)`**：沈阳两家有固定简称，其余按名称清洗截断（全名放 `title`）。不要在市场列硬编码某家市场的样式或名称。
- `meta.market_tiers` 是「沈阳/辽宁/全国参考」筛选的依据，别在前端另写一份市场归属表。
- `useFetch('/api/price-data', { server:false, cache:'no-store' })` 的 `no-store` 不要动——去掉后采集入库了页面还是旧数。
- **`noUncheckedIndexedAccess` 是开着的**（Nuxt 4 默认）：`arr[i]`、`record[key]` 都是 `T | undefined`。取值先收窄（`if (!x) return null` / 局部变量），**不要用 `!` 或 `as any` 压下去**——这块最容易在类型检查里翻车。
- 类型检查读根 `tsconfig.json`（references 指向 `.nuxt/tsconfig.*.json`）。改完用 `pnpm typecheck` 验证，别只靠编辑器。
- 路由固定 `/`、`/trend`、`/specs`、`/history`；导航在 `SiteNav.vue`。链接用 `NuxtLink`。
- **「立即采集」按钮仅本机可用**：`POST /api/fetch-run` 用 `child_process.spawn` 跑 `scripts/fetch.py`，状态存在 `server/utils/fetchRunner.ts` 的 `globalThis` 单例里，前端每 3s 轮询 `/api/fetch-status`。运行中会自动展开右下角日志抽屉，显示阶段（快照/分规格/补偿轮）、百分比进度与最后 120 行输出；进度由日志行推导，不改动 `fetch.py`。启用条件 = 项目根有 `scripts/fetch.py` **且** 配置了 `FETCH_TOKEN`；Docker 的 web 镜像没有这两样，按钮自动禁用。**不要**为了「线上也能点」往 web 镜像塞 Python 或挂 `docker.sock`。

---

## 8. 部署（Docker 是主路径）

- `docker-compose.yml` 只有 `web` + `fetch`；**PostgreSQL 是外部已有容器**，compose 只连过去。连接方式三选一（`host.docker.internal` / 同网络填容器名 / 外部 IP）见 `deploy/README.md` 第二节。
- 配置全部运行期注入：`DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME/DB_CONNECT_TIMEOUT`，Python 与 Node 共用一套。**不要把连接串写进镜像或代码**。
- 镜像要点（改 Dockerfile 前务必理解）：
  - 基镜像 `node:22-slim`，**不要换 alpine**（rolldown/oxc 的 musl 预编译包容易缺）。
  - 依赖层 `pnpm install --frozen-lockfile --ignore-scripts` + `pnpm rebuild esbuild`：根包 `postinstall` 是 `nuxt prepare`，依赖层没源码会失败；esbuild 的 build 脚本必须补跑。
  - `pnpm-workspace.yaml` 的 `allowBuilds.esbuild` 必须为 `true`，否则 pnpm 12 跳过 esbuild 构建脚本。
  - 健康检查用 `node -e fetch(...)` 探 `/api/health?db=0`（slim 没有 curl/wget）。
- **前端是构建产物**：改完代码要 `docker compose up -d --build`，HMR 只在 `pnpm dev` 存在。
- **同机多项目**：服务器已有 `ledger-db` / `ledger-shared-net` 时，用 `docker-compose.server.yml` 覆盖（外部网络 + `WEB_PORT`），部署目录 `/opt/seafood-price-monitor`，一键 `bash scripts/deploy.sh`；**不要**另起数据库容器，也不要改动其他项目的服务。
- 线上库建表 / 导种子：`init_pg.py` 连的是 `DB_*` 指向的库，在本机跑一次指过去即可（`DB_HOST=<线上IP> python scripts/init_pg.py`）。种子文件在 `scripts/seed/`，**随镜像走**（`.dockerignore` 排除了 `data/`，别把种子放那儿）。
- systemd 单元只是裸机备选，别把 `deploy/systemd/*` 当主路径维护。

---

## 9. 改完必须自检

```bash
# 1) 类型 + 构建 + 生产形态起一次
pnpm typecheck                                     # 必须 0 error
pnpm build
PORT=3011 node .output/server/index.mjs &
curl -s "localhost:3011/api/health?db=1"          # 期望 status=ok, db.ok=true
curl -s localhost:3011/api/price-data | head -c 200
# 2) Python 侧：语法 + 干跑
python -m py_compile scripts/fetch.py scripts/db.py scripts/config.py scripts/init_pg.py
python scripts/init_pg.py --dry-run                # 不连库，只验证参数与路径
# 3) 若动了冻品关键词 / 表结构：两端各查一次，条数必须一致
#    采集端 scripts/db.py::all_observations(frozen_only=True) vs 接口返回的 total_obs
# 4) 若动了日期解析：查一遍未来日期（必须为 0）
#    注意 trend_date / snap_date 是 TEXT，比较要显式 ::text 转换
python -c "import sys;sys.path.insert(0,'scripts');import db;c=db.connect();print(c.execute('select count(*) n from product_trend where trend_date > current_date::text').fetchone()['n'])"
```

改动涉及 `shared/reference.json` 时，在提交说明里写清影响面（采集条数、看板覆盖度、SQL 过滤），因为它是三处逻辑的共同输入。

---

## 10. 不要做

- ❌ 用 npm / yarn 安装或提交它们的锁文件；❌ 改 `packageManager` 版本而不更新锁。
- ❌ 恢复 JSON 中间层（`public/data.json` / `data/data.js`）或让浏览器直连数据源（无 CORS）。
- ❌ 打开 `ssr: true`。
- ❌ 删根 `tsconfig.json`、关掉 `noUncheckedIndexedAccess`、或用 `as any` / `@ts-ignore` 把类型错误压掉（该修的是取值逻辑）。
- ❌ 把品种/市场/关键词写回 `config.py` 或 `.ts` 里（破坏单一事实源）。
- ❌ 改价格列类型（`REAL`/`NUMERIC`），或跳过 `upsert_*` 手写 INSERT。
- ❌ 为了让慢品种"成功"而延长首轮超时或降低采集频率（见 §5.2）。
- ❌ 把 `DB_PASSWORD` 写进 `nuxt.config.ts` 默认值、镜像、或 `deploy/*.env.example` 之外的任何地方。
- ❌ 恢复 SQLite 后端（`DB_BACKEND`、`sqlite3` 导入、`_to_pg()` 占位符适配层）或重新引入 `migrate_to_pg.py`——真相源只有 PostgreSQL，旧库已归档到 `data/archive/prices.db`。
- ❌ 在 `fetch.py` 里改回「只在 1–2 月回退年份」的日期补年逻辑（见 §5.5）。
- ❌ 提交 `node_modules`、`.output`、`.nuxt`、`logs/`、`data/`、`.env`。
- ❌ 换 `TZ` 或让容器用 UTC。
- ❌ 把 `docker/web.Dockerfile` 的 `node:22-slim` 换成 alpine，或删掉健康检查。

---

## 11. 本机（Windows 开发环境）已知怪癖

这些不是项目问题，是运行环境限制，别"修"代码去绕：

- **`pnpm dev` 只监听 `[::1]:3000`**：`curl 127.0.0.1:3000` 会 `ECONNREFUSED`，用 `http://localhost:3000` 或 `http://[::1]:3000`。
- **编辑器报错但 `pnpm typecheck` 通过**：多半是 TS Server 缓存了旧的推断项目。命令面板执行 `TypeScript: Restart TS Server`（或重开窗口）；`.nuxt/` 被清过就先 `pnpm dev` 生成再重启 TS Server。需要 Vue 语言服务（Vue - Official 扩展）才能正确解析 `.vue`。
- 在受限沙箱里**重复** `pnpm build` 可能报 `SAFE_DELETE_BULK_CONFIRM_REQUIRED`（Nitro 清理 `.output` 被拦）——先把 `.output` 移走/删掉再构建，正常终端无此问题。
- `schtasks.exe`、`wsl.exe` 可能被安全策略黑名单拦截；注册定时任务这类命令交给用户自己执行。
- 本机 PostgreSQL 是 `trust` + 空密码，仅限本机；线上必须设强密码并放行容器网段（`172.16.0.0/12`）。
- 数据源偶发 `403`，重试即可；连续多天全失败再查采集逻辑。

---

## 12. 提交纪律

- 一次改动一件事：采集逻辑 / 看板视觉 / 部署配置分开提交。
- 版本号只在 `package.json`（当前 5.1.0），功能变更顺手升 minor。
- 文档三处保持一致：`README.md`（概览）、`deploy/README.md`（部署细节）、本文件（约束与雷区）。改了一处记得同步另外两处。
