"""m3u-get-down（视频）适配器。

四种下载方式与「能不能在网页端完成」的对应关系（设计文档 §3.4）：

| 方式     | 子命令   | 能否无人值守 | 说明 |
| get      | `get`    | ✅ 完全可自动化 | 需要你先从浏览器 F12 复制 m3u8 直链 |
| batch    | `batch`  | ⚠️ 可自动跑      | 每集会开「有头浏览器」，依赖页面自动出流；多候选时靠 --pick 选 |
| sniff    | `sniff`  | ❌ 需人工点播放  | 会弹出 Mac 本机浏览器窗口，网页端点不到那个窗口 |
| play     | `play`   | ❌ 需人工看着播  | 必须让视频真的播放完整段 |

一期做法：get（推荐）、batch（可全自动）、sniff 仅列候选（--no-download，用来到直链）。
sniff 的实际下载与 play 需要你在 Mac 本机终端操作，管理器只能转发日志。
"""
import re
from pathlib import Path

from .base import (Adapter, DownloadItem, LaunchPlan, STATUS_COMPLETED, STATUS_FAILED,
                   STATUS_PARTIAL, STATUS_UNVERIFIED, read_json)

# ---- 表单里 ? 图标弹出的详细说明（HTML 片段，前端用 innerHTML 渲染）----
# 这些说明较长，放进点击才出现的浮动气泡里，避免把参数表单撑高、把「开始下载」按钮挤出屏幕。

_MODE_HELP_HTML = """
<p>下拉框里的四种方式，分别对应下载器的子命令
<code>get</code> / <code>batch</code> / <code>sniff</code> / yt-dlp。</p>

<h4>① 直接下载 <code>get</code></h4>
<p><b>是什么：</b>你已经拿到 <code>.m3u8</code> 直链，下载器直接抓切片并合并成一个 mp4。</p>
<p><b>何时用：</b>在浏览器 F12 → 网络里找到了 m3u8 地址时。最可靠，不受页面反爬和浏览器影响。</p>
<p><b>触发什么：</b>只下载<b>这一个视频</b>。下面的「集数范围 / 线路 / 每集选第 N 个候选 /
每集间隔」<b>都不生效</b>；有用的是上面的 Referer / Cookie / 选流策略 / 变体序号。</p>
<p><b>例子：</b>F12 里复制到 <code>https://cdn.example.com/hls/abc/index.m3u8</code>，
粘到「地址」直接开始。</p>

<h4>② 批量下载 <code>batch</code></h4>
<p><b>是什么：</b>给它一个「番剧列表页」地址，它自动解析出每一集的链接、逐集下载，
并生成 <code>简介.md</code> 与 <code>批量进度.json</code>。</p>
<p><b>何时用：</b>要下一整季 / 一整部，且列表页能列出各集。</p>
<p><b>触发什么：</b><b>批量下载多集</b>；<b>下面的参数会生效</b>（集数范围、线路、每集候选、每集间隔）。
非内嵌播放器站点会<b>弹出有头浏览器窗口</b>逐集嗅探；内嵌播放器站点（如 mvffm）
直接解析直链、不开浏览器。重跑时已完成的集会自动跳过。</p>
<p><b>例子：</b>地址填 <code>https://www.example.com/drama/12345/</code>，
集数范围填 <code>1-12</code>，开始。</p>

<h4>③ 嗅探仅列候选 <code>sniff</code>（下拉框值 sniff_list）</h4>
<p><b>是什么：</b>不下载，只打开浏览器监听网络，把捕获到的 m3u8 候选列在日志里
（内嵌播放器站点还会标注线路名 / 集名）。实际执行的是
<code>sniff &lt;地址&gt; --no-download</code>。</p>
<p><b>何时用：</b>想先拿到直链，或不确定哪个候选才是真视频流时。</p>
<p><b>触发什么：</b>同样会<b>弹出有头浏览器窗口</b>，需要你在那个窗口里点一次播放；
它只列候选、<b>不下载</b>。拿到直链后再改用「直接下载」来下。</p>
<p><b>例子：</b>地址填播放页 <code>https://www.example.com/play/67890/</code>，
开始后等日志出现候选，复制它的 m3u8，改用「直接下载」提交。</p>

<h4>④ yt-dlp 下载 <code>sniff</code>（下拉框值 ytdlp）</h4>
<p><b>是什么：</b>给一个<b>单个视频 / 合集页</b>地址，由下载器内置的 yt-dlp 引擎自动下载，
<b>不开浏览器、不需要你点播放</b>（纯 HTTP 拉流，DASH 音视频分离后用 ffmpeg 合并）。</p>
<p><b>何时用：</b>下载 B站、YouTube 等主流站点的单个视频，又想进队列无人值守时。
之前只能自己 F12 复制 m3u8 用「直接下载」；现在直接粘视频页地址即可。</p>
<p><b>触发什么：</b>只下载 URL 指向的<b>那一个视频</b>；若地址是合集/番剧，
只会下第一个（日志会提示改用「批量下载」）。下面是常见支持站点与完整清单。</p>
<p class="tip-warn">非上述站点（yt-dlp 不支持的站）仍会走有头浏览器嗅探，
需要在桌面上手动点播放，<b>不建议</b>在管理器里用这种方式；
内嵌播放器站点（如 mvffm、ikanbot）请继续用「批量下载」。</p>

<h4>常见支持站点（yt-dlp 引擎）</h4>
<ul>
  <li><b>国内：</b>哔哩哔哩（B站，含番剧/直播/合集）、AcFun、西瓜视频、
      抖音、快手、微博、网易云音乐、QQ音乐、斗鱼、虎牙</li>
  <li><b>国际：</b>YouTube、Twitch、TikTok、Vimeo、Dailymotion、
      X/Twitter、Instagram、Facebook、Reddit、NicoNico、SoundCloud</li>
</ul>
<p>完整清单（官方，1800+ 站点，随版本增长）：
<a href="https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md"
 target="_blank" rel="noopener">supportedsites.md</a>
 ｜ 本机也可列：<code>py -m yt_dlp --list-extractors</code></p>
<p><b>清晰度：</b>默认「优先 ≤720P，没有 720P 则取能下到的最清晰」。
B站等国内站默认直连优先；YouTube 等走代理（若配置了代理）。</p>

<h4>两个常见坑（细节见帮助文件）</h4>
<ul>
  <li><b>YouTube 报 <code>Sign in to confirm you're not a bot</code>：</b>需要 cookie，
      且<u>不能</u>靠读 Edge/Chrome（新版加密读不到）——推荐装个 Firefox 后把
      <code>cookies_from_browser</code> 设为 <code>firefox</code>（已实测可行），
      或用扩展导出 <code>cookies.txt</code> 填 <code>cookies_file</code>。
      （YouTube 另需 JS 运行时 + EJS 挑战脚本，<b>下载器已默认预置</b>，不用管。）</li>
  <li><b>小红书下不了：</b>网址必须带 <code>xsec_token</code>（浏览器打开笔记后复制
      整条 URL）；App 分享的 <code>xhslink.com</code> 短链不行。</li>
</ul>
<p class="tip-warn">以上只是提醒。完整说明（含 cookies.txt 导出步骤、各站实测记录）
请看 <code>m3u-get-down/使用指南.md</code> §5.5「yt-dlp 引擎」；
配置在 <code>m3u-get-down/ytdlp_sites.json</code>。<b>以帮助文件为准。</b></p>
"""

_LINE_HELP_HTML = """
<p><b>仅「内嵌播放器」站点有效</b>（如 mvffm：播放页的 JS 里直接写着
「线路 × 剧集」的 m3u8 直链）。</p>
<p>用<b>序号或名称</b>指定<b>主线路</b>，例如 <code>1</code>、<code>22</code> 或
<code>FLV 22 推薦31</code>；其余线路会自动作为备用，某集在主线路失败时换线重试。</p>
<p><b>留空</b> = 使用默认的第 1 条线路。</p>
<p class="tip-warn">注意：它和下面的「每集选第 N 个候选」不是一回事。</p>
"""

_PICK_HELP_HTML = """
<p><b>仅对「非内嵌播放器」站点有意义</b>（需要开浏览器嗅探的那种站点）。</p>
<p>某一集在嗅探时，页面可能捕获到<b>多个 m3u8</b>（广告前贴片、不同清晰度、独立音轨、
真正的视频流……）；此参数指定自动取<b>捕获顺序里的第 N 个</b>，默认 1。</p>
<p>选错了会下到非目标流；换个数字重跑即可，已完成的集会自动跳过。</p>
<p class="tip-warn">要选「线路」请用上一项，不是这一项。</p>
"""


class M3uDownAdapter(Adapter):
    type_id = "video"
    display_name = "视频（m3u-get-down）"

    # 代理不再按敏感字段处理（与 e-download / fetech_xs 一致）：
    # 否则「已设置时留空=不修改」，UI 上无法把代理清空。原为 ["proxy"]。
    sensitive_paths = []

    # m3u_down 的顶层 import 依赖：缺任何一个，整个命令（含 --version 与「直接下载」）
    # 都无法启动，因为 cli.py 会顶层 import downloader / player_capture。
    # 这份清单同时被 start_server.command 复用，改这里就够了。
    top_level_modules = (
        ("Crypto", "pycryptodome", "AES-128 解密，downloader.py 顶层 import"),
        ("playwright", "playwright", "嗅探/播放器模式，sniffer/player_capture 顶层 import"),
    )

    form_schema = [
        {"key": "mode", "label": "下载方式", "type": "select", "default": "get",
         "options": [
             {"value": "get", "label": "直接下载 (get)：m3u8 直链 — 最可靠，推荐"},
             {"value": "batch", "label": "批量下载 (batch)：列表页整季 — 可全自动"},
             {"value": "sniff_list", "label": "嗅探仅列候选 (sniff)：只拿直链，不下载"},
             {"value": "ytdlp", "label": "yt-dlp 下载：单个视频 / 合集页 — B站、YouTube 等自动"},
         ],
         "help": "不确定选哪个？点右侧的 ? 看四种方式的区别、用法与例子",
         "help_popover": _MODE_HELP_HTML},
        {"key": "url", "label": "地址", "type": "text", "required": True,
         "placeholder": "m3u8 直链 或 播放页/列表页地址",
         "help": "get 填 m3u8 直链；batch 填番剧列表页；sniff_list 填播放页；"
                 "yt-dlp 填视频/合集页地址（B站、YouTube 等）"},
        {"key": "referer", "label": "Referer", "type": "text", "show_for": "get",
         "help": "防盗链站点需要时填写"},
        {"key": "cookie", "label": "Cookie", "type": "text", "show_for": "get",
         "help": '形如 "k=v; k2=v2"，防盗链站点需要时填写'},
        {"key": "quality", "label": "选流策略", "type": "select", "default": "best",
         "options": [{"value": "best", "label": "best（最高码率）"},
                     {"value": "worst", "label": "worst（最低码率）"}],
         "show_for": "get"},
        {"key": "variant_index", "label": "指定master变体序号", "type": "number",
         "show_for": "get", "help": "从 0 开始，填了就优先于选流策略"},
        {"key": "episodes", "label": "集数范围", "type": "text", "show_for": "batch",
         "placeholder": "1-12,15", "help": "留空=全部（会跳过选集确认）"},
        {"key": "line", "label": "线路（可选）", "type": "text", "show_for": "batch",
         "placeholder": "如 1 或 FLV 22 推薦31",
         "help_popover": _LINE_HELP_HTML},
        {"key": "pick", "label": "每集选第 N 个候选", "type": "number", "default": 1,
         "show_for": "batch",
         "help_popover": _PICK_HELP_HTML},
        {"key": "interval", "label": "每集间隔(秒)", "type": "number", "show_for": "batch",
         "help": "留空读 config.json 的 download_interval（默认 60）"},
        {"key": "auto", "label": "自动选第 N 个候选", "type": "number", "default": 1,
         "show_for": "sniff_list", "help": "非交互模式下自动选择第 N 个候选"},
        {"key": "max_wait", "label": "最长等待(秒)", "type": "number", "default": 180,
         "show_for": "sniff_list",
         "help": "需要在 Mac 弹出的浏览器窗口里点播放；等待超时会报错"},
    ]

    config_schema_data = [
        {"key": "output_dir", "label": "输出根目录", "type": "text",
         "help": "相对路径按 m3u-get-down 项目根目录解析（默认 Download）"},
        {"key": "concurrency", "label": "下载线程数", "type": "number",
         "help": "调大提速但更易触发站点限速，不建议超过 12"},
        {"key": "proxy", "label": "代理", "type": "text",
         "help": "http://127.0.0.1:10808，或 socks5://127.0.0.1:10808（socks5 需 pysocks）。"
                 "设置后 requests 与嗅探用的浏览器都会走它。留空并保存=清空该设置；"
                 "此时 requests 转而读取操作系统代理，浏览器是否走系统代理由 Chromium 自己决定"},
        {"key": "retry_times", "label": "单切片重试次数", "type": "number"},
        {"key": "retry_backoff", "label": "重试退避基数(秒)", "type": "number"},
        {"key": "timeout", "label": "读取超时(秒)", "type": "number",
         "help": "连接超时固定 15 秒"},
        {"key": "download_interval", "label": "batch每集间隔(秒)", "type": "number"},
        {"key": "ffmpeg_path", "label": "ffmpeg 路径", "type": "text",
         "help": "留空从 PATH 查找"},
        {"key": "insecure", "label": "跳过 HTTPS 证书校验", "type": "bool"},
    ]

    def config_schema(self):
        return self.config_schema_data

    def default_output_dir(self):
        return "Download"

    def output_root(self):
        """优先管理器配置；否则读 m3u 自己 config.json 的 output_dir（相对项目根解析）。"""
        raw = (self.cfg["projects"].get(self.type_id, {}) or {}).get("output_dir") or ""
        if raw.strip():
            p = Path(raw).expanduser()
            return p if p.is_absolute() else (self.project_dir / p)
        own = read_json(self.project_dir / "config.json") or {}
        value = str(own.get("output_dir") or self.default_output_dir()).strip() or "."
        p = Path(value).expanduser()
        return p if p.is_absolute() else (self.project_dir / p)

    def probe(self):
        """额外探测 ffmpeg 与 m3u 的顶层 Python 依赖。

        这里必须查全：`m3u_down` 的 cli.py 顶层就 import 了 downloader / player_capture，
        因此下面任何一个包缺失，**连 `get` 直链下载和 `--version` 都会直接失败**，
        不是等到真正下载才报错。
          · pycryptodome（Crypto）→ AES-128 解密，downloader.py 顶层 import
          · playwright            → sniffer / player_capture 顶层 import
          · pysocks               → socks5 代理支持
        ffmpeg 不是 Python 包，是合并切片用的外部命令。
        """
        import shutil

        base = super().probe()
        py = base.get("python")

        ffmpeg = shutil.which("ffmpeg")
        base["ffmpeg"] = ffmpeg
        base["ffmpeg_ok"] = bool(ffmpeg)
        if not ffmpeg:
            base["problems"].append(
                "未找到 ffmpeg（合并切片必需）：请安装并加入 PATH，"
                "或在 config.json 的 ffmpeg_path 里指定路径")

        if not py:
            base["playwright"] = False
            return base

        from ..runner import detect_module

        # 顶层 import 的包：缺任何一个都会让整个命令无法启动
        top_level = [
            ("Crypto", "pycryptodome", "AES-128 解密（downloader.py 顶层 import）"),
            ("playwright", "playwright", "嗅探/播放器模式（sniffer、player_capture 顶层 import）"),
        ]
        missing = []
        for module, package, why in top_level:
            ok, _ = detect_module(py, module)
            if not ok:
                missing.append(f"{package}（{why}）")
        ok_socks, _ = detect_module(py, "socks")
        base["pysocks"] = ok_socks

        # yt-dlp 是延迟 import（不影响其它命令），缺失时只影响 B站/YouTube 等站点
        ok_ytdlp, _ = detect_module(py, "yt_dlp")
        base["ytdlp"] = ok_ytdlp
        if not ok_ytdlp:
            base["problems"].append(
                "未安装 yt-dlp —— 只影响「yt-dlp 下载」方式（B站/YouTube 等站点）；"
                "其它下载方式不受影响。安装：py -m pip install -U yt-dlp")

        base["playwright"] = not any("playwright" in item for item in missing)
        base["pycryptodome"] = not any("pycryptodome" in item for item in missing)

        if missing:
            base["problems"].append(
                "缺少必需依赖：" + "；".join(missing)
                + "。它们是 m3u_down 的顶层依赖，缺失时连「直接下载」和 --version 都会失败。"
                + "安装：py -m pip install pycryptodome playwright"
                + "，然后 py -m playwright install chromium")
        if not ok_socks:
            base["problems"].append(
                "未安装 pysocks —— 只在用 socks5:// 代理时需要，"
                "若代理是 http:// 可忽略。安装：py -m pip install pysocks")

        base["ok"] = not base["problems"]
        return base

    # ---- 命令行 ----

    def _py(self):
        from .. import config as manager_config
        py, _ = manager_config.resolve_python(self.cfg)
        return py

    def build_launch(self, form):
        mode = form.get("mode") or "get"
        url = (form.get("url") or "").strip()
        if not url:
            raise ValueError("请填写地址")
        if not url.startswith(("http://", "https://")):
            raise ValueError("地址必须以 http(s):// 开头")

        argv = [self._py(), "-u", "-m", "m3u_down"]
        out = str(self.output_root())
        note = ""

        if mode == "get":
            argv += ["get", url]
            if form.get("referer"):
                argv += ["--referer", str(form["referer"]).strip()]
            if form.get("cookie"):
                argv += ["--cookie", str(form["cookie"]).strip()]
            if form.get("quality"):
                argv += ["--quality", str(form["quality"])]
            if form.get("variant_index") not in (None, ""):
                argv += ["--variant-index", str(int(form["variant_index"]))]
            argv += ["-o", out, "--insecure"] if self._insecure() else ["-o", out]
            note = "直链下载。若失败请检查站点是否需要 Referer / Cookie"

        elif mode == "batch":
            argv += ["batch", url, "--yes"]
            episodes = (form.get("episodes") or "").strip()
            if episodes:
                argv += ["--episodes", episodes]
            # --line：仅内嵌播放器站点有效，指定主线路（序号或名称），其余自动 failover
            line = (form.get("line") or "").strip()
            if line:
                argv += ["--line", line]
            if form.get("pick") not in (None, ""):
                argv += ["--pick", str(int(form["pick"]))]
            if form.get("interval") not in (None, ""):
                argv += ["--interval", str(int(form["interval"]))]
            argv += ["-o", out]
            note = ("每集会打开「有头浏览器」嗅探；需要屏幕上能看到窗口。"
                    "内嵌播放器站点用「线路」指定主线路（其余自动备用）；"
                    "多候选时按「每集选第 N 个候选」决定，选错可换 N 重跑")

        elif mode == "ytdlp":
            # yt-dlp 引擎：B站/YouTube 等由下载器自动路由（纯 HTTP，不用浏览器）。
            # --auto 1 必须有：管理器没有 stdin，sniff 不带 --auto 会阻塞在交互选候选；
            # yt-dlp 路径会忽略该参数（路由在嗅探前发生），无副作用。
            argv += ["sniff", url, "--auto", "1"]
            argv += ["-o", out, "--insecure"] if self._insecure() else ["-o", out]
            note = ("由 yt-dlp 引擎下载（B站/YouTube 等自动识别，纯 HTTP、不开浏览器）；"
                    "单个视频直接下，合集/番剧只会下第一个（整季请用「批量下载」）。"
                    "高清需登录 cookie（默认读 Edge，建议先退出 Edge）；"
                    "清晰度与 cookie 可在 m3u-get-down/ytdlp_sites.json 调整")

        elif mode == "sniff_list":
            argv += ["sniff", url, "--no-download"]
            if form.get("auto") not in (None, ""):
                argv += ["--auto", str(int(form["auto"]))]
            if form.get("max_wait") not in (None, ""):
                argv += ["--max-wait", str(int(form["max_wait"]))]
            note = ("仅嗅探列候选。必须在 Mac 弹出的浏览器窗口里手动点一次播放，"
                    "拿到 m3u8 直链后再用「直接下载」方式提交")

        else:
            raise ValueError(f"不支持的下载方式: {mode}")

        return LaunchPlan(argv, self.project_dir, kind="download",
                          base_dir=self.output_root(), note=note)

    def _insecure(self):
        own = read_json(self.project_dir / "config.json") or {}
        return bool(own.get("insecure"))

    def build_action(self, action, target):
        """m3u 没有 --check/--rd，失败恢复靠「重跑同一命令」自动续传。

        v0.5.1：续跑命令按产物类型分两种（URL 由 scan() 从产物目录回填，
        见 _source_url_of_dir；正常情况不会再报"缺少地址"）：
        - 列表页 URL → 统一 `batch <url> --yes`，并按 批量进度.json 顶层的
          resume_hint 带回 --line/--pick（不带回会因重探活换线触发下载器
          "线路变化→重下"，把整季已完成集全部重下）；
        - 裸 m3u8 + 本目录 progress.json 正是该直链的中断残留 →
          `get <url> -o <本目录>` 原地续传（不断片、不换目录）；
          其它裸 m3u8（如 --keep 残留、无 progress 的）走 batch 单集模式
          （v0.11.0+ 下载器支持）。
        """
        url = (target or {}).get("url")
        if not url:
            raise ValueError("缺少地址，无法续跑（请在标签页里重新提交一次）")
        if action != "resume":
            raise ValueError(f"m3u 下载器不支持 {action}（可用「续跑」代替）")
        argv = [self._py(), "-u", "-m", "m3u_down"]
        path = (target or {}).get("path") or ""
        if self._is_bare_m3u8(url) and self._single_progress_matches(path, url):
            argv += ["get", url, "-o", str(Path(path))]
        else:
            argv += ["batch", url, "--yes"]
            hint = self._resume_hint_of(path)
            if hint.get("line"):
                argv += ["--line", str(hint["line"])]
            try:
                pick = int(hint.get("pick") or 1)
            except (TypeError, ValueError):
                pick = 1
            if pick != 1:
                argv += ["--pick", str(pick)]
            argv += ["-o", str(self.output_root())]
        if self._insecure():
            argv += ["--insecure"]
        plan = LaunchPlan(argv, self.project_dir, kind="resume",
                          base_dir=self.output_root())
        plan.target_hint = (target or {}).get("name")
        return plan

    @staticmethod
    def _is_bare_m3u8(url):
        """是否为裸 m3u8 直链（去 query 按后缀判定，与下载器 is_m3u8_url 同口径）。"""
        return str(url or "").lower().split("?")[0].endswith((".m3u8", ".m3u"))

    def _resume_hint_of(self, path):
        """读产物目录 批量进度.json 顶层的 resume_hint（v0.11.0+ 下载器写入）。

        旧版进度文件没有该键 → 返回 {}（= 不补参数，与原来行为一致）。
        """
        data = read_json(Path(path) / "批量进度.json") or {}
        hint = data.get("resume_hint") or {}
        return hint if isinstance(hint, dict) else {}

    @staticmethod
    def _single_progress_matches(path, url):
        """该目录的单集 progress.json 是否正是这个直链的中断残留。

        三个条件缺一不可：progress.json 存在且有 segments 记录、
        playlist_url 与续跑 URL 一致、且目录里没有 批量进度.json
        （有批量进度的一律走 batch，那边状态更全）。
        """
        try:
            child = Path(path)
        except Exception:
            return False
        if (child / "批量进度.json").exists():
            return False
        single = read_json(child / "progress.json") or {}
        if not isinstance(single.get("segments"), dict):
            return False
        return (str(single.get("playlist_url") or "").strip() == url)

    def available_actions(self, item=None):
        return [{"action": "resume", "label": "续跑/补下",
                 "help": "重跑同一命令：已完成的集自动跳过，未完成/失败的集继续（切片级续传）"}]
    # ---- 定位与状态 ----

    # 快照里记录成品 mp4 的伪键前缀（不是路径，find_new_dirs 不会误用）
    _FILES_KEY = "@files:"

    @staticmethod
    def is_item_dir(path):
        return ((path / "批量进度.json").exists()
                # v0.5.1：单集 get/sniff 中断残留的目录（progress.json + segments，
                # 无成品 mp4）此前不可见 → 续跑按钮无处可点； now 同样列出
                or (path / "progress.json").exists()
                or any(path.glob("*.mp4")))

    def _source_url_of_dir(self, path):
        """本产物目录对应的原始入口 URL（供「续跑」重发命令）。

        优先级（v0.5.1）：
        1. 批量进度.json 顶层的 list_url（v0.11.0+ 下载器每次运行写入，最准）；
        2. 简介.md 的「来源列表页」行（旧版下载器只有这个；复用 _SOURCE_RE）；
        3. progress.json 的 playlist_url（单集 get/sniff/play 中断残留，
           且确实还有未完成切片——成功后下载器会清掉它）。
        都没有返回 ""（如已完成的散文件：无事可续跑，前端会直接提示而不调后端）。
        """
        prog = read_json(path / "批量进度.json") or {}
        url = str(prog.get("list_url") or "").strip()
        if url:
            return url
        try:
            head = (path / "简介.md").read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            head = ""
        m = self._SOURCE_RE.search(head or "")
        if m and m.group(1).strip():
            return m.group(1).strip()
        single = read_json(path / "progress.json") or {}
        segs = single.get("segments")
        if isinstance(segs, dict) and (single.get("total") or len(segs)):
            url = str(single.get("playlist_url") or "").strip()
            if url:
                return url
        return ""

    def snapshot_dirs(self):
        """父类记录输出根下的子目录名；这里额外记录成品 mp4 文件名。

        单文件产物（get / yt-dlp）是扁平的 <输出根>/<标题>.mp4，没有目录，
        仅靠目录差集定位不到，故一并快照。
        """
        snap = super().snapshot_dirs()
        root = self.output_root()
        try:
            files = sorted(f.name for f in root.glob("*.mp4") if f.is_file())
        except OSError:
            files = []
        snap[self._FILES_KEY + str(root)] = files
        return snap

    def _find_new_mp4(self, plan):
        """按 mp4 快照差集找本次新增的成品（取改动时间最新的一个）。"""
        baseline = getattr(plan, "baseline", None) or {}
        root = self.output_root()
        before = set(baseline.get(self._FILES_KEY + str(root), []))
        try:
            files = [f for f in root.glob("*.mp4") if f.is_file()]
        except OSError:
            return None
        fresh = [f for f in files if f.name not in before]
        if not fresh:
            return None
        try:
            return max(fresh, key=lambda f: f.stat().st_mtime)
        except OSError:
            return fresh[0]

    # 批量入口一定会打印这一行（batch.py 与 ytdlp_engine.py 都打印），
    # 是"产物目录在哪"最可靠的线索 —— 不依赖任务开始时的目录快照（续跑/补集时快照差集必然落空）
    _OUT_DIR_RE = re.compile(r"\[批量\]\s*已选\s*\d+\s*集，输出目录:\s*(.+?)\s*$")
    _SOURCE_RE = re.compile(r"来源列表页：\s*(\S+)")

    def locate_from_text(self, log_text):
        """从日志文本里取「[批量] 已选 N 集，输出目录: X」→ Path（路径存在才返回）。

        finalize() 拿到的是**日志字符串**（task_manager._on_exit 传 log_text），
        基类的 bus 版钩子在当前流程里根本不会被调用（`Adapter.locate_target()` 无人调用），
        所以这里直接吃文本；契约方法 locate_from_log() 复用它，避免两套实现。
        """
        for line in reversed((log_text or "").splitlines()):
            m = self._OUT_DIR_RE.search(line)
            if m:
                path = Path(m.group(1).strip())
                if path.exists():
                    return path
        return None

    def locate_from_log(self, bus=None):
        """基类钩子（bus 版）：与 locate_from_text 同一套正则。"""
        if bus is None:
            return None
        try:
            text = "\n".join(line.get("text", "") for line in bus.snapshot(tail=2000))
        except Exception:
            return None
        return self.locate_from_text(text)

    @staticmethod
    def _plan_url(plan):
        """从 argv 里取出本次任务的目标 URL（batch/sniff 都会带上）。"""
        for item in list(getattr(plan, "argv", None) or []):
            if str(item).startswith(("http://", "https://")):
                return str(item)
        return ""

    def find_by_identity(self, plan):
        """兜底定位：输出根下哪个番剧目录的 简介.md 写着本任务的列表页 URL。

        `log_text` 只取日志尾部 200KB，超长批量的那行可能被截掉；
        服务重启后重跑也可能拿不到日志 —— 这时按"产物自述的来源 URL"反查，
        与目录快照无关，续跑/补集同样有效。
        """
        url = self._plan_url(plan)
        if not url:
            return None
        try:
            children = [c for c in self.output_root().iterdir() if c.is_dir()]
        except OSError:
            return None
        for child in children:
            info = child / "简介.md"
            if not info.exists():
                continue
            try:
                head = info.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                continue
            m = self._SOURCE_RE.search(head)
            if m and m.group(1).strip() == url:
                return child
        return None

    def finalize(self, plan, exit_code, log_text=""):
        if plan and plan.kind == "resume":
            if exit_code != 0:
                return {"status": STATUS_FAILED, "message": "续跑失败，详见输出日志", "progress": {}}
            return {"status": STATUS_COMPLETED, "message": "续跑完成，详见输出日志", "progress": {}}

        # 定位产物目录：先看日志文本（最准，已存在的目录也能命中），
        # 再回落到目录快照差集 / 简介.md 反查（两者都在 detect_target_dir 里）
        target = self.locate_from_text(log_text) or self.detect_target_dir(plan)
        # sniff 仅列候选：日志里会有 [嗅探] 已选择: <url>
        m = re.search(r"\[嗅探\]\s*已选择:\s*(\S+)", log_text or "")
        if m and (plan is None or plan.kind == "download"):
            if "sniff" in " ".join(getattr(plan, "argv", []) or []):
                return {"status": STATUS_COMPLETED,
                        "message": f"已嗅探到候选直链：{m.group(1)}（可复制后用「直接下载」提交）",
                        "progress": {"direct_url": m.group(1)}}

        if target is None:
            if exit_code == 0:
                # 单文件产物（get / yt-dlp）：扁平 mp4，没有产物目录，用文件差集判定
                newbie = self._find_new_mp4(plan)
                if newbie is not None:
                    return {"status": STATUS_COMPLETED,
                            "message": f"完成：{newbie.name}",
                            "progress": {"done": 1, "total": 1, "failed": 0,
                                         "failed_items": [], "status": STATUS_COMPLETED,
                                         "unit": "个", "summary": f"成品 {newbie.name}",
                                         "kind": "single", "files": [newbie.name]},
                            "target_dir": str(newbie.parent)}
                return {"status": STATUS_UNVERIFIED,
                        "message": "进程正常结束，但未找到产物目录，无法核实结果", "progress": {}}
            if exit_code == 2:
                return {"status": STATUS_FAILED,
                        "message": "命令被拒绝或遇到真 DRM 加密（退出码 2），详见输出日志",
                        "progress": {}}
            return {"status": STATUS_FAILED, "message": f"进程异常退出（退出码 {exit_code}）",
                    "progress": {}}

        prog = self.progress_of_dir(target)
        if exit_code != 0:
            return {"status": STATUS_FAILED,
                    "message": f"进程异常退出（退出码 {exit_code}），已完成部分可「续跑」继续",
                    "progress": prog, "target_dir": str(target)}
        if prog.get("failed"):
            return {"status": STATUS_PARTIAL,
                    "message": f"完成 {prog.get('done')}/{prog.get('total')} 集，"
                               f"{prog['failed']} 集失败，可「续跑/补下」",
                    "progress": prog, "target_dir": str(target)}
        if prog.get("status") == STATUS_COMPLETED:
            return {"status": STATUS_COMPLETED,
                    "message": prog.get("summary") or "全部完成", "progress": prog,
                    "target_dir": str(target)}
        return {"status": STATUS_UNVERIFIED,
                "message": prog.get("summary") or "进程正常结束，但无法确认是否全部完成",
                "progress": prog, "target_dir": str(target)}

    # ---- 扫描 ----

    def progress_of_dir(self, path):
        """批量：读 批量进度.json；单集：看成品 mp4 与切片进度。"""
        batch = read_json(path / "批量进度.json")
        if batch and isinstance(batch.get("episodes"), dict):
            eps = batch["episodes"]
            done = sum(1 for v in eps.values() if v.get("status") == "done")
            failed = [v.get("label") or url for url, v in eps.items()
                      if v.get("status") == "failed"]
            total = len(eps)
            status = STATUS_PARTIAL if failed else (
                STATUS_COMPLETED if total and done >= total else "in_progress")
            return {
                "done": done, "total": total, "failed": len(failed),
                "failed_items": failed[:100], "status": status, "unit": "集",
                "summary": f"{done}/{total} 集完成" + (f"，{len(failed)} 集失败" if failed else ""),
                "kind": "batch", "list_url": str(batch.get("list_url") or ""),
            }

        # 单集：成品文件 + 切片进度
        mp4s = []
        try:
            mp4s = [f for f in path.glob("*.mp4") if f.is_file()]
        except OSError:
            pass
        prog = read_json(path / "progress.json")
        seg_total = seg_done = 0
        if prog and isinstance(prog.get("segments"), dict):
            seg_total = prog.get("total") or len(prog["segments"])
            seg_done = sum(1 for v in prog["segments"].values() if v.get("done"))
        if mp4s:
            return {"done": 1, "total": 1, "failed": 0, "failed_items": [],
                    "status": STATUS_COMPLETED, "unit": "个",
                    "summary": f"成品 {mp4s[0].name}",
                    "kind": "single", "files": [f.name for f in mp4s]}
        if seg_total:
            status = "in_progress"
            return {"done": seg_done, "total": seg_total, "failed": 0, "failed_items": [],
                    "status": status, "unit": "切片",
                    "summary": f"切片 {seg_done}/{seg_total}（未合并或未完成）",
                    "kind": "single",
                    "list_url": str((prog or {}).get("playlist_url") or "")}
        return {"done": None, "total": None, "failed": 0, "failed_items": [],
                "status": "unknown", "unit": "", "summary": "无进度信息", "kind": "unknown"}

    def scan(self):
        items = []
        root = self.output_root()
        if not root.exists():
            return items
        for child in sorted(root.iterdir(), key=lambda p: p.name):
            try:
                if not child.is_dir() or child.name in ("__pycache__", "design", "Design", "_work"):
                    continue
                if not self.is_item_dir(child):
                    continue
                prog = self.progress_of_dir(child)
                items.append(DownloadItem(
                    item_id=str(child.resolve()),
                    name=child.name,
                    path=child,
                    kind="视频",
                    progress=prog,
                    # v0.5.1：续跑地址从产物目录回填（此前写死 "" 导致一律
                    # "缺少地址，无法续跑"）；实在没有才留空，由前端守门提示
                    extra={"url": self._source_url_of_dir(child)},
                ))
            except OSError:
                continue
        # 也把散落在输出根目录下的成品 mp4 列出来（get 模式会扁平到这里）
        try:
            for f in root.glob("*.mp4"):
                if f.is_file():
                    items.append(DownloadItem(
                        item_id=str(f.resolve()), name=f.name, path=f, kind="视频文件",
                        progress={"done": 1, "total": 1, "failed": 0, "status": STATUS_COMPLETED,
                                  "unit": "个", "summary": "成品文件"},
                    ))
        except OSError:
            pass
        return items
