# Chat With Me — Demo App

最小可跑闭环 Demo：单固定场景（`Scene01` 集市）+ 随机 1 道 Level1 问题 → TTS 读题 → STT 录音→可编辑→发大模型识图评分（图片+问题+回答）→ 展示总分+短评（英文+中文翻译切换）+ 等待水果掉落小游戏。

> **新环境？请直接看 [`运行教程.md`](./运行教程.md) —— 含环境要求、Key 获取、HTTPS、常见问题的逐步教程。**

## 快速开始
```bash
cd english-learning-app/demo-app
npm install
# 1) 配置 Gemini Key（二选一）
# 方式 A: 环境变量（推荐，不提交到仓库）
# PowerShell:
$env:VITE_GEMINI_API_KEY="你的key"; npm run dev
# 方式 B: 直接填到 public/config.json 的 gemini.apiKey

# 2) 启动（http://localhost:5173）
npm run dev
# 局域网平板访问需 HTTPS，见 vite.config.ts 的 mkcert 注释；本机用 http://localhost:5173 即可
```

## 配置
`public/config.json`：
- `aiProvider`: `gemini` | `local`
- `gemini.textModel`: 默认 `gemini-3.6-flash`，失败回落 `gemini-3.5-flash`（2.0/2.5 Flash 已于 2026 年对新用户停服，实测 404 提示用 3.6）
- `local.baseURL`: `/local-v1`（Vite proxy 到 `http://172.18.0.110:8080/v1`），`directBaseURL` 为直连地址
- `demo.evaluationTimeoutMs`: Gemini 超时 15s；`demo.localEvaluationTimeoutMs`: Local 超时 40s（至少 40s，代码兜底 `Math.max(...,40000)`）
- `tts` / `asr`：`lang: en-US`, `rate:0.9, pitch:1.0`
- 页面右上角可实时切换 `Gemini ↔ Local Gemma4`，无需重启

## 目录
- `public/scenes/scene01/` — 场景资源（由 `../Demo/Scene01_*` 转换）
- `src/config/configLoader.ts` — 加载校验
- `src/speech/` — TTS/ASR 封装
- `src/ai/` — Gemini / Local 双 Provider
- `src/demo/useDemoSession.ts` — 5 状态状态机
- `src/components/` — 展示/问答/等待/结果

## 常见问题
- **麦克风不可用**：ASR 要求 `HTTPS` 或 `http://localhost`，局域网 `http://192.168.x.x` 会被浏览器拒绝；用 `mkcert` 自签证书或只用 `localhost` 测试
- **Gemini 报错 404/model not found**：`2.0/2.5 Flash` 已对新用户停服，实测提示改用 `gemini-3.6-flash`；已在配置中改为 `3.6-flash`→`3.5-flash` 自动回落
- **本地 Gemma4 CORS**：已通过 `vite.config.ts` 的 `/local-v1` proxy 解决；不要直接请求 `172.18.0.110`
- **本地超时**：Local 已单独设 40s（Gemini 仍 15s），等待页会显示 `~30–40s` 提示

## 构建
```bash
npm run build && npm run preview
```
