# setup-https.ps1 — 局域网 HTTPS 一键配置（mkcert 自签，A档 家庭自用）
# 用法（请在 pwsh 中运行）：
#   pwsh ./scripts/setup-https.ps1                      # 交互式选 IP + 生成证书 + 启动 dev
#   pwsh ./scripts/setup-https.ps1 -NoStart             # 只生成证书，不启动
#   pwsh ./scripts/setup-https.ps1 -IpAddress 192.168.1.100   # 跳过 IP 菜单
#   pwsh ./scripts/setup-https.ps1 -SkipInstall         # 跳过 mkcert 检查/安装
# 说明：
#   - 证书输出 certs/localhost.pem（已被 .gitignore 忽略），vite.config.ts 自动探测并启用 https
#   - IP 变更（换 Wi-Fi/DHCP）后重跑本脚本覆盖证书即可；客户端已信任的 rootCA.pem 无需重装
#   - 客户端（平板/手机）信任步骤无法自动化，见 局域网HTTPS证书分发详细教程.md §4

[CmdletBinding()]
param(
  [string]$IpAddress = '',
  [switch]$NoStart,
  [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'

# 0. 定位 demo-app 根目录（本脚本位于 scripts/ 下）
$demoRoot = Split-Path -Parent $PSScriptRoot
$certsDir = Join-Path $demoRoot 'certs'
$certFile = Join-Path $certsDir 'localhost.pem'
$keyFile  = Join-Path $certsDir 'localhost-key.pem'
$caCopy   = Join-Path $certsDir 'rootCA.pem'

Write-Host '=== Chat With Me 局域网 HTTPS 一键配置 ===' -ForegroundColor Cyan
Write-Host "项目目录: $demoRoot"

# 1. 检查/安装 mkcert（winget -> choco -> 手动指引）
if (-not $SkipInstall) {
  if (-not (Get-Command mkcert -ErrorAction SilentlyContinue)) {
    Write-Host '[1/5] 未检测到 mkcert，尝试安装...' -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
      Write-Host '  -> winget install FiloSottile.mkcert'
      winget install --id FiloSottile.mkcert -e --accept-source-agreements --accept-package-agreements
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
      Write-Host '  -> choco install mkcert'
      choco install mkcert -y
    } else {
      Write-Warning '  winget/choco 均不可用，请手动安装 mkcert：'
      Write-Host '  1) 打开 https://github.com/FiloSottile/mkcert/releases 下载 mkcert-v1.4.4-windows-amd64.exe'
      Write-Host '  2) 重命名为 mkcert.exe，放入任意已在 PATH 的目录（如 C:\Windows\System32）'
      Write-Host '  完成后重跑本脚本。'
      exit 1
    }
    # 安装后刷新 PATH 再探测（winget 可能装到新链接路径）
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not (Get-Command mkcert -ErrorAction SilentlyContinue)) {
      Write-Warning '  安装后仍未找到 mkcert（可能需要重开终端生效），请重开终端后重跑本脚本。'
      exit 1
    }
  }
  Write-Host "[1/5] mkcert 就绪: $(mkcert -version 2>&1)" -ForegroundColor Green
} else {
  Write-Host '[1/5] 跳过 mkcert 检查（-SkipInstall）'
}

# 2. 安装本地 CA（mkcert 自行触发 UAC 提权确认框，点"是"）
if (-not $SkipInstall) {
  Write-Host '[2/5] 安装本地 CA（如弹出系统确认框请点"是"）...' -ForegroundColor Yellow
  mkcert -install
  Write-Host '[2/5] 本地 CA 已安装并信任（仅本机）' -ForegroundColor Green
} else {
  Write-Host '[2/5] 跳过本地 CA 安装（-SkipInstall）'
}

# 3. 检测/选择局域网 IPv4（私网段优先排序，多网卡出菜单）
Write-Host '[3/5] 检测局域网 IPv4...' -ForegroundColor Yellow
$ips = @()
try {
  $ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
    Select-Object -ExpandProperty IPAddress -Unique)
} catch { }
if ($ips.Count -eq 0) {
  # 兜底：解析 ipconfig 输出（中英文系统均兼容）
  $ips = @((ipconfig | Select-String -Pattern 'IPv4[^\d]*([\d]{1,3}\.[\d]{1,3}\.[\d]{1,3}\.[\d]{1,3})').Matches |
    ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
}
# 私网段排前，公网/其他段靠后
$private = @($ips | Where-Object { $_ -match '^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)' })
$others  = @($ips | Where-Object { $_ -notmatch '^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)' })
$ips = @($private) + @($others)

$selectedIp = ''
if ($IpAddress) {
  $selectedIp = $IpAddress
  Write-Host "  使用参数指定 IP: $selectedIp"
} elseif ($ips.Count -eq 0) {
  Write-Warning '  未检测到局域网 IPv4，请手动输入（ipconfig 查看，如 192.168.1.100）：'
  $selectedIp = Read-Host '  IP'
} elseif ($ips.Count -eq 1) {
  $selectedIp = $ips[0]
  Write-Host "  检测到: $selectedIp"
} else {
  Write-Host '  检测到多个 IP，请选择（平板同网段的那个）：'
  for ($i = 0; $i -lt $ips.Count; $i++) { Write-Host "    [$($i+1)] $($ips[$i])" }
  $sel = Read-Host '  输入序号（默认 1）'
  if (-not $sel) { $sel = '1' }
  $selectedIp = $ips[[int]$sel - 1]
}
if ($selectedIp -notmatch '^\d{1,3}(\.\d{1,3}){3}$') {
  Write-Warning "IP 格式不合法: $selectedIp"
  exit 1
}
Write-Host "[3/5] 使用 IP: $selectedIp" -ForegroundColor Green

# 4. 签发站点证书（固定文件名，vite.config.ts 自动探测）
Write-Host "[4/5] 签发站点证书 -> certs/localhost.pem（SAN: localhost / 127.0.0.1 / ::1 / $selectedIp）..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $certsDir | Out-Null
mkcert -cert-file $certFile -key-file $keyFile localhost 127.0.0.1 ::1 $selectedIp
if (-not (Test-Path $certFile) -or -not (Test-Path $keyFile)) {
  Write-Warning '证书生成失败，请检查上方 mkcert 输出。'
  exit 1
}
Write-Host '[4/5] 站点证书已生成（有效期约 2 年）' -ForegroundColor Green

# 5. 导出待分发的 CA 公钥（只发 rootCA.pem，绝不分发任何 -key.pem）
$caroot = ((mkcert -CAROOT 2>&1) -join '').Trim()
if (Test-Path (Join-Path $caroot 'rootCA.pem')) {
  Copy-Item (Join-Path $caroot 'rootCA.pem') $caCopy -Force
  Write-Host "[5/5] rootCA.pem 已复制到 certs/（分发给平板/手机并信任，步骤见 局域网HTTPS证书分发详细教程.md §4）" -ForegroundColor Green
} else {
  Write-Warning "未找到 $caroot\rootCA.pem，请按教程 §4.1 手动导出"
}

# 汇总
Write-Host ''
Write-Host '=== 证书就绪 ===' -ForegroundColor Cyan
Write-Host '  本机访问:   https://localhost:5173'
Write-Host "  局域网访问: https://${selectedIp}:5173"
Write-Host '  验证要点:   地址栏锁图标 + 页面顶部 "🎤 Ready"（否则见教程 §5 排查）'
Write-Host '  防火墙提示: 首次启动若 Windows 防火墙弹窗，请允许 Node.js 在专用网络访问'
Write-Host '  安全要求:   保持 public/config.json 的 apiKey 为空，key 走环境变量（本脚本已自动从 .env.local 注入）'

# 6. 启动 dev（读取 .env.local 注入 VITE_ 环境变量，key 不落 config.json）
if ($NoStart) {
  Write-Host ''
  Write-Host '-NoStart 已指定，跳过启动。下次手动启动：' -ForegroundColor Yellow
  Write-Host "  cd $demoRoot; npm run dev"
  return
}

Write-Host ''
Write-Host '启动 dev server...' -ForegroundColor Yellow
$envFile = Join-Path $demoRoot '.env.local'
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    # 仅解析 VITE_ 开头的 KEY=VALUE 行；行内注释（# 之后）剔除
    if ($line -match '^VITE_([A-Z0-9_]+)=(.*)$') {
      $k = "VITE_$($Matches[1])"
      $v = ($Matches[2] -replace '\s#.*$', '').Trim()
      Set-Item -Path "env:$k" -Value $v
      Write-Host "  已注入 $k（长度 $($v.Length)）"
    }
  }
} else {
  Write-Host '  未找到 .env.local（可选；key 也可由 config.json 明文提供，但不推荐随局域网分发）'
}

Set-Location $demoRoot
npm run dev
