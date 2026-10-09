/* 实时输出坞（v0.2.0 改为固定底部、不遮挡内容的两档高度：小 ≈ 6 行 / 大 ≈ 55vh）。
   每个任务一个页签，通过 SSE 接收日志。
   `\r` 行（进度条）会原地覆盖上一行，避免进度条把输出刷成几千行。

   v0.4.2：
   - 页签**最新在左**（最近新开始的任务排最左，最新那个永远看得见、不用横向滚动）；
   - 新增「关闭已完成」：一键关掉所有已结束任务的页签（运行中/排队的一个都不动）。 */

window.LogView = (function () {
  const MAX_LINES = 4000;          // 单任务 DOM 行数上限，超出丢弃最早的

  // 已结束（不会再输出日志）的任务状态 —— 只有这些页签会被「关闭已完成」关掉。
  // 与后端 adapters/base.py 的 STATUS_* 对齐；运行中/排队中的绝不在内。
  const FINISHED_STATUS = new Set([
    'completed', 'completed_unverified', 'partial_failed',
    'failed', 'crashed', 'stopped', 'interrupted',
  ]);

  const state = {
    tabs: new Map(),               // taskId → {label, lines: [node], stream, lastSeq, status}
    active: null,
    follow: true,
  };

  const els = {};

  function init() {
    els.root = document.getElementById('logview');
    els.tabs = document.getElementById('log-tabs');
    els.body = document.getElementById('log-body');
    els.toggle = document.getElementById('logview-toggle');
    els.followBox = document.getElementById('log-follow');
    els.clear = document.getElementById('log-clear');
    els.download = document.getElementById('log-download');
    els.closeDone = document.getElementById('log-close-done');

    // 两档高度：小 / 大。高度由 body 上的 class 控制（CSS 变量 --dock-h），
    // 因此页面内容的下边距会自动跟着变，坞永远不会遮住内容。
    els.toggle.addEventListener('click', () => {
      document.body.classList.toggle('dock-large');
      updateToggle();
    });
    els.tabs.addEventListener('click', (evt) => {
      const close = evt.target.closest('.x');
      const tab = evt.target.closest('.tab');
      if (!tab) return;
      const id = tab.dataset.id;
      if (close) { closeTab(id); return; }
      select(id);
    });
    els.followBox.addEventListener('change', () => {
      state.follow = els.followBox.checked;
      if (state.follow) scrollToEnd();
    });
    els.clear.addEventListener('click', () => {
      const tab = state.tabs.get(state.active);
      if (!tab) return;
      tab.lines.forEach((n) => n.remove());
      tab.lines = [];
      els.body.textContent = '';
    });
    els.download.addEventListener('click', () => {
      const tab = state.tabs.get(state.active);
      if (!tab) return;
      const text = tab.lines.map((n) => n.textContent).join('\n');
      const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${tab.label.replace(/[\\/:*?"<>|]/g, '_')}.log`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
    // 一键关闭所有已结束的页签（v0.4.2）。判空兜底：万一浏览器缓存了旧版 index.html
    // （没有这个按钮），也只是没按钮可用，不会让整个输出坞的初始化崩掉
    if (els.closeDone) {
      els.closeDone.addEventListener('click', () => {
        const n = closeFinished();
        if (n) Utils.toast(`已关闭 ${n} 个已结束任务的页签`, 'ok');
      });
    }
    updateToggle();
    renderTabs();          // 初始化时把页签区与「关闭已完成」的状态归一（HTML 里只是初值）
  }

  function updateToggle() {
    const large = document.body.classList.contains('dock-large');
    els.toggle.textContent = large ? '收起输出' : '展开输出';
  }

  /** 打开（或聚焦）某任务的日志页签并开始接收。
      保持当前高度（默认小）：这样发起任务后不用手动操作就能看到是否成功启动。 */
  function open(taskId, label, options = {}) {
    if (!els.root) init();
    let tab = state.tabs.get(taskId);
    if (!tab) {
      tab = { id: taskId, label: label || taskId, lines: [], stream: null, lastSeq: 0,
              status: options.status || '', historyLoaded: false };
      state.tabs.set(taskId, tab);
      renderTabs();
    } else if (label) {
      tab.label = label;
      renderTabs();
    }
    ensureStream(tab, options.after || 0);
    select(taskId);
    return tab;
  }

  /** 先补历史日志再订阅 SSE。
      为什么要先调 REST：服务重启后，历史任务不在内存里，SSE 端点拿不到它的日志，
      只能由 REST 从日志文件补读（否则点旧任务的「日志」永远是空的）。 */
  function ensureStream(tab, after) {
    if (tab.stream) return;
    if (tab.historyLoaded) {
      subscribe(tab, after || tab.lastSeq);
      return;
    }
    tab.historyLoaded = true;
    API.taskLog(tab.id, 2000).then((data) => {
      for (const line of (data.lines || [])) appendLine(tab, line);
      tab.lastSeq = Math.max(tab.lastSeq, data.last_seq || 0);
      subscribe(tab, tab.lastSeq);
    }).catch(() => subscribe(tab, tab.lastSeq));
  }

  function subscribe(tab, after) {
    tab.lastSeq = Math.max(tab.lastSeq || 0, after || 0);
    tab.stream = API.taskEvents(tab.id, {
      hello: () => {},
      log: (line) => appendLine(tab, line),
      status: (task) => {
        tab.status = task.status;
        renderTabs();          // 状态变了 → 顺带刷新「关闭已完成」的计数
      },
      done: () => {
        // 服务端表示日志已发完；保持页签，不再重连
        if (tab.stream) { tab.stream.close(); tab.stream = null; }
        renderTabs();
      },
      error: () => { /* EventSource 自动重连，无需处理 */ },
    });
  }

  function appendLine(tab, line) {
    if (line.seq) tab.lastSeq = Math.max(tab.lastSeq, line.seq);
    const isActive = state.active === tab.id;
    const node = document.createElement('div');
    node.className = line.kind === 'err' ? 'err' : (line.kind === 'sys' ? 'sys' : '');
    const stamp = Utils.clock(line.ts);
    node.textContent = stamp ? `[${stamp}] ${line.text}` : line.text;

    // \r 覆盖：替换上一行而不是新增
    if (line.overwrite && tab.lines.length) {
      const prev = tab.lines[tab.lines.length - 1];
      prev.textContent = node.textContent;
      prev.className = node.className;
      if (isActive) scrollToEnd();
      return;
    }

    tab.lines.push(node);
    if (tab.lines.length > MAX_LINES) {
      const dropped = tab.lines.splice(0, tab.lines.length - MAX_LINES);
      dropped.forEach((n) => n.remove());
    }
    if (isActive) {
      // 首次输出时清掉占位文字
      if (tab.lines.length === 1 && els.body.textContent.startsWith('（')) {
        els.body.textContent = '';
      }
      els.body.append(node);
      scrollToEnd();
    }
  }

  function scrollToEnd() {
    if (!state.follow) return;
    els.body.scrollTop = els.body.scrollHeight;
  }

  /** 页签的**视觉顺序**：最新打开的排最左（v0.4.2 用户要求）。
      实现上只反转 Map 的插入顺序 —— 不重排、不跳动，某个页签收状态也不会换位置。 */
  function orderedIds() {
    return Array.from(state.tabs.keys()).reverse();
  }

  /** 已结束的页签 id（视觉顺序）。状态未知（还没收到 status）的不算，避免误关。 */
  function finishedIds() {
    return orderedIds().filter((id) => FINISHED_STATUS.has((state.tabs.get(id) || {}).status));
  }

  function showEmpty() {
    state.active = null;
    els.body.textContent = '（暂无输出。发起任务后会自动显示该任务的实时日志。）';
  }

  function select(taskId) {
    const tab = taskId ? state.tabs.get(taskId) : null;
    if (!tab) { showEmpty(); renderTabs(); return; }
    state.active = taskId;
    els.body.textContent = '';
    if (!tab.lines.length) {
      els.body.textContent = '（等待输出…）';
    } else {
      tab.lines.forEach((n) => els.body.append(n));
    }
    scrollToEnd();
    renderTabs();
  }

  /** 关掉一个页签后该选谁：它在视觉顺序里的**同一下标**（越界取最后一个）。
      这样"关掉哪一格，目光就停在哪一格"，比固定跳到第一个更符合直觉。 */
  function neighborAfterClose(before, closedId) {
    const at = before.indexOf(closedId);
    const rest = orderedIds();
    if (!rest.length) return null;
    return rest[Math.min(Math.max(at, 0), rest.length - 1)];
  }

  /** 只回收页签资源（关流 + 从 Map 删），不动选中、不渲染 —— 供单选/批量关闭复用 */
  function dropTab(taskId) {
    const tab = state.tabs.get(taskId);
    if (!tab) return;
    if (tab.stream) tab.stream.close();
    state.tabs.delete(taskId);
  }

  function closeTab(taskId) {
    if (!state.tabs.has(taskId)) return;
    const before = orderedIds();
    const wasActive = state.active === taskId;
    dropTab(taskId);
    if (wasActive) select(neighborAfterClose(before, taskId));
    else renderTabs();
  }

  /** 一键关闭所有已结束任务的页签，返回关掉的数量（运行中/排队中的不碰） */
  function closeFinished() {
    const ids = finishedIds();
    if (!ids.length) return 0;
    const before = orderedIds();
    const activeBefore = state.active;
    const wasActive = ids.indexOf(activeBefore) >= 0;
    ids.forEach(dropTab);
    if (wasActive) select(neighborAfterClose(before, activeBefore));
    else renderTabs();
    return ids.length;
  }

  /** 页签栏是横向滚动的：只调 scrollLeft 把它带进视野，避免影响页面纵向位置 */
  function ensureTabVisible(node) {
    const left = node.offsetLeft;
    const right = left + node.offsetWidth;
    if (left < els.tabs.scrollLeft) {
      els.tabs.scrollLeft = left;
    } else if (right > els.tabs.scrollLeft + els.tabs.clientWidth) {
      els.tabs.scrollLeft = right - els.tabs.clientWidth;
    }
  }

  /** 「关闭已完成 (N)」：带可关闭数量，没有可关的置灰 */
  function updateCloseDone() {
    if (!els.closeDone) return;
    const n = finishedIds().length;
    els.closeDone.disabled = n === 0;
    els.closeDone.textContent = n ? `关闭已完成 (${n})` : '关闭已完成';
  }

  function renderTabs() {
    els.tabs.textContent = '';
    for (const id of orderedIds()) {
      const tab = state.tabs.get(id);
      const running = tab.status === 'running';
      const node = Utils.el('span', {
        class: 'tab' + (tab.id === state.active ? ' active' : ''),
        dataset: { id: tab.id },
        title: tab.label,
      }, [
        // × 放在最左边（与“最新页签在最左”一致，长标签也不会把关闭按钮推远）
        Utils.el('span', { class: 'x', text: '×', title: '关闭此页签（不影响任务）' }),
        running ? Utils.el('span', { class: 'run-dot', text: '●' }) : null,
        Utils.el('span', { class: 'tab-label', text: tab.label, title: tab.label }),
      ]);
      els.tabs.append(node);
      if (tab.id === state.active) ensureTabVisible(node);
    }
    updateCloseDone();
  }

  // 页面加载后立即初始化：否则在打开过任何任务日志之前，底部输出坞的高度切换按钮没有绑定事件。
  document.addEventListener('DOMContentLoaded', () => { if (!els.root) init(); });

  return {
    open, closeTab, closeFinished, init,
    get active() { return state.active; },
  };
})();
