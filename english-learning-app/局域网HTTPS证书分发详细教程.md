# 局域网 HTTPS 证书分发详细教程（mkcert 自签，A档家庭自用）

> **定位**：`项目设计文档.md §8.1` 的详细版。本文只解决一件事——让 `http://192.168.x.x:5173` 变成 `https://192.168.x.x:5173`，使平板/手机的 `SpeechRecognition`（`isSecureContext`）可用。**不涉及后端代理**，`Gemini/GLM Key` 仍由浏览器直连（见 `§1.3` 安全说明）。公网分享需 `B档` 后端代理，本文不覆盖。

> **前置**：本机 `http://localhost:5173` 无需任何证书即可使用麦克风；仅当需要局域网其他设备访问时才做本教程。

> **⚡ 一键脚本（v0.2.5 起，推荐）**：Windows 下服务端全部步骤（安装 mkcert → 安装 CA → 选 IP → 签发证书 → 导出 rootCA → 带 key 启动 dev）已由一条命令自动化：
>
> ```powershell
> cd C:\Users\automation\Vibe_Coding\english-learning-app\demo-app
> pwsh ./scripts/setup-https.ps1
> # 常用参数：-NoStart 只生成不启动 / -IpAddress 192.168.1.100 跳过 IP 菜单 / -SkipInstall 跳过安装检查
> ```
>
> 脚本产物：`certs/localhost.pem`（站点证书，`vite.config.ts` 自动探测启用 https）、`certs/localhost-key.pem`（站点私钥）、`certs/rootCA.pem`（待分发公钥）。均已被 `.gitignore` 忽略。
> **仍需手动**：§4 客户端信任 `rootCA.pem`（脚本无法自动化平板/手机操作）。下文 §2/§3 保留为手动方式（macOS 或想理解原理时使用）。

---

## 目录

1. [原理与安全说明](#1-原理与安全说明)
2. [本机生成证书（Windows / macOS）](#2-本机生成证书windows--macos)
3. [服务端启用 HTTPS（Vite）](#3-服务端启用-httpsvite)
4. [客户端分发与信任 rootCA.pem](#4-客户端分发与信任-rootcapem)
5. [验证与故障排查](#5-验证与故障排查)
6. [常见问题](#6-常见问题)
7. [附录](#7-附录)

---

## 1. 原理与安全说明

### 1.1 为什么需要 HTTPS

| 访问方式 | `window.isSecureContext` | `SpeechRecognition` | `getUserMedia` |
|---|---|---|---|
| `http://localhost:5173` | `true` | ✅ | ✅ |
| `http://192.168.x.x:5173` | `false` | ❌ 直接拒绝 | ❌ `NotAllowedError` |
| `https://192.168.x.x:5173`（mkcert 自签且已信任 CA） | `true` | ✅ | ✅ |

`src/speech/asrService.ts: isAvailable()` 同时检查 `window.isSecureContext`，非安全上下文直接返回 `false`，页面顶部会提示 `⚠️ Mic needs HTTPS/localhost`。

### 1.2 mkcert 做了什么

`mkcert` 会在本机创建一个**本地 CA**（根证书 `rootCA.pem` + 私钥 `rootCA-key.pem`），并用它签发 `localhost / 127.0.0.1 / 192.168.x.x` 的证书。只要客户端信任了这个 CA，浏览器就会认为自签证书是合法的。

```
本机 CA (rootCA.pem)  --签发--> localhost+2.pem (含 localhost/127.0.0.1/192.168.x.x)
     |                                |
     +-- 需分发到每台设备并信任 -------+-- Vite https 配置指向它
```

### 1.3 安全边界（A档）

* **架构**：Demo 为纯静态（`fetch('/config.json')` @ `src/config/configLoader.ts:87` + 浏览器直连 `generativelanguage.googleapis.com` @ `src/ai/geminiProvider.ts:34`），`Gemini Key` 前端可见是**有意为之**（家庭自用简化），详见 `项目设计文档.md §8.1`。
* **A档缓解**：
  - `demo-app/public/config.json` 中 `gemini.apiKey` 保持 `""`
  - 本机以环境变量启动：`$env:VITE_GEMINI_API_KEY="AIza..." ; npm run dev`（`src/config/configLoader.ts:80-84` 优先取环境变量）
  - Google AI Studio 侧给 Key 加**配额限制**与 **HTTP referrer 限制**，用完即删
* **超出 A档**：若要发公网链接给不可信用户，需 `B档` 后端代理（`浏览器→同源 /api/evaluate → Google`），key 仅存服务器，本文不展开。

---

## 2. 本机生成证书（Windows / macOS）

> **Windows 用户**：以下 §2.1–§2.4 与 §3.1 已被 `pwsh ./scripts/setup-https.ps1` 全部自动化（产物为 `certs/localhost.pem` 固定文件名），本节保留为手动方式与原理说明。

### 2.1 安装 mkcert

**Windows（推荐 Chocolatey）：**

```powershell
# 若未装 Chocolatey，先装：https://chocolatey.org/install
choco install mkcert -y
mkcert -version   # 验证，如 v1.4.x
```

**Windows（无 Chocolatey，手动下载）：**

1. 打开 https://github.com/FiloSottile/mkcert/releases 下载 `mkcert-v1.4.4-windows-amd64.exe`
2. 重命名为 `mkcert.exe`，放到 `C:\Windows\System32` 或任意已在 `PATH` 的目录
3. `mkcert -version` 验证

**macOS：**

```bash
brew install mkcert
brew install nss   # 若用 Firefox，需装 nss
mkcert -version
```

### 2.2 安装本地 CA

```powershell
mkcert -install
# 期望：Created a new local CA at "...\AppData\Local\mkcert" / The local CA is now installed in the system trust store!
```

> 会弹出系统确认框，点“是”。此 CA 仅本机信任，不影响其他机器。

查看 CA 位置：

```powershell
mkcert -CAROOT
# 例如 C:\Users\YourName\AppData\Local\mkcert
dir (mkcert -CAROOT)
# 应看到 rootCA.pem / rootCA-key.pem
```

**妥善保管 `rootCA-key.pem`**：它是 CA 私钥，泄露后他人可签发任意证书。**只分发 `rootCA.pem`（公钥），绝不分发 `-key.pem`**。

### 2.3 确认本机局域网 IP

```powershell
ipconfig
# 找 无线局域网适配器 WLAN 或 以太网适配器，IPv4 地址，如 192.168.1.100
# macOS: ifconfig | grep inet  或 ipconfig getifaddr en0
```

> 若路由器会分配变动 IP，建议在路由器中为本机绑定静态 DHCP，或生成时多写几个候选 IP（见下一步）。

### 2.4 生成站点证书

```powershell
# 在 english-learning-app/demo-app 目录下执行
cd C:\Users\automation\Vibe_Coding\english-learning-app\demo-app

# 把 192.168.1.100 换成你的实际 IP；可一次写多个 IP/域名
mkcert localhost 127.0.0.1 192.168.1.100

# 期望：Created a new certificate at ".\localhost+2.pem" etc.
dir .\localhost+*.pem
# 应看到 localhost+2.pem (证书) / localhost+2-key.pem (私钥)
```

**多 IP 写法（可选）：**

```powershell
mkcert localhost 127.0.0.1 192.168.1.100 192.168.0.100 ::1
```

> 证书默认有效期约 2 年，到期重跑 `mkcert` 即可。`localhost+2.pem` 中 `2` 表示含 3 个 SAN（localhost/127.0.0.1/IP），数字会随 SAN 数量变化，不必深究。

---

## 3. 服务端启用 HTTPS（Vite）

### 3.1 修改 vite.config.ts

**当前版本（v0.2.5 起）已改为自动探测，无需手动改配置**：`vite.config.ts` 检测到 `certs/localhost.pem` + `certs/localhost-key.pem` 存在即自动启用 https，否则维持 http（本机 localhost 用 http 也可用麦克风）：

```typescript
// demo-app/vite.config.ts（当前实现，自动探测）
import fs from 'node:fs'

const hasCerts = fs.existsSync('certs/localhost.pem') && fs.existsSync('certs/localhost-key.pem')

export default defineConfig({
  // ...
  server: {
    host: '0.0.0.0',
    port: 5173,
    ...(hasCerts ? { https: { cert: fs.readFileSync('certs/localhost.pem'), key: fs.readFileSync('certs/localhost-key.pem') } } : {}),
    // proxy ...（略，未变）
  },
})
```

<details>
<summary>旧版手动方式（v0.2.4 及之前，仅作历史参考）</summary>

```typescript
// demo-app/vite.config.ts
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import fs from 'node:fs'   // ← 需新增此行

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    https: {
      cert: fs.readFileSync('./localhost+2.pem'),
      key: fs.readFileSync('./localhost+2-key.pem'),
    },
  },
})
```

> 若证书文件名是 `localhost+3.pem`，同步改名。`fs` 为 Node 内置，无需 `npm install`。

</details>

### 3.2 启动

```powershell
# 若用环境变量注入 Key（推荐，A档安全要求）
$env:VITE_GEMINI_API_KEY="AIza...你的key..."
npm run dev -- --host 0.0.0.0

# 期望：
# VITE vX ready
# ➜  Local:   https://localhost:5173/
# ➜  Network: https://192.168.1.100:5173/
```

> 必须加 `--host 0.0.0.0`，否则局域网设备无法连入。`https` 启用后，`localhost` 也会变成 `https://localhost:5173`，本机继续可用。

### 3.3 本机自测

浏览器打开 `https://localhost:5173` 或 `https://192.168.1.100:5173`，应看到**锁图标**（无警告），页面顶部 `🎤 Ready`（而非 `⚠️ Mic needs HTTPS`）。若仍显示警告，见 §5 排查。

---

## 4. 客户端分发与信任 rootCA.pem

> **核心**：每台需要访问的设备都需信任 `rootCA.pem`，否则浏览器会显示 `NET::ERR_CERT_AUTHORITY_INVALID` 且 `isSecureContext` 仍为 `false`。

### 4.1 导出 rootCA.pem

```powershell
# 本机
$caroot = mkcert -CAROOT
explorer $caroot
# 复制 rootCA.pem 到 U盘/微信/邮件/局域网共享
# 或命令行：
Copy-Item "$caroot\rootCA.pem" -Destination ".\rootCA.pem"
```

> **只发 `rootCA.pem`**，不要发 `rootCA-key.pem`、`localhost+2-key.pem`。

### 4.2 Android（Chrome/Edge）

1. 把 `rootCA.pem` 传到手机（微信文件传输/邮件/USB）
2. **设置 → 安全 → 加密与凭据 → 从存储设备安装**（不同品牌路径略异：`设置→安全→安装证书→CA 证书`）
3. 选择 `rootCA.pem`，类型选 **CA 证书**，确认安装
4. 打开 `https://192.168.1.100:5173`，应显示锁图标；地址栏点锁图标应显示“证书有效”

> 部分 Android 需先设锁屏密码才能装 CA。卸载：同路径“受信任的凭据→用户”中移除。

### 4.3 iOS / iPadOS（Safari/Chrome）

1. 把 `rootCA.pem` 通过 **AirDrop / 邮件 / Files** 传到 iPhone/iPad
2. 点击文件 → 提示“已下载描述文件” → 去 **设置 → 已下载描述文件** → 安装 `mkcert` 根证书
3. **关键第二步**：**设置 → 通用 → 关于本机 → 证书信任设置** → 将 `mkcert` 对应的 CA **开启完全信任**（开关变绿）
4. 用 **Safari** 打开 `https://192.168.1.100:5173`（iOS Chrome 也依赖系统信任，但需 Safari 先验证）

> 若未做第 3 步，Safari 仍会报“此连接非私人连接”。信任后需重启 Safari。

### 4.4 Windows 客户端

1. 双击 `rootCA.pem` → **安装证书**
2. 存储位置选 **本地计算机**（需管理员）→ **将所有证书放入下列存储** → 浏览 → **受信任的根证书颁发机构**
3. 完成向导，重启浏览器后访问 `https://192.168.1.100:5173`

### 4.5 macOS 客户端

1. 双击 `rootCA.pem` → 钥匙串访问自动打开，选择 **系统** 钥匙串
2. 找到 `mkcert ...` 证书 → 双击 → 展开 **信任** → **使用此证书时** 选 **始终信任**
3. 重启浏览器

---

## 5. 验证与故障排查

### 5.1 验证清单

- [ ] 本机 `https://localhost:5173` 锁图标正常，`🎤 Ready`
- [ ] 本机 `https://192.168.1.100:5173` 锁图标正常
- [ ] 手机 `https://192.168.1.100:5173` 锁图标正常（无 `NET::ERR_CERT_AUTHORITY_INVALID`）
- [ ] 手机页面顶部显示 `🎤 Ready`，可正常录音（点 🎤 后浏览器会弹麦克风授权，需允许）

### 5.2 常见失败

| 现象 | 原因 | 解决 |
|---|---|---|
| `NET::ERR_CERT_AUTHORITY_INVALID` | 客户端未信任 `rootCA.pem` | 重做 §4 对应系统步骤；iOS 必须做“证书信任设置”第二步 |
| `NET::ERR_CERT_COMMON_NAME_INVALID` | 证书未包含该 IP | `mkcert` 时漏写 IP，重跑 `mkcert localhost 127.0.0.1 <正确的IP>` 并重启 Vite |
| `https://192.168.x.x` 仍显示 `⚠️ Mic needs HTTPS` | 仍是 `http` 或证书未被信任导致 `isSecureContext=false` | 确认地址栏是 `https` 且有锁；`F12→Console` 输入 `window.isSecureContext` 应为 `true` |
| `Vite error: ENOENT localhost+2.pem` | 旧版手动配置路径与文件名不匹配 | v0.2.5 起为自动探测 `certs/localhost.pem`，重跑 `pwsh ./scripts/setup-https.ps1` 即可 |
| 手机能开页面但点 🎤 无反应 | 未授权麦克风 | 首次点 🎤 时允许“麦克风”权限；`设置→隐私→麦克风` 检查 |
| `Gemini error 404 / model not found` | 模型名不对 | `public/config.json: gemini.textModel` 确认为 `gemini-3.6-flash`（`fallbackModel: gemini-3.5-flash`），见 `项目设计文档.md §7` |
| 证书过期 | mkcert 默认 ~2 年 | 重跑 `mkcert localhost ...` 覆盖旧文件，重启 Vite，客户端无需重装 CA（CA 未过期） |

### 5.3 快速自检命令

```powershell
# 本机
mkcert -CAROOT
dir .\localhost+*.pem
# 浏览器控制台
window.isSecureContext  # 期望 true
# 检查证书 SAN
openssl x509 -in localhost+2.pem -text -noout | Select-String -Pattern "DNS|IP Address"
```

---

## 6. 常见问题

**Q: 能否不分发 CA，用 `vite --host` 的 http 凑合？**
A: 不能。`http://192.168.x.x` 的 `isSecureContext` 恒为 `false`，`SpeechRecognition` 会被浏览器直接拒绝，`src/speech/asrService.ts: isAvailable()` 返回 `false`。

**Q: 能否用 `ngrok / frp` 内网穿透代替 mkcert？**
A: 可以，但会引入外网依赖与延迟，且 `Gemma4 (172.18.0.110)` 仍需内网穿透。`mkcert` 是局域网零依赖方案，适合 A档。

**Q: 证书分发后，其他人能用我的 Gemini Key 吗？**
A: Key 不在证书里。只要你按 §1.3 保持 `public/config.json: gemini.apiKey=""` 并用环境变量启动，局域网其他设备**不会**从 `config.json` 拿到你的 Key。但他们仍可通过浏览器 `Network` 面板看到**自己**请求 Gemini 时的 `?key=`（若他们用你的 Key 启动），故建议用配额/referrer 限制并定期轮换。

**Q: 换了 Wi-Fi / IP 变了怎么办？**
A: 重跑 `mkcert localhost 127.0.0.1 <新IP>` 覆盖证书，重启 Vite。客户端 CA 无需重装。

---

## 7. 附录

### 7.1 文件清单

```
demo-app/
├── certs/
│   ├── localhost.pem       ← 站点证书（一键脚本产物；已被 .gitignore 忽略，勿提交）
│   ├── localhost-key.pem   ← 站点私钥（绝不提交）
│   └── rootCA.pem          ← 脚本自动复制的待分发 CA 公钥（不提交，可分发）
└── vite.config.ts          ← 自动探测 certs/localhost.pem，无需手动改

mkcert -CAROOT/
├── rootCA.pem              ← 需分发到每台设备的 CA 公钥
└── rootCA-key.pem          ← CA 私钥（绝不分发）

# 旧版（v0.2.4 及之前手动方式，文件在 demo-app 根目录）：
# ├── localhost+2.pem       ← 站点证书
# └── localhost+2-key.pem   ← 站点私钥
```

### 7.2 .gitignore 建议

已在 `demo-app/.gitignore` 落地（v0.2.5）：

```
# mkcert 证书（A档本地使用，含站点私钥与 rootCA.pem，绝不进仓库）
certs/
```

### 7.3 参考

* mkcert 官方：https://github.com/FiloSottile/mkcert
* 设计概略：`../项目设计文档.md §8.1`
* 运行教程局域网章节：`./运行教程.md §7`

---

*最后更新：2026-09-15（v0.2.5 新增一键脚本 `scripts/setup-https.ps1`，§3.1 改自动探测，§7 文件清单/gitignore 同步），与 `项目设计文档.md §8.1` 同步。*
