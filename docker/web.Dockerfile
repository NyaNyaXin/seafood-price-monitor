# syntax=docker/dockerfile:1
#
# Web 镜像（Nuxt 4 / Nitro node-server），包管理器 pnpm
#   构建：docker build -f docker/web.Dockerfile -t seafood-price-monitor-web .
#   产物：仅打包 .output（Nitro 已把依赖 trace 进去，运行层不需要 node_modules）
#
# 基镜像用 Debian slim 而不是 alpine：rolldown / oxc 等原生依赖在 glibc 上的
# 预编译包最全，避免 musl 缺 binary 的坑；体积差 ~50MB，换省心的首构建。
#
# ssr:false + 服务端 API 直连 PG：数据库连接参数在「运行时」由 DB_* 注入，
# 同一个镜像可在任何环境复用，换库只改 compose 的 environment，不用重新构建。

# ---------- 1. 构建层 ----------
FROM node:22-slim AS build
WORKDIR /app

# 固定 pnpm 版本（与 package.json 的 packageManager 字段一致）。
# 用 npm i -g 而不是 corepack：corepack 需要额外的签名校验/下载，偶发 keyid 报错，
# 构建镜像时没必要引入这层不确定性。
RUN npm install -g pnpm@12.10.1 --no-audit --no-fund

# 只拷清单与锁文件：源码变动不会触发重装依赖
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# --ignore-scripts：本层还没有源码，根包 postinstall（nuxt prepare）此时跑不了，
#   .nuxt 类型会在下面 nuxt build 时重新生成。
# 再单独 rebuild esbuild：它的 build 脚本负责放置平台二进制（pnpm-workspace.yaml
#   里的 allowBuilds 已放行），不能省。
RUN pnpm install --frozen-lockfile --ignore-scripts --reporter=append-only \
 && pnpm rebuild esbuild

COPY . .
RUN pnpm run build

# ---------- 2. 运行层：最小镜像 ----------
FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000 \
    NITRO_PORT=3000 \
    TZ=Asia/Shanghai

# tzdata 让日志时间与北京时间一致（slim 默认没有）；非 root 运行
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system app && useradd --system --gid app --create-home app

COPY --from=build --chown=app:app /app/.output ./.output

USER app
EXPOSE 3000

# 存活探针：只探进程（db=0），库挂了不重启容器，避免重启风暴。
# slim 镜像没有 curl/wget，直接用 node 自带的 fetch。
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||3000)+'/api/health?db=0').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", ".output/server/index.mjs"]
