import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import fs from 'node:fs'

// 局域网 HTTPS 自动探测：运行 scripts/setup-https.ps1 生成 certs/localhost.pem 后，
// 重启 npm run dev 即自动启用 https；删除 certs/ 目录即回到 http（本机 localhost 用 http 也可用麦克风）
const hasCerts = fs.existsSync('certs/localhost.pem') && fs.existsSync('certs/localhost-key.pem')

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    ...(hasCerts
      ? {
          https: {
            cert: fs.readFileSync('certs/localhost.pem'),
            key: fs.readFileSync('certs/localhost-key.pem'),
          },
        }
      : {}),
    proxy: {
      // 本地 Gemma4 OpenAI 兼容接口，解决 CORS；前端用 /local-v1 而不是直连 172.18.0.110
      // 批量 150s 超时，需显式放大代理超时，否则 Vite 默认 60-120s 会先于模型返回而 504
      '/local-v1': {
        target: 'http://172.18.0.110:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/local-v1/, '/v1'),
        timeout: 380000,
        proxyTimeout: 380000,
      },
      // 火山方舟 Ark OpenAI 兼容接口（GLM 5.3 Flash），解决浏览器直连 CORS
      // 前端用 /glm-v1/chat/completions，代理转发到 token plan 专属端点
      // https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions（标准 API 为 /api/v3）
      '/glm-v1': {
        target: 'https://ark.cn-beijing.volces.com',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/glm-v1/, '/api/coding/v3'),
        timeout: 380000,
        proxyTimeout: 380000,
      },
    },
  },
})
