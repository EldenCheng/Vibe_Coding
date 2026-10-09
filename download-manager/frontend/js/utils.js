/* 通用工具：DOM 操作、格式化、令牌存取、提示条。
   作为普通脚本引入（非 ES module），把接口挂在 window.Utils 上供其他脚本使用。 */

window.Utils = (function () {
  const TOKEN_KEY = 'download-manager-token';

  return {
    // ---------- 令牌 ----------

    /** 取令牌：优先 localStorage；首次从 URL 的 ?token= 读取并保存，同时从地址栏抹掉。 */
    readToken() {
      let token = localStorage.getItem(TOKEN_KEY) || '';
      const url = new URL(location.href);
      const fromUrl = url.searchParams.get('token');
      if (fromUrl) {
        token = fromUrl;
        localStorage.setItem(TOKEN_KEY, token);
        url.searchParams.delete('token');
        history.replaceState(null, '', url.pathname + url.search + url.hash);
      }
      return token;
    },

    saveToken(token) {
      if (token) localStorage.setItem(TOKEN_KEY, token);
    },

    clearToken() {
      localStorage.removeItem(TOKEN_KEY);
    },

    get token() {
      return localStorage.getItem(TOKEN_KEY) || '';
    },

    // ---------- DOM ----------

    el(tag, attrs = {}, children = []) {
      const node = document.createElement(tag);
      for (const [key, value] of Object.entries(attrs)) {
        if (value === null || value === undefined || value === false) continue;
        if (key === 'class') node.className = value;
        else if (key === 'text') node.textContent = value;
        else if (key === 'html') node.innerHTML = value;
        else if (key === 'dataset') Object.assign(node.dataset, value);
        else if (key === 'style') node.setAttribute('style', value);
        else if (key.startsWith('on') && typeof value === 'function') {
          node.addEventListener(key.slice(2).toLowerCase(), value);
        } else if (value === true) node.setAttribute(key, '');
        else node.setAttribute(key, value);
      }
      for (const child of [].concat(children)) {
        if (child === null || child === undefined || child === false) continue;
        node.append(child instanceof Node ? child : document.createTextNode(String(child)));
      }
      return node;
    },

    $(selector, root = document) { return root.querySelector(selector); },
    $$(selector, root = document) { return Array.from(root.querySelectorAll(selector)); },

    // ---------- 格式化 ----------

    bytes(num) {
      if (num === null || num === undefined || isNaN(num)) return '-';
      const units = ['B', 'KB', 'MB', 'GB', 'TB'];
      let n = Number(num), i = 0;
      while (Math.abs(n) >= 1024 && i < units.length - 1) { n /= 1024; i++; }
      return `${i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
    },

    time(ts) {
      if (!ts) return '-';
      const d = new Date(ts * 1000);
      const pad = (v) => String(v).padStart(2, '0');
      return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    },

    clock(ts) {
      if (!ts) return '';
      const d = new Date(ts * 1000);
      const pad = (v) => String(v).padStart(2, '0');
      return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    },

    duration(seconds) {
      if (!seconds || seconds < 0) return '-';
      const s = Math.floor(seconds);
      const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
      if (h) return `${h}小时${m}分`;
      if (m) return `${m}分${s % 60}秒`;
      return `${s}秒`;
    },

    percent(done, total) {
      if (!total) return null;
      return Math.min(100, Math.round((done / total) * 100));
    },

    // ---------- 提示条 ----------

    toast(message, kind = 'info', timeout = 4500) {
      const area = document.getElementById('toast-area');
      if (!area) return;
      const node = Utils.el('div', { class: `toast ${kind}`, text: message });
      area.append(node);
      setTimeout(() => { node.style.opacity = '0'; setTimeout(() => node.remove(), 300); }, timeout);
    },

    /** 统一的错误提示：把后端返回的 {error:{message}} 解出来 */
    errorMessage(err) {
      if (!err) return '未知错误';
      if (typeof err === 'string') return err;
      if (err.error && err.error.message) return err.error.message;
      if (err.message) return err.message;
      return JSON.stringify(err);
    },

    /** 简单的并发去抖：短时间内重复调用只执行最后一次 */
    debounce(fn, wait = 250) {
      let timer = null;
      return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), wait);
      };
    },

    // ---------- 模态框（配置弹窗用） ----------

    /** 打开一个模态框。返回 {close, root, body}。点击遮罩或 Esc 关闭。 */
    modal({ title, content, width, onClose } = {}) {
      const host = document.getElementById('modal-root');
      const overlay = Utils.el('div', { class: 'modal-overlay' });
      const closeBtn = Utils.el('button', { class: 'close', text: '×', title: '关闭' });
      const head = Utils.el('div', { class: 'modal-head' }, [title || '']);
      head.append(closeBtn);
      const body = Utils.el('div', { class: 'modal-body' });
      if (content) body.append(content);
      const modal = Utils.el('div', { class: 'modal' }, [head, body]);
      if (width) modal.style.width = `min(${width}, 100%)`;
      overlay.append(modal);
      host.append(overlay);

      const onKey = (e) => { if (e.key === 'Escape') close(); };
      function close() {
        overlay.remove();
        document.removeEventListener('keydown', onKey);
        if (onClose) onClose();
      }
      closeBtn.addEventListener('click', close);
      overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });
      document.addEventListener('keydown', onKey);
      return { close, root: modal, body };
    },

    // ---------- 浮动说明气泡（表单字段的 ? 图标用） ----------

    /** 在 anchor 旁弹出一个带关闭按钮的浮动说明面板。同一时刻只保留一个。
     *  返回 {close, anchor}；点击面板外、按 Esc、点关闭按钮均会关闭。 */
    popover(anchor, { title, html } = {}) {
      if (Utils._popover) Utils._popover.close();   // 单例：先关旧的

      const panel = Utils.el('div', { class: 'popover' });
      const head = Utils.el('div', { class: 'popover-head' });
      head.append(Utils.el('span', { class: 'popover-title', text: title || '说明' }));
      const closeBtn = Utils.el('button', { class: 'close', type: 'button', text: '×', title: '关闭' });
      head.append(closeBtn);
      const body = Utils.el('div', { class: 'popover-body', html: html || '' });
      panel.append(head, body);
      document.body.append(panel);

      // 贴在被点击元素旁边；下方放不下就翻到上方，并避开固定底部输出坞
      function place() {
        const r = anchor.getBoundingClientRect();
        const pw = panel.offsetWidth, ph = panel.offsetHeight;
        const m = 10;
        // 固定底部的输出坞会占住下方，气泡尽量放在它上面
        // 注意：position:fixed 元素的 offsetParent 为 null，不能用它判断可见性
        const dock = document.getElementById('logview');
        let dockTop = window.innerHeight;
        if (dock) {
          const dr = dock.getBoundingClientRect();
          if (dr.height > 0 && dr.top < window.innerHeight) dockTop = dr.top;
        }
        const bottomLimit = Math.min(window.innerHeight, dockTop) - m;

        let top = r.bottom + m;
        if (top + ph > bottomLimit) {
          const above = r.top - ph - m;
          top = above >= m ? above : Math.max(m, bottomLimit - ph);
        }
        const left = Math.min(Math.max(m, r.left), Math.max(m, window.innerWidth - pw - m));
        panel.style.left = `${Math.round(left)}px`;
        panel.style.top = `${Math.round(Math.max(m, top))}px`;
      }

      const onKey = (e) => { if (e.key === 'Escape') close(); };
      const onDown = (e) => {
        if (panel.contains(e.target) || anchor.contains(e.target)) return;
        close();
      };
      const onReflow = () => place();

      function close() {
        panel.remove();
        anchor.classList.remove('active');
        document.removeEventListener('keydown', onKey);
        document.removeEventListener('mousedown', onDown, true);
        window.removeEventListener('resize', onReflow);
        window.removeEventListener('scroll', onReflow, true);
        if (Utils._popover && Utils._popover.anchor === anchor) Utils._popover = null;
      }

      closeBtn.addEventListener('click', close);
      document.addEventListener('keydown', onKey);
      document.addEventListener('mousedown', onDown, true);
      window.addEventListener('resize', onReflow);
      window.addEventListener('scroll', onReflow, true);

      const api = { close, anchor, panel };
      Utils._popover = api;
      anchor.classList.add('active');
      place();
      return api;
    },

    escape(text) {
      return String(text ?? '').replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
      ));
    },
  };
})();
