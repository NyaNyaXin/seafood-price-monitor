# 沈阳市冷冻水产行情系统 v5（Nuxt 4 + PostgreSQL 直连）

按需抓取全国水产技术推广总站「水产时价云」的**冷冻水产**数据，存 **PostgreSQL**，服务端直查数据库渲染看板。**涨红跌绿。**

> **v7 变更（去 SQLite + 手动采集）**：SQLite 后端**彻底移除** —— `db.py` 只保留 PostgreSQL（psycopg2 + `RealDictCursor`，SQL 写原生 `%s` / `%(name)s`，删掉 `_to_pg()` 适配层与 `DB_BACKEND` 开关），`data/prices.db` 归档到 `data/archive/`，`migrate_to_pg.py` 删除。建库建表改由 **`scripts/init_pg.py`** 负责（幂等；`--seed` 导入 `scripts/seed/*.json`、`--dump-seed` 反向导出、`--recreate --yes` 重建、`--dry-run` 真不连库）。采集改**本机手动执行**，不再挂 Windows 计划任务。同时修掉 `parse_md_date` 年份推断缺陷（跨年窗口被算成未来日期，清出 52 条 trend + 2 条 spec）。
>
> **v6 变更（数据源扩容）**：市场范围从沈阳 2 家扩到**全国 59 个批发市场**（`GetPriceNow` 改 `rid=0` + `pageSize=500`，3 次请求拉完全国 1047 条），冻品日采集量 **15 → 120 条**、覆盖市场 **2 → 30 个**。`shared/reference.json` 的 `markets` 升级为 `{ id: { name, tier } }`，`tier` 分 `core`（沈阳）/ `province`（辽宁其他）/ `national`（全国参考），首页新增「范围 + 市场」筛选。数据库表结构未变。数据源调研与不接入理由见 `docs/03-数据源调研.md`。
>
> **v5.1 变更（容器化 + pnpm）**：线上改为 **Docker + docker-compose** 一键部署（`docker-compose.yml` + `docker/`），Web 与采集各自一个容器，**PostgreSQL 不进 compose**（复用已在跑的独立容器），连接参数全在运行期由 `DB_*` 注入。新增 `/api/health` 健康探针（`?db=1` 顺带验库）。采集容器自带每日调度循环，不再依赖 cron / systemd timer；systemd 那套保留作裸机备选。**包管理器统一为 pnpm**（`packageManager: pnpm@12.10.1`，锁文件只留 `pnpm-lock.yaml`，`package-lock.json` 已删除）。
>
> **v5 变更（取数链路重构）**：不再生成 `public/data.json` 中间层。新增 Nitro 服务端接口 `GET /api/price-data`，用 `pg` 连接池**直接查 PostgreSQL** 组装看板数据（冻品过滤下推到 SQL）。采集端从 WSL cron 改到 **Windows 任务计划程序**（WSL2 的 `127.0.0.1` 与本机 PG 不互通）。品种清单 / 市场 / 冻品判定关键词 / 阈值抽到 `shared/reference.json`，**Python 采集与 Node 服务端共用一份**，不再两头维护。数据库连接统一为 `DB_*` 环境变量。
>
> **v4.1 变更（目录整理）**：Python 脚本从项目根目录收拢到 `scripts/`，`config.ROOT` 取 `scripts/` 的上一级，两个入口脚本加 `sys.path` 引导，可从任意目录执行。
>
> **v4 变更（数据层）**：真相源从 SQLite 迁到 **PostgreSQL**（库 `seafood_price`）。`scripts/db.py` 为**双后端**：`DB_BACKEND` 可选 `postgres`（默认）/ `sqlite`，业务 SQL 一行未改，适配层自动把 `?` / `:name` 转成 psycopg2 的 `%s` / `%(name)s`。`data/prices.db` 保留为历史归档，不再写入。
>
> **v3 变更（前端）**：四页静态 HTML 迁移为标准 **Nuxt 4** 项目，交互控件改用 **Reka UI**，ECharts 改为 npm 本地依赖。旧静态页已删除，备份另存 `../seafood-price-monitor-legacy-static-backup-2026-11-23.zip`。

数据源两条链路：
- **市场当日快照**（`GetPriceNow`，`rid=0` 全国）：59 个批发市场商户上报的成交报价，只留冻品规格。沈阳于洪 537 / 前当堡 538 为 `core` 核心观测，辽宁其他 4 家为 `province`，其余 53 家为 `national` 参考。
- **品种分规格 + 30天历史**（`GetPriceList`）：平台聚合口径，29 个重点冻品品种，含全国/辽宁分规格价 + 现成的 30 天双线序列——**曲线不用自己攒**。

## 目录结构

```
seafood-price-monitor/
├── # ---- Nuxt 4 前端 + 服务端 ----
├── nuxt.config.ts      Nuxt 配置（Reka UI module / ssr:false / runtimeConfig.db*）
├── tsconfig.json       ★ solution-style 根配置，引用 .nuxt/tsconfig.{app,server,shared,node}.json
├── package.json        依赖：nuxt 4 / reka-ui / echarts / pg（packageManager 锁 pnpm 版本）
├── pnpm-lock.yaml      ★ 唯一锁文件（npm/yarn 锁文件已删）
├── pnpm-workspace.yaml pnpm 12 的 allowBuilds（放行 esbuild 构建脚本）
├── app/
│   ├── app.vue         主组件（导航 + 页面 + 全局错误提示）
│   ├── pages/          文件路由：index / trend / specs / history
│   ├── components/     SiteNav / PageHero / SiteFooter（自动导入）
│   ├── composables/    usePriceData.ts（取数 + 派生逻辑）
│   └── assets/css/     main.css（全局样式 + Reka UI 组件样式）
├── server/
│   ├── api/price-data.get.ts   ★ 唯一数据接口：直查 PostgreSQL
│   ├── api/health.get.ts       容器健康探针（?db=1 顺带验库连通）
│   └── utils/pg.ts             pg 连接池（DB_* 环境变量）
├── shared/
│   └── reference.json  ★ 采集端与服务端共用的参考数据
├── # ---- Python 采集链路 ----
├── scripts/            ★ 所有 Python 脚本集中于此
│   ├── config.py       配置（数据源/路径/DB 连接；参考数据来自 shared/）
│   ├── db.py           数据层（唯一后端 PostgreSQL：建表/幂等 upsert/查询/CSV）
│   ├── fetch.py        采集脚本（两条链路 + 冻品过滤 + 日志落盘）
│   ├── init_pg.py      建库 + 建表 +（可选）种子数据，幂等
│   ├── seed/           种子数据 JSON（空库重建/演示，见其 README）
│   └── requirements.txt 采集端依赖（psycopg2-binary）
├── # ---- 容器化部署 ----
├── docker-compose.yml  ★ 线上部署入口：web + fetch 两个服务
├── docker/
│   ├── web.Dockerfile   Nuxt 多阶段构建，运行层只带 .output
│   ├── fetch.Dockerfile Python 采集镜像
│   └── fetch/entrypoint.sh 每日调度循环（sleep 到 FETCH_AT）
├── .dockerignore       构建上下文排除项（含 .env，防止密码进镜像）
├── deploy/             ★ 部署手册 + systemd 单元 + env 模板
├── data/
│   ├── archive/        旧 SQLite 库、脏数据备份、改造前脚本备份（仅留档）
│   └── export/prices.csv
├── logs/               采集日志（fetch.log）
├── docs/               需求文档 + 技术选型
├── AGENTS.md           ★ 给 AI 编码代理的约束清单（硬性约定 / 雷区 / 自检命令）
└── README.md           本文件
```

> 数据流：`采集（本机手动 / Docker）→ PostgreSQL → /api/price-data（Nitro）→ 浏览器`。
> **不再有 JSON 中间文件**——`public/data.json` 与 `data/data.js` 已删除，页面每次加载由服务端实时查库。
> `shared/reference.json` 是品种清单/市场/冻品判定关键词的唯一来源，Python 与 Node 同时读取，避免前后端各写一份而漂移。

## 一、部署

> 完整步骤（Windows 现在 / Linux 线上）见 **[`deploy/README.md`](deploy/README.md)**，这里只放要点。

### 1. 数据库（PostgreSQL）

首次部署先建库建表（脚本幂等，可重复执行）：

```bash
python scripts/init_pg.py            # 建库 seafood_price + 4 张表 + 索引
python scripts/init_pg.py --seed     # 想打开页面就有内容：再导入种子数据
```

- `--dry-run`：只打印将执行的步骤，**不连库、不写库**。
- `--dump-seed`：反向把当前库导出成 `scripts/seed/*.json`（备份/重建用）。
- `--recreate --yes`：DROP 四张表后重建，**数据全丢**，必须显式加 `--yes`。
- 种子是快照（无 id、无 `fetch_log`），导入走唯一键 upsert，重复导不会重复插。

连接参数全部走环境变量，**采集端与服务端共用同一套**（模板见 `deploy/seafood-price.env.example`）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `5432` | 数据库地址 |
| `DB_USER` / `DB_PASSWORD` | `postgres` / 空 | 本机 `pg_hba.conf` 为 trust；线上务必设置密码 |
| `DB_NAME` | `seafood_price` | 与 `project_ledger` / `retail_ledger` 隔离 |

### 2. 采集（本机手动执行）

不再挂 Windows 计划任务，需要数据时手动跑一次。在项目根目录：

```powershell
python scripts\fetch.py                 # 抓一次：快照 + 29 品种分规格/30天趋势（约 2–3 分钟）
python scripts\fetch.py --skip-list     # 只抓市场快照（约 10 秒，调试用）
```

- 成功时控制台最后一行是 JSON：`{"status":"OK","snapshot":120,"specs":42,"trends":1146,"products_ok":29,"products_total":29}`；明细同时追加进 `logs/fetch.log`。
- **重复跑安全**：三张表都有唯一键，同一天跑多次不会重复计数（`fetch_log` 是纯追加流水）。
- 耗时大头是 6 个平台侧固定慢查询品种（368/413/414/415/501/549，16–25s/个），首轮 8s 超时后由补偿轮 35s 补齐——日志里看到「失败(首轮) → 补偿轮」是正常路径。
- **别在凌晨刚过就跑**：`obs_date` 取本机本地日期，而平台报价是「11月23日」口径，00:30 跑回来的多半还是前一天的数据。
- 验证：
  ```powershell
  python -c "import sys;sys.path.insert(0,'scripts');import db;c=db.connect();print(db.table_counts(c))"
  ```
- 前置：本机 PostgreSQL 在跑（服务名类似 `postgresql-x64-17`），且 Python 装了 `psycopg2`（`python -m pip install -r scripts/requirements.txt`）。

> 线上 Docker 的 `fetch` 容器仍自带每日循环（`FETCH_AT`，默认 07:00），与本机手动执行互不影响。

### 3. 线上部署（Docker，推荐）

```bash
cp deploy/docker.env.example .env     # 填 DB_HOST / DB_USER / DB_PASSWORD / DB_NAME
docker compose up -d --build          # web(:3000) + fetch(每日 07:00 采集)
curl -s "localhost:3000/api/health?db=1"
```

- **PostgreSQL 不进 compose**：它已经在单独的容器里跑，compose 只负责连过去。三种连法（宿主机端口 / 共用容器网络 / 外部库）见 [`deploy/README.md`](deploy/README.md) 第二节。
- 采集容器自带 `sleep 到下一个 07:00` 的调度循环，**不依赖 cron / systemd timer**；单次失败只记日志不退出。
- 改代码后必须 `docker compose up -d --build`：前端是构建产物，HMR 只在 dev 模式存在。
- 镜像里不含连接串，`DB_*` 全在运行期注入，同一个镜像可跨环境复用。

## 二、日常使用

| 操作 | 命令 |
|---|---|
| 立即抓一次 | `python scripts/fetch.py` |
| 只抓市场快照（跳过分规格，调试快） | `python scripts/fetch.py --skip-list` |
| 建库建表 / 导种子 | `python scripts/init_pg.py` ／ `python scripts/init_pg.py --seed` |
| 导出种子（备份当前库） | `python scripts/init_pg.py --dump-seed` |
| 看采集记录 | `python -c "import sys;sys.path.insert(0,'scripts');import db;c=db.connect();print([dict(r) for r in db.fetch_logs(c,10)])"` |
| 看各表条数 | `python -c "import sys;sys.path.insert(0,'scripts');import db;c=db.connect();print(db.table_counts(c))"` |
| 接口自检（服务起在 3000） | `curl -s localhost:3000/api/price-data \| head -c 200` |
| 看采集日志 | `tail -f logs/fetch.log`（Windows：`Get-Content logs\fetch.log -Wait`） |
| 直接用 psql 查（若装了 psql） | `psql -h 127.0.0.1 -U postgres -d seafood_price -c "SELECT count(*) FROM product_trend"` |

## 三、看板（Nuxt 4 项目）

需要 Node.js 22+ 与 **pnpm**（本项目唯一包管理器，版本锁在 `package.json` 的 `packageManager` 字段）：

```bash
corepack enable            # 一次性：让 pnpm 按 packageManager 自动选版本
pnpm install               # 或 pnpm i
pnpm dev                   # → http://localhost:3000
```

> 没有 corepack 就 `npm i -g pnpm@12.10.1`。**不要用 npm / yarn 安装**——`package-lock.json` 已删除，
> 锁文件只有 `pnpm-lock.yaml`；混用会在 `node_modules` 里留下两套结构，构建结果不可复现。

生产构建：`pnpm build && pnpm preview`（产物 `.output/`，用 `node .output/server/index.mjs` 起服务）。

类型检查：`pnpm typecheck`（`nuxt typecheck` + vue-tsc，读根 `tsconfig.json` 的 references）。

> 根 `tsconfig.json` 是 Nuxt 4 的 solution-style 配置，只引用 `.nuxt/tsconfig.*.json`，本身不 include 任何目录。
> **不要删**：缺了它，VS Code 里 `server/api/*.ts` 会落进 inferred project，`defineEventHandler` / `getQuery` / `getPool` / `process` 全部报「找不到名称」。
> 它也依赖 `nuxt prepare` 生成的文件，所以 `.nuxt/` 被清掉后跑一次 `pnpm dev`（或 `pnpm install`）再打开编辑器。

> **不能再用 `pnpm generate` 做纯静态导出**——数据由 `/api/price-data` 实时查库，必须有一个 Node 进程在跑。也正因为如此，「双击 HTML 打开」这种用法在 v5 之后不再成立，本地开发请用 `pnpm dev`。

> 若在受沙箱限制的 IDE 里**重复**执行 `pnpm build` 时报 `SAFE_DELETE_BULK_CONFIRM_REQUIRED`（Nitro 清理 `.output` 被拦），先手动删掉 `.output` 和 `.nuxt` 两个目录再构建即可——与项目代码无关，正常终端环境不会有此问题。
>
> 另一个 pnpm 特有的坑：`pnpm-workspace.yaml` 里的 `allowBuilds.esbuild` 必须为 `true`，否则 pnpm 会跳过 esbuild 的构建脚本，导致 `nuxt build` 找不到平台二进制。新增带 install 脚本的依赖时要一并 `pnpm approve-builds`。

| 路由 | 内容 |
|---|---|
| **/ 今日概览** | 4 个 KPI + **当日报价表**。涨红跌绿、超 ±10% 黄底高亮、附每斤单价。 |
| **/trend 价格走势** | 默认引导态——**选市场 + 品种后**（Reka UI Select），只显示该品种 30 天双线。ECharts 本地依赖。 |
| **/specs 全国规格** | 分规格参考价，全国/辽宁切换（Reka UI Tabs）、按品种搜索、覆盖度进度条。 |
| **/history 历史明细** | 每日快照流水（最近 50 条，倒序）。 |

> 组件来自 Reka UI（`reka-ui/nuxt` 自动导入，无样式），样式在 `main.css` 末尾的 "Reka UI 组件样式" 段。
> 数据层统一在 `app/composables/usePriceData.ts`，四页共享一次请求。接口返回 `Cache-Control: no-store`，采集入库后刷新即见新数据，不再需要旧版的 `document.write` 时间戳 hack。
> 服务端连不上库时，页面顶部会出现红色提示条（`app.vue`），不会只剩空表。
> 首日市场快照只有 1 天数据，`较上期` 显示"—"属正常；品种曲线首日就有 30 天（平台现成序列）。

## 四、关键事实与防坑

| 项 | 说明 |
|---|---|
| 数据源 | 全国水产技术推广总站「智能渔技 / 水产时价云」`znyj.nftec.agri.cn:8089`，官方 `.agri.cn` 域，免登录 |
| 接口 A 快照 | `GET /API/Product/GetPriceNow`，`rid=4`（辽宁），`PageNum` **大写**分页，77 条/8 页 |
| 接口 B 分规格/历史 | `GET /API/Product/GetPriceList`，`pid`=品种ID（见 config.FROZEN_PRODUCTS），`rid=4`。一次返回全国+辽宁分规格价与 30 天 `trend` 双线 |
| 只关注冻品 | 采集端 `config.is_frozen()` / 服务端 `/api/price-data` 的 SQL 条件，关键词同来自 `shared/reference.json`：规格含"冻/冰/统货"或品名含"进口/冻/冰"保留；明确"鲜/活"剔除。淡水鱼全不采 |
| 0.00 占位 | 缺报占位，入库前剔除 |
| 日期无年份 | 快照 `11月23日`、趋势 `10.23`，平台不给年份。补年规则见 `fetch.py::resolve_date`：先按当年拼，**晚于抓取日则回退一年**（1 天容差）。旧逻辑只在 1–2 月回退，会把 11 月抓到的 `12.07` 算成当年 12 月 → 未来日期（2026-11-24 已清 52 条 trend + 2 条 spec，备份在 `data/archive/`） |
| 幂等 | 三张表各有 UNIQUE 约束，重复抓 UPSERT 不新增行（`ON CONFLICT DO UPDATE`） |
| 价格字段类型 | PG 必须用 `DOUBLE PRECISION`（8 字节）：`REAL` 是 float4 会截断 `40.67`，`NUMERIC` 会回 `Decimal` 导致 JSON 序列化失败 |
| 单市场历史 | `GetPriceList` 的 `uid` 参数无效，**拿不到于洪单市场历史**，只能到"辽宁全省"级——曲线双线是全国 vs 辽宁，不是于洪 vs 大连 |
| 超时根因（已实测诊断） | **不是限流**：正常品种连打 15 次无间隔全部 0.2s 返回、无 403/429、无延迟递增。慢是平台后端对特定品种（进口鱼/虾贝类 368/413/414/415/501/549）的固定查询耗时，每个稳定 16~25s，与频率无关（返回体仅 ~1KB，排除数据量）。 |
| 请求策略 | 首轮 8s 超时快速筛出慢品种 → 补偿轮 35s 超时（覆盖最慢 25.5s + 余量）逐个补齐。间隔 0.25s 仅礼貌性，实测并非必需。 |
| **规格覆盖不全** | 29/29 品种请求均成功；其中 **18 个**有全国分规格价（28 档）、**12 个**有辽宁分规格价（14 档），27 个有 30 天趋势。缺口 11 个已逐品种直调接口核实（见下表），全是平台本身不提供冻品规格价，**非采集遗漏**。规格页顶部有覆盖度进度条直接显示缺哪些品种 |
| 口径差异 | 市场快照=商户成交报价；分规格/趋势=平台聚合均价。两者口径不同，不要横向直接比价 |

**规格缺口 11 个品种的实测成因**（2026-11-23 直调 `GetPriceList` 核对原始 `standar.x/y`）：

| 成因 | 品种 | 说明 |
|---|---|---|
| 规格名无"冻/冰"字样 | 竹荚鱼、扇贝柱、海蜇皮、海蜇头 | 平台只报鲜品/通用规格（如"条重≥300""面蜇""每500克120粒"），被 `is_frozen()` 正确过滤 |
| 有冻规格名但冻档全为 0 价 | 中国对虾、日本对虾、斑节对虾 | 以中国对虾为例：`standar.x` 18 档里 9 档是"冻每500克…"，但对应 `y[全国]` 全为 0（只有前 6 档"鲜"有价），冻档无报价可采 |
| 规格字段为空或 `/` | 扇贝、金枪鱼 | 平台返回 `standar.x = ['/', ...]`，无有效规格 |
| 连趋势都没有（请求失败） | 鲽鱼 | 平台对该 pid 无数据返回；金枪鱼同时属于规格空 |

> 结论：18/29 是数据源能给到的上限，**再抓也补不齐**——这是平台侧的数据缺失，不是频率、超时或本地过滤配置的问题。

## 五、为什么不直连接口（重要）

数据源接口**没有 CORS 头**，浏览器 JS 跨域直连会被拦；且是 HTTP，https 页面还会触发混合内容拦截。所以必须落地采集这一层。

三个方案的取舍：

| 方案 | 是否采集 | 代价 |
|---|---|---|
| 纯前端直连 | 否 | ❌ CORS 挡死，不可行 |
| 本地 Python 转发服务（约 40 行） | 否，实时调 | ⚠️ 必须一直开着服务；且现在前端还要经 Nitro，链路更长 |
| **定时采集 + 服务端查库（当前方案）** | 是，每天一次 | ✅ 数据落在 PG，服务端直查；30 天历史是接口给的，不用自己攒 |

将来若要"免采集 + 实时"，把 Nitro 的 `/api/price-data` 内部改成实时调数据源即可（顺便天然解决了 CORS）。当前不需要。

## 六、线上部署产物

详细步骤见 [`deploy/README.md`](deploy/README.md)。**默认走 Docker**；不用 Docker 时才看 systemd 那套。

| 文件 | 用途 |
|---|---|
| `docker-compose.yml` | ★ 线上入口：`web`（Nitro :3000）+ `fetch`（每日采集）+ 共享网络 + 日志/CSV 命名卷 |
| `docker/web.Dockerfile` | 多阶段构建，运行层只带 `.output`，非 root，内置健康检查 |
| `docker/fetch.Dockerfile` | Python 3.11 + psycopg2，只带 `scripts/` 与 `shared/` |
| `docker/fetch/entrypoint.sh` | 每日调度循环（`FETCH_AT`，默认 07:00，容器本地时间） |
| `deploy/docker.env.example` | `.env` 模板，含三种 PG 连接方式 |
| `deploy/systemd/seafood-web.service` | 备选：裸机常驻（`node .output/server/index.mjs`，只监听 `127.0.0.1:3000`） |
| `deploy/systemd/seafood-fetch.service` + `.timer` | 备选：裸机每天 07:00 采集（`Persistent=true` 补跑） |
| `deploy/seafood-price.env.example` | 裸机两个进程共用的 `DB_*` 配置 |

容器化后可以顺手做：PG 换托管/开只读账号、前置 Nginx + HTTPS、看板加访问控制。
