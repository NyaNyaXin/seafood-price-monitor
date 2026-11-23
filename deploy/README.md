# 部署手册

## 架构

```
采集（Python 容器）→ PostgreSQL（已有独立容器）← Nitro 服务端（Node 容器）→ 浏览器
```

- **采集端**：`scripts/fetch.py` 抓「水产时价云」接口，幂等写 PostgreSQL。不产出任何 JSON 文件。
- **服务端**：Nitro 的 `/api/price-data` 直连 PostgreSQL（`pg` 连接池），把观测/规格/30天趋势组装给前端。
- **浏览器**：四个页面通过 `/api/price-data` 取数。

两端共用同一套 `DB_*` 环境变量，所以一份配置能同时喂给采集与 Web。

| 变量 | 默认 | 说明 |
|---|---|---|
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `5432` | 数据库地址（Docker 下见第二节） |
| `DB_USER` / `DB_PASSWORD` | `postgres` / 空 | 线上务必设置强密码 |
| `DB_NAME` | `seafood_price` | 专用库 |
| `DB_CONNECT_TIMEOUT` | `8` | 秒 |
| `TZ` | `Asia/Shanghai` | 采集日期/日志用容器本地时间，别改 UTC |
| `WEB_BIND` / `WEB_PORT` | `0.0.0.0` / `3000` | Web 容器对外发布地址 |
| `FETCH_AT` | `07:00` | 每天采集时刻（容器本地时间） |
| `RUN_ON_START` | `true` | 采集容器启动时先跑一次 |
| `DOCKER_NETWORK` | `seafood-net` | compose 使用的网络名 |

---

## 一、当前：Windows 本机（手动执行）

本机 PostgreSQL 只监听 `127.0.0.1`，WSL 的 `127.0.0.1` 是它自己的命名空间，**WSL 里的 cron 连不上**，所以采集在 Windows 侧跑。**2026-11-24 起不再挂任务计划，改为需要时手动执行**。

### 1. 确认解释器

```powershell
where python
python -c "import psycopg2; print(psycopg2.__version__)"
```

若 `psycopg2` 缺失（scoop 装的全局 Python 常缺）：

```powershell
python -m pip install -r scripts\requirements.txt
```

用 venv 时，下面命令里的解释器路径换成 `<项目>\.venv\Scripts\python.exe`。

### 2. 执行采集

```powershell
cd <项目根>
python scripts\fetch.py                 # 全量：快照 + 29 品种分规格/30 天趋势（约 2–3 分钟）
python scripts\fetch.py --skip-list     # 只抓市场快照（约 10 秒，调试用）
```

- 成功时最后一行是 `{"status":"OK","snapshot":...,"products_ok":29,"products_total":29}`。
- 重复跑幂等，同一天多次执行不会重复计数（`fetch_log` 是纯追加流水）。
- `obs_date` 取本机本地日期，**凌晨刚过跑回来的多是前一天数据**，建议上午再跑。
- 日志由脚本自己写 `logs/fetch.log`，无需重定向。

### 3. 验证

```powershell
Get-Content logs\fetch.log -Tail 20
```

```powershell
cd <项目根>
python -c "import sys;sys.path.insert(0,'scripts');import db;c=db.connect();print(db.table_counts(c))"
python -c "import sys;sys.path.insert(0,'scripts');import db;c=db.connect();print(db.fetch_logs(c,5))"
```

### 4. 注意

- 本机 PG 为 trust 认证、空密码，仅适合本机使用。
- 采集全程约 3 分钟（部分进口鱼/虾贝品种平台查询固定慢 16–25 秒，属数据源特性）。
- 数据源偶发 `403 Forbidden`（平台侧限流），脚本会重试 3 次并把 `ERROR` 记入 `fetch_log`；不影响已有数据，下次手动执行时再试即可。

---

## 二、线上：Docker + docker-compose（推荐）

两个容器，一个 compose 文件，**数据库不进来**：

```
┌─ seafood-web   (Nitro,  :3000) ─┐
│                                 ├─→ 已有 PostgreSQL 容器（外部，不在本 compose）
└─ seafood-fetch (Python, 07:00) ─┘
```

镜像里**不含任何数据库连接串**，`DB_*` 全在运行期注入，所以同一个镜像能搬到任何环境，换库只改 `.env`。

| 文件 | 作用 |
|---|---|
| `docker-compose.yml` | 两个服务 + 网络 + 采集日志/CSV 命名卷 |
| `docker/web.Dockerfile` | 两阶段构建 Nuxt（pnpm），只把 `.output` 带进运行层，非 root |
| `docker/fetch.Dockerfile` | Python 3.11 + psycopg2，自带每日调度循环 |
| `docker/fetch/entrypoint.sh` | `sleep` 到下一个 `FETCH_AT` 的循环，不依赖 cron |
| `deploy/docker.env.example` | `.env` 模板（含三种连库方式） |
| `.dockerignore` | 排除 `node_modules` / `.env` / 日志 / 本地数据 |
| `pnpm-lock.yaml` + `pnpm-workspace.yaml` | 唯一锁文件 + `allowBuilds.esbuild`（缺了 esbuild 二进制不会被铺好） |

### 1. 准备 .env

```bash
cp deploy/docker.env.example .env
vi .env      # 至少改 DB_HOST / DB_USER / DB_PASSWORD / DB_NAME
```

`.env` 同时被 `.gitignore` 和 `.dockerignore` 排除——不会提交，也不会打进镜像层。

### 2. 让容器连上已在跑的 PostgreSQL

三选一：

**A. 走宿主机端口（最省事）**

PG 容器已经把端口发布到宿主机：

```bash
docker ps --format '{{.Names}}\t{{.Ports}}' | grep 5432
# 能看到 0.0.0.0:5432->5432/tcp 就行
```

`.env` 保持 `DB_HOST=host.docker.internal`。compose 已给两个服务加了
`extra_hosts: host.docker.internal:host-gateway`，Linux 上也能解析（无需改宿主 hosts）。

**B. 走容器网络（不发布端口，更内网）**

把 PG 容器接进 compose 用的网络（默认 `seafood-net`，compose 首次起服务时也会自动创建）：

```bash
docker network create seafood-net 2>/dev/null || true   # 先建好，避免非要先起两个容器
docker network connect seafood-net <PG容器名>
```

`.env` 改 `DB_HOST=<PG容器名>`（如 `seafood-postgres`），容器名即主机名。

> PG 是另一个 compose 项目起的：把 `DOCKER_NETWORK` 设成那个项目已有的网络名直接复用，
> 再 `docker network connect <网络名> <PG容器名>` 即可，不必自建网络。

**C. 外部库**：`DB_HOST` 直接填 IP / 域名，注意对方 `pg_hba.conf` 放行本机公网 IP。

### 3. 首次：建库（+ 可选的历史数据迁移）

**a. 建库**（只需库，表由采集脚本自己 `CREATE TABLE IF NOT EXISTS`）：

```bash
docker exec -it <PG容器名> psql -U postgres -c "CREATE DATABASE seafood_price;"
# 库已存在会报 already exists，忽略即可
```

**b. 建表**：不用手动做——容器首次跑采集就会建表建索引。想先建好再起服务：

```bash
docker compose run --rm --entrypoint python fetch -c "
import sys; sys.path.insert(0,'/app/scripts')
import db; c=db.connect(); db.init_schema(c); print('schema ok')"
```

**c. 种子数据（可选）**：种子随 `scripts/seed/` 进镜像（`data/` 被 `.dockerignore` 排除，
别把种子放那儿）。想打开页面就有内容：

```bash
docker compose run --rm --entrypoint python fetch /app/scripts/init_pg.py --seed
```

也可以在本机直连线上库跑：`$env:DB_HOST="<线上PG地址>"; python scripts\init_pg.py --seed`。

不导种子也能正常起，只是看板从第一次采集开始攒数据（30 天趋势来自接口，不受影响）。

### 4. 起服务

```bash
docker compose up -d --build
docker compose ps            # web 应为 Up (healthy)
```

Web 只暴露 `3000`（`WEB_BIND=127.0.0.1` 可只监听本机，交给 Nginx/Caddy 反代）。
浏览器打开 `http://<服务器IP>:3000`。

### 5. 验证

```bash
# 1) 进程活着（不碰数据库）
curl -s localhost:3000/api/health
# {"status":"ok","uptime_s":12,...}

# 2) 数据库通不通（就绪探针）
curl -s "localhost:3000/api/health?db=1"
# {"status":"ok","db":{"ok":true,"latency_ms":3}}

# 3) 真实数据
curl -s localhost:3000/api/price-data | head -c 300

# 4) 采集容器日志（启动即跑一次，约 3 分钟）
docker compose logs -f --tail=50 fetch
```

### 6. 日常运维

```bash
docker compose logs -f web                  # Web 日志
docker compose logs -f --tail=100 fetch     # 采集日志
docker compose restart fetch                # 重启采集（会立刻重跑一次）
docker compose up -d --build                # 改代码后重建（纯后端改动也要重建，前端是构建产物）
docker compose down                         # 停容器，命名卷保留
```

手动补跑一次采集（不干扰调度循环）：

```bash
docker compose exec fetch python /app/scripts/fetch.py --verbose
```

看采集写的日志文件与 CSV（在命名卷里，容器重建不丢）：

```bash
docker compose exec fetch tail -n 50 /app/logs/fetch.log
docker compose exec fetch ls -lh /app/data/export
```

把日志/CSV 拷出来：

```bash
docker cp seafood-fetch:/app/logs/fetch.log ./fetch.log
docker cp seafood-fetch:/app/data/export/prices.csv ./prices.csv
```

### 7. 调度与时间

采集容器里就是一个 `while` 循环：启动时按 `RUN_ON_START` 决定是否立刻跑，之后
每个 `FETCH_AT`（**容器本地时间**）跑一次，然后 `sleep` 到下一个点。

- 容器重启（`restart: unless-stopped` + `RUN_ON_START=true`）会立刻补跑一次，服务器重启也不怕。
- 停机期间错过的时间点**不补跑**，但每天固定一次，影响可忽略。
- `TZ` 必须是 `Asia/Shanghai`：采集日期取容器本地日期，改成 UTC 会把 `obs_date` 记成前一天。
- 单次采集失败不会让容器退出，只记日志（`/app/logs/fetch.log` + `fetch_log` 表），等下一轮。

### 8. 反向代理（可选）

```nginx
location / {
    proxy_pass http://127.0.0.1:3000;   # 配合 WEB_BIND=127.0.0.1
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

### 9. 镜像要点（为什么这么写）

- **两阶段**：`node_modules` 与源码只存在构建层，运行层只有 Nitro 的 `.output`（约百 MB 级）。
- **pnpm 固定版本**：镜像里 `npm i -g pnpm@12.10.1`，与 `package.json` 的 `packageManager` 一致；只用 `pnpm-lock.yaml`，`package-lock.json` 已删除。
- **安装时 `--ignore-scripts` + `pnpm rebuild esbuild`**：依赖层还没源码，根包 postinstall（`nuxt prepare`）会失败；而 esbuild 的 build 脚本必须补跑，否则没有平台二进制。
- **`allowBuilds.esbuild: true`**（`pnpm-workspace.yaml`）：pnpm 12 默认不执行依赖的 build 脚本，不放行等于 esbuild 装了个空壳。
- **运行期注入配置**：`server/utils/pg.ts` 先读 `process.env.DB_*`，所以同一个镜像跨环境复用。
- **非 root**：web 用 `app` 用户，fetch 用 uid 10001。
- **健康检查在 Dockerfile 里**：`/api/health?db=0` 只探进程，库挂了不会触发重启风暴。
- **分服务**：Web 与采集各自重建，采集挂了不影响看板访问。

---

## 三、线上（不用 Docker 时）：Linux + systemd

> 只有在裸机/虚拟机直接跑进程时才需要这一节；正常上云走第二节 Docker 更省事。

### 1. 前置

- Node.js **22+**（Nuxt 4 要求）与 **pnpm**（`corepack enable` 或 `npm i -g pnpm@12.10.1`）
- Python **3.11+** 与 `venv`
- PostgreSQL 14+（本机或托管），库名 `seafood_price`

### 2. 部署代码

```bash
sudo useradd -r -m -d /srv/seafood-price-monitor seafood
sudo -u seafood git clone <repo> /srv/seafood-price-monitor   # 或 rsync 上传
cd /srv/seafood-price-monitor

# 前端依赖 + 构建（包管理器统一 pnpm，版本锁在 package.json 的 packageManager）
corepack enable          # 一次性
pnpm install --frozen-lockfile
pnpm build               # 产物在 .output/

# 采集端虚拟环境
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt
```

### 3. 配置数据库连接

```bash
sudo cp deploy/seafood-price.env.example /etc/seafood-price.env
sudo chmod 600 /etc/seafood-price.env
sudo nano /etc/seafood-price.env     # 填真实 DB_* 值
```

建库（若线上还没有）：

```bash
sudo -u postgres createdb seafood_price    # 也可以交给 init_pg.py 自动建库
# 建表 +（可选）种子数据（幂等）
.venv/bin/python scripts/init_pg.py --seed
```

### 4. 安装 systemd 单元

```bash
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload

# Web
sudo systemctl enable --now seafood-web
sudo systemctl status seafood-web

# 采集定时器
sudo systemctl enable --now seafood-fetch.timer
systemctl list-timers seafood-fetch.timer

# 手动跑一次采集验证
sudo systemctl start seafood-fetch
journalctl -u seafood-fetch -n 50 --no-pager
```

### 5. 反向代理

Web 只监听 `127.0.0.1:3000`，用 Nginx / Caddy 反代：

```nginx
location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

### 6. 时区

`seafood-fetch.timer` 写的是 `OnCalendar=*-*-* 07:00:00`，含义是**服务器本地时间** 07:00：

```bash
timedatectl set-timezone Asia/Shanghai   # 若不是
```

服务器坚持用 UTC 的话，改成 `OnCalendar=*-*-* 23:00:00`（UTC 前一日 23 点 = 北京 07:00）。

---

## 四、排错

### Docker（第二节）

| 现象 | 排查 |
|---|---|
| `docker compose ps` 里 web 一直 `Restarting` | `docker compose logs --tail=80 web`；多半是构建或端口占用（`WEB_PORT` 换一个） |
| web `Up` 但页面顶部红条「数据加载失败」 | `docker compose exec web node -e "fetch('http://127.0.0.1:3000/api/health?db=1').then(r=>r.text()).then(console.log)"` 看 `db.error`；再 `docker compose exec web getent hosts $DB_HOST` 确认能解析到 PG（镜像里没有 curl/wget，用 node） |
| `db.error: password authentication failed` | `.env` 的 `DB_USER`/`DB_PASSWORD` 与 PG 容器实际账号不一致；PG 容器里 `psql -U <user> -d seafood_price` 验证一次 |
| `db.error: connect ECONNREFUSED` / `ETIMEDOUT` | `DB_HOST` 方式选错了：方案 A 要 PG 发布了端口，方案 B 要 `docker network connect` 且填容器名；`pg_hba.conf` 是否放行容器网段（172.16.0.0/12） |
| 采集容器 `docker compose logs fetch` 里有 `connection refused` | 同上；注意 fetch 与 web 用的是同一份 `.env`，连不上时两边都会报 |
| 改了代码页面没变 | 前端是构建产物，必须 `docker compose up -d --build`（`--build` 不能省） |
| 采集日志时间差 8 小时 / `obs_date` 差一天 | `TZ` 没设或设成 UTC；compose 默认 `Asia/Shanghai`，确认实际 `.env` 没被覆盖 |
| 想看采集历史成功/失败 | `docker compose exec fetch tail -n 50 /app/logs/fetch.log`；或查 `fetch_log` 表 |
| 改名/换机器后容器名冲突 | `docker compose down --remove-orphans` 后重起；`container_name` 是全局唯一的 |

### 裸机 systemd（第三节）

| 现象 | 排查 |
|---|---|
| 页面空白 + 顶部红条「数据加载失败」 | 服务端连不上 PG：`systemctl status seafood-web`、`journalctl -u seafood-web -n 50`、核对 `/etc/seafood-price.env` |
| API 有响应但数字为空 | `curl -s localhost:3000/api/price-data \| head -c 200`，看 `meta.total_obs`；为 0 说明采集没成功入库 |
| 采集报 403 | 数据源侧限流，隔一段时间重试；看 `logs/fetch.log` |
| 采集报 `connection refused` | 库里地址/端口不对，或 PG 未启动、`pg_hba.conf` 未放行 |
| 定时没触发 | `systemctl list-timers`；`Persistent=true` 只补跑错过的最近一次 |
