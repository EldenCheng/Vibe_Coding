// ==UserScript==
// @name         发送到下载管理器
// @namespace    dsh.download-manager
// @version      1.0.2
// @description  在网页上把任务直接交给本机「统一下载管理器」（电子书 / E-Hentai / 视频），自动入队并开始下载
// @author       dsh
// ★ 新增站点时别忘了这里：把域名加进下面的 @match（"总表"在脚本里的 SITES）。
//   @match 只能在文件头部静态声明、运行时无法生成，所以这一处需要手动同步；
//   userscript/test_core.mjs 会检查 @match 与 SITES 是否一致，漏加会测试失败。
// @match        *://*.e-hentai.org/*
// @match        *://e-hentai.org/*
// @match        *://*.exhentai.org/*
// @match        *://exhentai.org/*
// @match        *://*.als1004.space/*
// @match        *://*.eacg.net/*
// @match        *://*.ikanbot.com/*
// @match        *://*.javdock.com/*
// @match        *://*.mvffm.net/*
// @match        *://*.movieffm.net/*
// @match        *://*.youknow.tv/*
// @match        *://*.bilibili.com/*
// @match        *://*.acg.tv/*
// @match        *://b23.tv/*
// @match        *://*.youtube.com/*
// @match        *://youtu.be/*
// 想在别的网站也能用：取消下面这行的注释（或在 Tampermonkey 的「设置 → 用户匹配」里加自己的规则）。
// 代价是油猴图标在任何页面都会显示脚本数字。
// @match        *://*/*
// @grant        GM_xmlhttpRequest
// @grant        GM_registerMenuCommand
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-idle
// @noframes
// ==/UserScript==

/**
 * 发送到下载管理器（download-manager v0.4.3 配套脚本）
 *
 * 设计见《download-manager/Design/项目设计文档.md》§23，要点：
 * - 入口用油猴**原生菜单**，不做页面常驻悬浮球；
 * - 只用管理器**现有**接口（POST /api/tasks、GET /api/tasks、GET /api/health），后端零改动；
 * - 必须用 GM_xmlhttpRequest：管理器没有 CORS 头，页面里 fetch 会被浏览器拦掉；
 * - 令牌存 GM_setValue，填一次长期有效；
 * - batch 的集数用「快捷芯片 + 文本框」（同一个控件，选与填不分家），
 *   线路/候选由脚本按站点类型自动切换（内嵌播放器站点才有"线路"的概念）；
 * - 提交只提示"已加入"，不轮询进度、不自动打开管理器页面。
 *
 * 维护站点（v1.0.2 起）：支持站点集中在脚本里的 **SITES 单表**，`PRESETS` / `EMBEDDED_SITES` /
 * `CAUTION_SITES` 全由它派生。加站点时改 1 行 + 补文件顶部 `@match`（测试会检查两者一致）；
 * 详见 userscript/使用说明.md 第 5 节。
 */
(function () {
  'use strict';

  const VERSION = '1.0.2';
  const DEFAULT_BASE = 'http://127.0.0.1:8765';   // 管理器默认监听地址
  const KEY_BASE = 'dm_base_url';
  const KEY_TOKEN = 'dm_token';

  // ---------------------------------------------------------------- 站点表

  // ★ 支持站点总表：想加站点，大多数情况只需要在这里加/改一行。
  //
  // 每行 = 一组域名 + 预选的下载器/方式，并标注两件"面板要不要特殊处理"的事：
  //   hosts    : 域名后缀数组（匹配该域本身及其子域），如 'mvffm.net' 能匹配 www.mvffm.net
  //   type     : ebook | ehentai | video
  //   mode     : '' | 'get' | 'batch' | 'ytdlp'（仅 video 有意义）
  //   label    : 面板上显示的预选名
  //   embedded : 仅 video+batch 有意义。true = 播放页 JS 里直接写着"线路×剧集"直链
  //              → 面板显示「线路」；省略/false = 需嗅探 → 面板显示「每集候选」。
  //   caution  : 可选。下载器明确拒绝/有坑的站点，面板顶部给一行警示（仍允许提交）。
  //
  // 新增站点的完整步骤（详见 userscript/使用说明.md 第 5 节）：
  //   ① 本表加一行（或改某行的 hosts/mode/embedded）；
  //   ② 把域名补进**文件顶部**的 @match —— 这步必须手动，@match 在运行时无法生成；
  //   ③ 视频站通常还要在 m3u-get-down/sites/ 加一个 <站名>.json（那是给下载器解析用的，
  //      与本脚本无关；不加以后的站点 html 结构一变就解析不了）。
  const SITES = [
    { hosts: ['e-hentai.org', 'exhentai.org'], type: 'ehentai', mode: '', label: 'E-Hentai 画廊' },
    { hosts: ['als1004.space'], type: 'ebook', mode: '', label: '电子书' },
    { hosts: ['bilibili.com', 'b23.tv', 'acg.tv', 'youtube.com', 'youtu.be'],
      type: 'video', mode: 'ytdlp', label: '视频 · yt-dlp' },
    { hosts: ['eacg.net'], type: 'video', mode: 'batch', label: '视频 · 批量' },
    { hosts: ['ikanbot.com'], type: 'video', mode: 'batch', label: '视频 · 批量', embedded: true },
    { hosts: ['javdock.com'], type: 'video', mode: 'batch', label: '视频 · 批量',
      caution: '该站视频是滑动窗口 HLS 防下载（清单只暴露最近几秒切片），下载器会拒绝执行。' },
    { hosts: ['mvffm.net', 'movieffm.net'], type: 'video', mode: 'batch', label: '视频 · 批量', embedded: true },
    { hosts: ['youknow.tv'], type: 'video', mode: 'batch', label: '视频 · 批量' },
  ];

  /** 把域名后缀数组编译成匹配 host 本身/子域的正则（转义点号，其余原样）。 */
  function hostsToRe(hosts) {
    const alt = hosts.map((h) => String(h).replace(/\./g, '\\.')).join('|');
    return new RegExp('(^|\\.)(' + alt + ')$', 'i');
  }

  // 下面三个都由 SITES 派生，脚本别处照旧用它们（不要再单独维护）。
  const PRESETS = SITES.map((s) => ({
    re: hostsToRe(s.hosts), type: s.type, mode: s.mode, label: s.label,
  }));
  // 内嵌播放器站点：batch 的「线路」有效；其它站点「每集候选」有效（两者互斥）。
  const EMBEDDED_SITES = SITES.filter((s) => s.embedded).map((s) => hostsToRe(s.hosts));
  const CAUTION_SITES = SITES.filter((s) => s.caution)
    .map((s) => [hostsToRe(s.hosts), s.caution]);

  // ---------------------------------------------------------------- 纯函数（可被 Node 测试直接调用）

  /** 取主机名；非法 URL 返回空串。 */
  function siteHost(href) {
    try { return new URL(href, 'http://localhost').hostname; } catch (e) { return ''; }
  }

  /** 按当前页地址预选 {type, mode, label}。 */
  function domainPreset(href) {
    if (/\.m3u8?(\?|#|$)/i.test(href || '')) {
      return { type: 'video', mode: 'get', label: '视频 · m3u8 直链' };
    }
    const host = siteHost(href);
    for (const p of PRESETS) {
      if (p.re.test(host)) return { type: p.type, mode: p.mode, label: p.label };
    }
    return { type: 'video', mode: 'batch', label: '视频 · 批量（默认）' };
  }

  function isEmbeddedSite(href) {
    const host = siteHost(href);
    return EMBEDDED_SITES.some((re) => re.test(host));
  }

  function cautionFor(href) {
    const host = siteHost(href);
    for (const [re, text] of CAUTION_SITES) if (re.test(host)) return text;
    return '';
  }

  /**
   * 当前「下载器 + 方式 + 地址」下哪些字段生效 —— 面板显隐与提交取值共用这一份判断，
   * 避免两处各写一套导致"隐藏了却还在提交/显示了却收不到值"。
   *
   * 关键区分：`--line`（选线路）只对**内嵌播放器站点**有效，`--pick`（每集取第 N 个候选）
   * 只对需要嗅探的站点有效，两者互斥；而**每集间隔对所有 batch 站点都有效**。
   */
  function fieldPlan(type, mode, url) {
    const isVideo = type === 'video';
    const isBatch = isVideo && mode === 'batch';
    const embedded = isBatch && isEmbeddedSite(url);
    return {
      type: type, mode: mode, isVideo: isVideo, isBatch: isBatch, embedded: embedded,
      showGet: isVideo && mode === 'get',
      showRange: type === 'ehentai',
      showEpisodes: isBatch,
      showLine: embedded,                 // 内嵌站点：显示线路下拉
      showPick: isBatch && !embedded,     // 需嗅探的站点：显示每集候选
      showInterval: isBatch,              // 两种站点都能设每集间隔
    };
  }

  // 集数/页码范围：空串=全部；否则 "1"、"1-12"、"1-12,15"、"1-12, 15" 之类。
  // 除格式外还校验语义（页码 1 基、区间左端 ≤ 右端），免得把明显错的输入送给下载器。
  const SPEC_RE = /^\d+(\s*-\s*\d+)?(\s*,\s*\d+(\s*-\s*\d+)?)*$/;

  function isValidSpec(spec) {
    const s = String(spec == null ? '' : spec).trim();
    if (s === '') return true;
    if (!SPEC_RE.test(s)) return false;
    for (const part of s.split(',')) {
      const nums = part.split('-').map((x) => Number(x.trim()));
      if (nums[0] < 1) return false;
      if (nums.length > 1 && nums[1] < nums[0]) return false;
    }
    return true;
  }

  // 管理器任务状态 → 中文（管理器返回的是英文枚举，别把英文直接甩给用户）
  const STATUS_LABELS = {
    queued: '排队中', running: '运行中', completed: '已完成',
    partial_failed: '部分失败', completed_unverified: '已完成(未核实)',
    failed: '失败', stopped: '已停止', crashed: '异常中断',
    interrupted: '服务重启中断', unknown: '状态未知',
  };

  /** 任务状态文案；排队中会带上队列位置（有的话）。 */
  function statusLabel(task) {
    const s = (task && task.status) || '';
    const label = STATUS_LABELS[s] || s || '已加入';
    const pos = task && task.queue_position;
    return (s === 'queued' && pos) ? label + '（第 ' + pos + ' 位）' : label;
  }

  /**
   * 面板状态 → 管理器 POST /api/tasks 的请求体。
   * 键必须与后端各 adapter 的 form_schema 对齐：
   *   ebook   → {book}
   *   ehentai → {url, range?}
   *   video   → {mode, url, episodes?/line?/pick?/interval?} 或 {mode, url, referer?/cookie?}
   * 校验不通过直接抛错（面板把 message 显示给用户）。
   */
  function buildTaskPayload(state) {
    const s = state || {};
    const type = s.type || 'video';
    const url = String(s.url || '').trim();
    if (!url) throw new Error('请填写地址');
    if (!/^https?:\/\//i.test(url)) throw new Error('地址必须以 http(s):// 开头');

    const form = {};
    if (type === 'ebook') {
      form.book = url;
    } else if (type === 'ehentai') {
      if (!/https?:\/\/[^/]+\/g\/(\d+)\/([0-9a-fA-F]+)/.test(url)) {
        throw new Error('画廊 URL 格式不对，应为 https://e-hentai.org/g/<编号>/<token>/');
      }
      form.url = url;
      const range = String(s.range || '').trim();
      if (range) {
        if (!isValidSpec(range)) throw new Error('页码范围格式不对，例：1-10,20,30-40');
        form.range = range;
      }
    } else if (type === 'video') {
      const mode = s.mode || 'batch';
      form.mode = mode;
      form.url = url;
      if (mode === 'batch') {
        const spec = String(s.episodes || '').trim();
        if (spec) {
          if (!isValidSpec(spec)) throw new Error('集数范围格式不对，例：1-12,15（留空=全部）');
          form.episodes = spec;
        }
        const line = String(s.line || '').trim();
        if (line) form.line = line;     // 仅内嵌播放器站点有效
        if (s.pick !== undefined && String(s.pick).trim() !== '') {
          const n = Number(s.pick);
          if (!Number.isInteger(n) || n < 1) throw new Error('「每集选第 N 个候选」要填 ≥1 的整数');
          form.pick = n;
        }
        if (s.interval !== undefined && String(s.interval).trim() !== '') {
          const iv = Number(s.interval);
          if (!Number.isInteger(iv) || iv < 0) throw new Error('「每集间隔」要填 ≥0 的整数秒');
          form.interval = iv;
        }
      } else if (mode === 'get') {
        const referer = String(s.referer || '').trim();
        const cookie = String(s.cookie || '').trim();
        if (referer) form.referer = referer;
        if (cookie) form.cookie = cookie;
      } else if (mode !== 'ytdlp') {
        throw new Error('不支持的方式: ' + mode);
      }
    } else {
      throw new Error('未知下载器: ' + type);
    }
    return { type: type, kind: 'download', form: form };
  }

  // ---------------------------------------------------------------- 设置读写

  const store = {
    get(key, dft) {
      try {
        if (typeof GM_getValue === 'function') return GM_getValue(key, dft);
        const v = localStorage.getItem(key);
        return v === null ? dft : v;
      } catch (e) { return dft; }
    },
    set(key, val) {
      try {
        if (typeof GM_setValue === 'function') GM_setValue(key, val);
        else localStorage.setItem(key, val);
      } catch (e) { /* 存不上也不影响本次使用 */ }
    },
  };

  const getBase = () => String(store.get(KEY_BASE, '') || DEFAULT_BASE).replace(/\/+$/, '');
  const getToken = () => String(store.get(KEY_TOKEN, '') || '');

  // ---------------------------------------------------------------- 网络

  /** GM_xmlhttpRequest 的 Promise 包装：{status, body}；网络层错误抛异常。 */
  function gmFetch(method, path, data) {
    const base = getBase();
    const token = getToken();
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: method,
        url: base + path,
        headers: Object.assign({ 'Content-Type': 'application/json' },
                               token ? { 'X-Auth-Token': token } : {}),
        data: data === undefined ? undefined : JSON.stringify(data),
        timeout: 20000,
        onload(res) {
          let body = {};
          try { body = JSON.parse(res.responseText || '{}'); } catch (e) { body = {}; }
          resolve({ status: res.status, body: body });
        },
        ontimeout() { reject(new Error('请求超时：管理器没有响应')); },
        onerror() {
          reject(new Error('连不上管理器（' + base + '）——请确认它已启动（start_server.bat），'
                           + '或在本脚本的「管理器设置」里改地址'));
        },
      });
    });
  }

  /** 提交任务；返回 task 对象。 */
  async function createTask(payload) {
    const res = await gmFetch('POST', '/api/tasks', payload);
    if (res.status === 401) {
      const err = new Error('令牌无效或缺失，请在「管理器设置」里填写');
      err.code = 'unauthorized';
      throw err;
    }
    if (res.status >= 400) {
      const msg = (res.body && res.body.error && res.body.error.message) || ('提交失败（HTTP ' + res.status + '）');
      throw new Error(msg);
    }
    return (res.body && res.body.task) || {};
  }

  /** 测试连通 + 令牌：GET /api/tasks（只读、要鉴权）。返回值形如 "已连接（3 个任务）"。 */
  async function testConnection() {
    const health = await gmFetch('GET', '/api/health');
    if (health.status !== 200) throw new Error('管理器响应异常（HTTP ' + health.status + '）');
    const res = await gmFetch('GET', '/api/tasks');
    if (res.status === 401) throw new Error('能连上，但令牌不对');
    if (res.status >= 400) throw new Error('能连上，但读取任务列表失败（HTTP ' + res.status + '）');
    const n = (res.body && res.body.tasks && res.body.tasks.length) || 0;
    return '连接正常，令牌有效（当前 ' + n + ' 个任务）';
  }

  // ---------------------------------------------------------------- 面板 UI

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
    .mask { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 2147483647;
            display: flex; align-items: flex-start; justify-content: center; padding: 6vh 16px 16px;
            font: 13px/1.5 "Microsoft YaHei", system-ui, sans-serif; color: #e8eaed; }
    .panel { width: 460px; max-width: 100%; max-height: 88vh; overflow: auto;
             background: #23262b; border: 1px solid #3a3f47; border-radius: 10px;
             box-shadow: 0 12px 40px rgba(0,0,0,.5); }
    header { display: flex; align-items: center; gap: 8px; padding: 10px 14px;
             border-bottom: 1px solid #3a3f47; font-weight: 600; }
    header .ver { color: #8b939e; font-weight: 400; font-size: 11px; margin-left: auto; }
    header button { background: none; border: 0; color: #b9c0c9; font-size: 20px; cursor: pointer;
                    line-height: 1; padding: 0 4px; }
    header button:hover { color: #fff; }
    .body { padding: 12px 14px; }
    .row { display: flex; align-items: center; gap: 10px; margin-bottom: 9px; }
    .row > label { flex: 0 0 96px; color: #a9b1bb; }
    .col { margin-bottom: 9px; }
    .col > label { display: block; color: #a9b1bb; margin-bottom: 5px; }
    input[type=text], input[type=password], input[type=number], select {
      flex: 1 1 auto; width: 100%; background: #1a1c20; color: #e8eaed;
      border: 1px solid #3a3f47; border-radius: 6px; padding: 6px 8px; font: inherit; }
    input:focus, select:focus { outline: none; border-color: #4c8dff; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
    .chips button { background: #2c3138; color: #cfd5dc; border: 1px solid #3a3f47;
                    border-radius: 999px; padding: 3px 10px; cursor: pointer; font: inherit; }
    .chips button:hover { border-color: #4c8dff; color: #fff; }
    .hint { color: #8b939e; font-size: 12px; margin: 2px 0 0; }
    .warn { color: #ffd479; font-size: 12px; margin: 4px 0 0; }
    .result { margin-top: 10px; padding: 8px 10px; border-radius: 6px; font-size: 12px; word-break: break-all; }
    .result.ok { background: #1d3a26; border: 1px solid #2e6b3f; color: #b7f0c6; }
    .result.bad { background: #3d2126; border: 1px solid #7a3541; color: #ffc4cc; }
    .result a { color: #9ecbff; }
    footer { display: flex; align-items: center; gap: 10px; padding: 10px 14px;
             border-top: 1px solid #3a3f47; }
    footer .spacer { flex: 1 1 auto; }
    button.primary { background: #2f6fd0; color: #fff; border: 0; border-radius: 6px;
                     padding: 7px 16px; cursor: pointer; font: inherit; font-weight: 600; }
    button.primary:hover { background: #3b7de0; }
    button.primary:disabled { background: #39414b; color: #8b939e; cursor: default; }
    button.ghost { background: #2c3138; color: #cfd5dc; border: 1px solid #3a3f47;
                   border-radius: 6px; padding: 6px 12px; cursor: pointer; font: inherit; }
    button.ghost:hover { border-color: #4c8dff; color: #fff; }
    button.link { background: none; border: 0; color: #9ecbff; cursor: pointer; font: inherit;
                  padding: 0; text-decoration: underline; }
  `;

  const HTML = `
    <div class="mask">
      <div class="panel">
        <header>
          <span>发送到下载管理器</span>
          <span class="ver">v${VERSION}</span>
          <button id="close" title="关闭（Esc）">×</button>
        </header>
        <div class="body">
          <div id="view-task">
            <div class="row"><label>下载器</label>
              <select id="type">
                <option value="ebook">电子书（fetech_xs）</option>
                <option value="ehentai">E-Hentai 画廊</option>
                <option value="video">视频（m3u-get-down）</option>
              </select></div>
            <div class="row" data-show="video"><label>方式</label>
              <select id="mode">
                <option value="batch">批量下载 batch：列表页整季</option>
                <option value="ytdlp">yt-dlp：单个视频 / 合集页</option>
                <option value="get">直接下载 get：m3u8 直链</option>
              </select></div>
            <div class="row"><label id="url-label">地址</label>
              <input id="url" type="text" spellcheck="false"
                     placeholder="https://..."></div>

            <div class="row" data-show="video:get"><label>Referer</label>
              <input id="referer" type="text" spellcheck="false" placeholder="防盗链站点需要时填"></div>
            <div class="row" data-show="video:get"><label>Cookie</label>
              <input id="cookie" type="text" spellcheck="false" placeholder='如 "k=v; k2=v2"'></div>

            <div class="row" data-show="ehentai"><label>页码范围</label>
              <input id="range" type="text" spellcheck="false"
                     placeholder="留空=全部，如 1-10,20,30-40"></div>

            <div class="col" data-show="batch-line-pick">
              <label>集数范围</label>
              <div class="chips">
                <button data-spec="">全部</button>
                <button data-spec="1-6">1-6</button>
                <button data-spec="1-12">1-12</button>
                <button data-spec="1-24">1-24</button>
              </div>
              <input id="episodes" type="text" spellcheck="false"
                     placeholder="留空=全部集；也可以自己写，如 1-12,15">
            </div>
            <div class="row" data-show="batch-line"><label>线路</label>
              <select id="line-sel">
                <option value="">自动（探活第一条存活线路）</option>
                <option value="__custom">自定义…</option>
              </select></div>
            <div class="row" data-show="batch-line-custom"><label></label>
              <input id="line" type="text" spellcheck="false"
                     placeholder="线路序号或名字，如 22 或 FLV 22 推薦31"></div>
            <div class="row" data-show="batch-pick"><label>每集候选</label>
              <input id="pick" type="number" min="1" value="1">
              </div>
            <div class="row" data-show="batch-interval"><label>每集间隔(秒)</label>
              <input id="interval" type="number" min="0" placeholder="留空用 config 里的值"></div>
            <div class="warn" id="warn" hidden></div>
          </div>

          <div id="view-settings" hidden>
            <div class="row"><label>管理器地址</label>
              <input id="set-base" type="text" spellcheck="false" placeholder="http://127.0.0.1:8765"></div>
            <div class="row"><label>访问令牌</label>
              <input id="set-token" type="password" spellcheck="false" placeholder="粘贴访问令牌"></div>
            <p class="hint">令牌在 <b>download-manager/config.json</b> 的
              <code>server.access_token</code>；管理器启动时也会打印到控制台。只需填一次。</p>
            <p class="hint">管理器若跑在别的机器上，把地址改成它的局域网 IP，并在 Tampermonkey 里
              给本脚本补一条 <code>@connect</code>（脚本管理器会提示）。</p>
          </div>

          <div class="result" id="result" hidden></div>
        </div>
        <footer>
          <button class="primary" id="submit">加入下载</button>
          <button class="ghost" id="save" hidden>保存设置</button>
          <button class="ghost" id="test" hidden>测试连接</button>
          <span class="spacer"></span>
          <button class="link" id="open">打开管理器</button>
        </footer>
      </div>
    </div>
  `;

  let host = null;   // 面板宿主（懒创建，跨次复用）
  let root = null;   // shadow root
  let el = {};       // 常用节点引用

  function buildPanel() {
    host = document.createElement('div');
    host.id = 'dm-userscript-host';
    host.style.cssText = 'position:fixed;inset:0;z-index:2147483647;';
    root = host.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = CSS;
    const box = document.createElement('div');
    box.innerHTML = HTML;
    root.appendChild(style);
    root.appendChild(box);
    (document.body || document.documentElement).appendChild(host);

    const $ = (sel) => root.querySelector(sel);
    el = {
      mask: $('.mask'), result: $('#result'), warn: $('#warn'),
      type: $('#type'), mode: $('#mode'), url: $('#url'), urlLabel: $('#url-label'),
      referer: $('#referer'), cookie: $('#cookie'), range: $('#range'),
      episodes: $('#episodes'), lineSel: $('#line-sel'), line: $('#line'),
      pick: $('#pick'), interval: $('#interval'),
      viewTask: $('#view-task'), viewSettings: $('#view-settings'),
      submit: $('#submit'), save: $('#save'), test: $('#test'), open: $('#open'),
      base: $('#set-base'), token: $('#set-token'),
    };

    // 事件绑定
    $('#close').addEventListener('click', closePanel);
    el.mask.addEventListener('click', (e) => { if (e.target === el.mask) closePanel(); });
    root.querySelectorAll('.chips button').forEach((b) => {
      b.addEventListener('click', () => { el.episodes.value = b.dataset.spec; });
    });
    [el.type, el.mode, el.url].forEach((n) => {
      n.addEventListener('change', refresh);
      n.addEventListener('input', refresh);
    });
    el.lineSel.addEventListener('change', refresh);
    el.submit.addEventListener('click', onSubmit);
    el.save.addEventListener('click', onSaveSettings);
    el.test.addEventListener('click', onTest);
    el.open.addEventListener('click', () => {
      window.open(getBase(), '_blank', 'noopener');
    });
  }

  /** 按「下载器 + 方式 + 地址」刷新字段显隐与文案。 */
  function refresh() {
    const p = currentPlan();
    const show = (key, on) => {
      root.querySelectorAll('[data-show="' + key + '"]').forEach((n) => { n.hidden = !on; });
    };
    show('video', p.isVideo);
    show('video:get', p.showGet);
    show('ehentai', p.showRange);
    show('batch-line-pick', p.showEpisodes);
    show('batch-line', p.showLine);
    show('batch-line-custom', p.showLine && el.lineSel.value === '__custom');
    show('batch-pick', p.showPick);
    show('batch-interval', p.showInterval);

    el.urlLabel.textContent = p.type === 'ehentai' ? '画廊 URL'
      : (p.type === 'ebook' ? '书籍地址 / book_id' : '地址');

    const caution = cautionFor(el.url.value.trim());
    el.warn.hidden = !caution;
    el.warn.textContent = caution;
  }

  /** 读当前面板状态得到 fieldPlan（纯函数 fieldPlan 的取值包装）。 */
  function currentPlan() {
    return fieldPlan(el.type.value, el.mode.value, el.url.value.trim());
  }

  function setResult(text, ok, withOpenLink) {
    el.result.hidden = false;
    el.result.className = 'result ' + (ok ? 'ok' : 'bad');
    el.result.textContent = text;
    if (ok && withOpenLink) {
      // 只有点了这个链接才打开管理器页面；提交任务本身不打开任何页面
      const a = document.createElement('a');
      a.href = getBase();
      a.target = '_blank';
      a.rel = 'noopener';
      a.textContent = ' 打开管理器看看';
      el.result.appendChild(a);
    }
  }

  function currentState() {
    const p = currentPlan();
    return {
      type: p.type,
      mode: p.mode,
      url: el.url.value,
      referer: el.referer.value,
      cookie: el.cookie.value,
      range: el.range.value,
      episodes: el.episodes.value,
      // 隐藏的字段不提交（如内嵌站点的"每集候选"），避免把不生效的参数塞给下载器
      line: (p.showLine && el.lineSel.value === '__custom') ? el.line.value : '',
      pick: p.showPick ? el.pick.value : '',
      interval: p.showInterval ? el.interval.value : '',
    };
  }

  async function onSubmit() {
    let payload;
    try {
      payload = buildTaskPayload(currentState());
    } catch (e) {
      setResult('✗ ' + e.message, false);
      return;
    }
    if (!getToken()) {
      setResult('还没填访问令牌 —— 已切到设置，填完再提交', false);
      switchView('settings');
      el.token.focus();
      return;
    }
    el.submit.disabled = true;
    el.submit.textContent = '提交中…';
    setResult('提交中…', true);
    try {
      const task = await createTask(payload);
      // 不关闭面板、保留表单：方便接着提交下一个任务（多任务场景）
      setResult('✓ 已加入任务 #' + String(task.id || '').slice(0, 8)
                + ' — ' + statusLabel(task), true, true);
    } catch (e) {
      if (e.code === 'unauthorized') {
        switchView('settings');
        el.token.focus();
      }
      setResult('✗ ' + e.message, false);
    } finally {
      el.submit.disabled = false;
      el.submit.textContent = '加入下载';
    }
  }

  function onSaveSettings() {
    store.set(KEY_BASE, el.base.value.trim() || DEFAULT_BASE);
    store.set(KEY_TOKEN, el.token.value.trim());
    setResult('✓ 设置已保存', true);
    switchView('task');
  }

  async function onTest() {
    store.set(KEY_BASE, el.base.value.trim() || DEFAULT_BASE);
    store.set(KEY_TOKEN, el.token.value.trim());
    el.test.disabled = true;
    setResult('测试中…', true);
    try {
      setResult('✓ ' + await testConnection(), true);
    } catch (e) {
      setResult('✗ ' + e.message, false);
    } finally {
      el.test.disabled = false;
    }
  }

  /** 切换「任务视图 / 设置视图」并同步底部按钮。 */
  function switchView(view) {
    const isTask = view !== 'settings';
    el.viewTask.hidden = !isTask;
    el.viewSettings.hidden = isTask;
    el.submit.hidden = !isTask;
    el.save.hidden = isTask;
    el.test.hidden = isTask;
    if (!isTask) {
      el.base.value = getBase();
      el.token.value = getToken();
    }
    el.result.hidden = true;
  }

  function onKeyDown(e) {
    if (e.key === 'Escape') { closePanel(); }
  }

  function closePanel() {
    if (host) host.remove();
    host = null;
    root = null;
    document.removeEventListener('keydown', onKeyDown, true);
  }

  /** 打开面板：prefill=true 时用当前页地址预填。 */
  function openPanel(view) {
    if (!host) {
      buildPanel();
      document.addEventListener('keydown', onKeyDown, true);
      // 按域名预选下载器/方式，并把当前页地址预填进地址框
      const preset = domainPreset(location.href);
      el.type.value = preset.type;
      el.mode.value = preset.mode || 'batch';
      el.url.value = location.href;
    }
    switchView(view || 'task');
    refresh();
    (view === 'settings' ? el.token : el.episodes).focus();
  }

  // ---------------------------------------------------------------- 菜单注册

  if (typeof GM_registerMenuCommand === 'function') {
    GM_registerMenuCommand('下载到管理器…', () => openPanel('task'));
    GM_registerMenuCommand('管理器设置（地址/令牌）', () => openPanel('settings'));
    GM_registerMenuCommand('打开管理器页面', () => {
      window.open(getBase(), '_blank', 'noopener');
    });
  }

  // 调试/测试用：Node 桩测试直接调用这些纯函数（不影响正常使用）
  try {
    (typeof globalThis !== 'undefined' ? globalThis : window).__dmUserscript = {
      VERSION: VERSION,
      domainPreset: domainPreset,
      isEmbeddedSite: isEmbeddedSite,
      cautionFor: cautionFor,
      isValidSpec: isValidSpec,
      statusLabel: statusLabel,
      fieldPlan: fieldPlan,
      buildTaskPayload: buildTaskPayload,
      PRESETS: PRESETS,
      SITES: SITES,
    };
  } catch (e) { /* 忽略 */ }
})();
