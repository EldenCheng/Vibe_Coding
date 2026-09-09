import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // 如需局域网 HTTPS（平板/手机访问），用 mkcert 生成证书后取消注释：
    // https: {
    //   cert: fs.readFileSync('./localhost+2.pem'),
    //   key: fs.readFileSync('./localhost+2-key.pem'),
    // },
    proxy: {
      // 本地 Gemma4 OpenAI 兼容接口，解决 CORS；前端用 /local-v1 而不是直连 172.18.0.110
      '/local-v1': {
        target: 'http://172.18.0.110:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/local-v1/, '/v1'),
      },
    },
  },
})
