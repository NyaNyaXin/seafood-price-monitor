// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-01-01',
  devtools: { enabled: true },

  // 监听 0.0.0.0：让同一局域网内的手机/其他电脑能直接访问看板
  // （默认 localhost 只绑 ::1，外部连不上）
  devServer: {
    host: '0.0.0.0',
    port: 3000,
  },

  // Reka UI 官方 Nuxt module：自动导入全部组件（reka-ui/nuxt）
  modules: ['reka-ui/nuxt'],

  // 看板数据由 Nitro 服务端直接查 PostgreSQL（server/api/price-data.get.ts），
  // 前端纯客户端渲染，避免 ECharts 等浏览器 API 在 SSR 阶段报错
  ssr: false,

  // 数据库连接（服务端私用，不会下发到前端）
  // 生产环境（Linux）用环境变量覆盖：NUXT_DB_HOST / NUXT_DB_PORT / NUXT_DB_USER /
  // NUXT_DB_PASSWORD / NUXT_DB_NAME
  runtimeConfig: {
    dbHost: '127.0.0.1',
    dbPort: '5432',
    dbUser: 'postgres',
    dbPassword: '',
    dbName: 'seafood_price',
    dbPoolMax: '5',
    dbConnectTimeout: '8000',
  },

  app: {
    head: {
      titleTemplate: '%s · 潮汐 TIDE',
      htmlAttrs: { lang: 'zh-CN' },
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'description', content: '沈阳冷冻水产批发行情日报 · 全国水产技术推广总站官方数据' },
      ],
      link: [
        { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
        { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' },
        {
          rel: 'stylesheet',
          href: 'https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;600;700;800&display=swap',
        },
      ],
    },
  },

  css: ['~/assets/css/main.css'],
})
