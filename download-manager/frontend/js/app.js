/* 应用主逻辑（v0.2.0 界面重构）：粘性头部、两栏工作区、配置弹窗、底部输出坞、全局事件。 */

(function () {
  const state = {
    adapters: [],
    tabs: new Map(),        // typeId → {pane, collectForm, taskList, openDirBtn, ...}
    activeTab: null,
    runningCount: 0,
    canOpen: false,         // 前后端同 OS 且后端支持时，才允许「打开目录」
    sysTimer: null,
  };

  // ---------------------------------------------------------------- 入口

  async function boot() {
    const token = Utils.readToken();
    if (!token) { showLogin('缺少访问令牌。请用带 ?token=xxx 的地址打开本页面。'); return; }

    Notify.init(document.getElementById('notify-toggle'));

    let health;
    try {
      health = await API.health();
    } catch {
      showLogin('无法连接到后端服务，请确认服务正在运行。');
      return;
    }
    document.getElementById('version').textContent = `v${health.version || ''}`;

    try {
      const data = await API.adapters();
      state.adapters = data.adapters || [];
    } catch (err) {
      if (err && err.unauthorized) { showLogin('访问令牌无效或已更换，请用新的带令牌地址打开。'); return; }
      Utils.toast(`读取下载器信息失败：${Utils.errorMessage(err)}`, 'error');
      return;
    }

    buildTabs();
    buildPanes();
    // buildTabs 里调用的 activate 发生在 panes 创建之前，所以这里要再激活一次，
    // 否则首屏所有 .pane 都没有 .active、内容区是空的。
    if (state.activeTab || state.adapters.length) {
      activate(state.activeTab || state.adapters[0].type);
    }

    // 顶栏「配置」按钮：打开**当前标签页**对应下载器的配置弹窗
    document.getElementById('config-btn').addEventListener('click', () => {
      if (state.activeTab) openConfig(state.activeTab);
    });
    document.getElementById('logout-btn').addEventListener('click', () => {
      if (!confirm('清除本机保存的访问令牌？（下次需要用带令牌的地址重新打开）')) return;
      Utils.clearToken();
      location.reload();
    });

    refreshSysinfo();
    state.sysTimer = setInterval(refreshSysinfo, 5000);
    subscribeGlobalEvents();
    loadAllTasks();
  }

  function showLogin(message) {
    document.querySelector('main').innerHTML = '';
    document.getElementById('tabs').innerHTML = '';
    document.getElementById('logview').style.display = 'none';
    const wrap = Utils.el('div', { class: 'login-wrap' }, [
      Utils.el('h1', { text: '需要访问令牌' }),
      Utils.el('div', { class: 'banner warn', text: message }),
      Utils.el('div', { class: 'faint', text: '令牌写在 download-manager/config.json 的 server.access_token，' +
        '也可以在服务启动时打印的访问地址里找到。' }),
    ]);
    document.querySelector('main').append(wrap);
  }

  // ---------------------------------------------------------------- 标签页

  function buildTabs() {
    const tabs = document.getElementById('tabs');
    tabs.innerHTML = '';
    for (const adapter of state.adapters) {
      const button = Utils.el('button', {
        dataset: { type: adapter.type },
        text: adapter.name,
      });
      button.addEventListener('click', () => activate(adapter.type));
      tabs.append(button);
    }
    if (state.adapters.length) activate(state.adapters[0].type);
  }

  function activate(typeId) {
    state.activeTab = typeId;
    for (const button of Utils.$$('#tabs button')) {
      button.classList.toggle('active', button.dataset.type === typeId);
    }
    for (const pane of Utils.$$('.pane')) {
      pane.classList.toggle('active', pane.dataset.type === typeId);
    }
  }

  // ---------------------------------------------------------------- 面板

  function buildPanes() {
    const main = document.querySelector('main');
    main.innerHTML = '';
    for (const adapter of state.adapters) {
      const pane = Utils.el('section', { class: 'pane', dataset: { type: adapter.type } });
      main.append(pane);

      const grid = Utils.el('div', { class: 'pane-grid' });
      const colMain = Utils.el('div', { class: 'col-main' });
      const colSide = Utils.el('div', { class: 'col-side' });
      grid.append(colMain, colSide);
      pane.append(grid);

      // ---- 右栏：新建任务 ----
      const paramCard = Utils.el('div', { class: 'card' });
      paramCard.append(Utils.el('div', { class: 'card-head static' }, [
        Utils.el('span', { text: '＋ 新建任务' }),
        Utils.el('span', { class: 'spacer' }),
        Utils.el('span', { class: 'hint', title: adapter.project_dir, text: projectTail(adapter.project_dir) }),
      ]));
      const paramBody = Utils.el('div', { class: 'card-body' });
      paramCard.append(paramBody);
      colSide.append(paramCard);
      const formApi = buildParamForm(adapter, paramBody);
      paramBody.append(formApi.actions);

      // ---- 右栏：工具按钮（配置 / 打开目录） ----
      const openDirBtn = Utils.el('button', {
        class: 'btn block', text: '📂 打开下载目录', hidden: true,
        title: '在后端机器的文件管理器中打开该下载器的输出根目录',
      });
      openDirBtn.addEventListener('click', async () => {
        try {
          const res = await API.openPath(adapter.output_root, false);
          Utils.toast(res.message || '已打开目录', 'ok');
        } catch (err) {
          Utils.toast(`打开失败：${Utils.errorMessage(err)}`, 'error', 8000);
        }
      });
      const cfgBtn = Utils.el('button', { class: 'btn block', text: '⚙ 下载器配置' });
      cfgBtn.addEventListener('click', () => openConfig(adapter.type));
      const tools = Utils.el('div', { class: 'btn-row stack' }, [cfgBtn, openDirBtn]);
      colSide.append(tools);

      // ---- 右栏：依赖自检 ----
      colSide.append(buildProbeBox(adapter));

      // ---- 左栏：任务与产物 ----
      const taskList = TaskList.create(adapter.type, {
        actions: adapter.available_actions || [],
        collectForm: formApi.collect,
        canOpen: () => state.canOpen,
        outputRoot: () => adapter.output_root,
        onTasks: () => updateRunningBadge(),
      });
      colMain.append(taskList.root);

      state.tabs.set(adapter.type, {
        pane, collectForm: formApi.collect, taskList, openDirBtn,
      });
    }
  }

  function projectTail(path) {
    if (!path) return '';
    const parts = String(path).split(/[\\/]/).filter(Boolean);
    return parts.length ? `…/${parts.slice(-2).join('/')}` : path;
  }

  /** 依赖自检提示（紧凑版，放在右栏，不占主区）。 */
  function buildProbeBox(adapter) {
    const problems = (adapter.probe && adapter.probe.problems) || [];
    const ok = !problems.length;
    const box = Utils.el('div', { class: `probe-box ${ok ? 'ok' : 'bad'}` });
    const head = Utils.el('div', { class: 'probe-head' }, [
      Utils.el('span', { text: ok ? '✓ 依赖自检通过' : '⚠️ 该下载器存在环境问题' }),
      Utils.el('span', { class: 'spacer' }),
      Utils.el('span', { class: 'faint', text: adapter.probe?.project_dir ? '项目目录就绪' : '' }),
    ]);
    box.append(head);
    if (!ok) {
      const list = Utils.el('ul');
      problems.forEach((p) => list.append(Utils.el('li', { text: p })));
      box.append(list);
    }
    return box;
  }

  // ---------------------------------------------------------------- 配置弹窗

  function openConfig(typeId) {
    const adapter = state.adapters.find((a) => a.type === typeId);
    const form = ConfigForm.create(typeId, { onSaved: () => refreshSysinfo() });
    Utils.modal({
      title: `⚙ 下载器配置 · ${adapter ? adapter.name : typeId}`,
      content: form.root,
      width: '820px',
    });
  }

  /** 按 form_schema 渲染参数表单；支持 show_for 按某字段取值动态显隐（视频的下载方式） */
  function buildParamForm(adapter, container) {
    const grid = Utils.el('div', { class: 'grid2' });
    const fields = [];
    const inputs = new Map();

    for (const field of adapter.form_schema || []) {
      const id = `p-${adapter.type}-${field.key}`;
      let input;
      if (field.type === 'select') {
        input = Utils.el('select', { id });
        for (const opt of (field.options || [])) {
          input.append(Utils.el('option', { value: opt.value, text: opt.label }));
        }
        if (field.default !== undefined) input.value = field.default;
      } else if (field.type === 'bool') {
        input = Utils.el('input', { type: 'checkbox', id });
        input.checked = !!field.default;
      } else {
        const numeric = field.type === 'number' || field.type === 'float';
        input = Utils.el('input', {
          type: numeric ? 'number' : 'text',
          id,
          placeholder: field.placeholder || '',
          step: field.type === 'float' ? 'any' : null,
        });
        if (field.default !== undefined) input.value = field.default;
      }
      input.dataset.key = field.key;
      input.dataset.fieldType = field.type || 'text';

      // “?” 按钮：点击弹出浮动说明（长说明收进气泡，避免把表单撑高）
      const makeHelpBtn = () => {
        const btn = Utils.el('button', {
          type: 'button', class: 'help-btn', text: '?',
          title: '查看说明', 'aria-label': '查看说明',
        });
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          // 再点同一个图标 = 收起
          if (Utils._popover && Utils._popover.anchor === btn) { Utils._popover.close(); return; }
          Utils.popover(btn, { title: field.help_title || field.label, html: field.help_popover });
        });
        return btn;
      };

      const label = Utils.el('label', { for: id }, [
        document.createTextNode(field.label),
        field.required ? Utils.el('span', { class: 'req', text: '*' }) : null,
        // 没有行内说明时，? 图标紧跟在标签后（紧贴输入框一侧）
        (field.help_popover && !field.help) ? makeHelpBtn() : null,
      ]);
      const wrap = Utils.el('div', { class: 'field' }, [label, input]);
      // 行内说明（短的直接显示）；若同时有 help_popover，则在其后追加 ? 图标
      if (field.help) {
        const helpLine = Utils.el('div', { class: 'help' });
        helpLine.append(document.createTextNode(field.help));
        if (field.help_popover) {
          helpLine.append(document.createTextNode(' '));
          helpLine.append(makeHelpBtn());
        }
        wrap.append(helpLine);
      }
      wrap.dataset.showFor = field.show_for || '';
      fields.push({ field, wrap, input });
      grid.append(wrap);
    }

    container.append(grid);

    /** 按 show_for 动态显隐 */
    function syncVisibility() {
      const modeInput = inputs.get('mode');
      const mode = modeInput ? modeInput.value : '';
      for (const { field, wrap } of fields) {
        if (!field.show_for) { wrap.hidden = false; continue; }
        wrap.hidden = mode !== '' && field.show_for !== mode;
      }
    }

    for (const { field, input } of fields) {
      inputs.set(field.key, input);
      input.addEventListener('change', syncVisibility);
      input.addEventListener('input', syncVisibility);
    }
    for (const input of inputs.values()) {
      if (input.tagName !== 'TEXTAREA') {
        input.addEventListener('keydown', (evt) => {
          if (evt.key === 'Enter') submit();
        });
      }
    }

    function collect() {
      const form = {};
      for (const [key, input] of inputs.entries()) {
        const type = input.dataset.fieldType;
        if (type === 'bool') { form[key] = input.checked; continue; }
        const raw = input.value.trim();
        if (raw === '') continue;
        if (type === 'number' || type === 'float') {
          const num = Number(raw);
          if (Number.isNaN(num)) { Utils.toast(`「${key}」需要数字`, 'error'); return null; }
          form[key] = num;
        } else {
          form[key] = raw;
        }
      }
      return form;
    }

    const submitBtn = Utils.el('button', { class: 'btn primary', text: '开始下载' });
    const resetBtn = Utils.el('button', { class: 'btn', text: '清空参数' });
    const actions = Utils.el('div', { class: 'btn-row', style: 'margin-top:6px' }, [submitBtn, resetBtn]);

    async function submit() {
      const form = collect();
      if (form === null) return;
      submitBtn.disabled = true;
      submitBtn.textContent = '提交中…';
      try {
        const res = await API.createTask(adapter.type, 'download', form);
        const task = res.task;
        const queued = task.status === 'queued';
        Utils.toast(queued
          ? `已加入队列（第 ${task.queue_position} 位）：${task.label}`
          : `任务已启动：${task.label}`, 'ok');
        // 输出坞只保持「小」高度，避免遮挡；这样发起后立刻就能看到是否成功启动
        // 把当前状态一并传进去：已结束的“关闭已完成”按钮立即就能点
        LogView.open(task.id, task.label, { status: task.status });
        state.tabs.get(adapter.type)?.taskList.loadTasks();
      } catch (err) {
        Utils.toast(`提交失败：${Utils.errorMessage(err)}`, 'error', 8000);
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = '开始下载';
      }
    }

    submitBtn.addEventListener('click', submit);
    resetBtn.addEventListener('click', () => {
      for (const { field, input } of fields) {
        if (field.type === 'bool') input.checked = !!field.default;
        else input.value = field.default !== undefined ? field.default : '';
      }
      syncVisibility();
    });

    syncVisibility();
    return { collect, actions, fields };
  }

  // ---------------------------------------------------------------- 任务

  async function loadAllTasks() {
    for (const [, tab] of state.tabs) {
      try { await tab.taskList.loadTasks(); } catch { /* 单个失败不影响其他 */ }
    }
    updateRunningBadge();
  }

  function updateRunningBadge() {
    let running = 0;
    for (const [, tab] of state.tabs) {
      for (const task of tab.taskList.state.tasks) {
        if (task.status === 'running' || task.status === 'queued') running++;
      }
    }
    state.runningCount = running;
    const badge = document.getElementById('running-badge');
    badge.hidden = running === 0;
    badge.textContent = `${running} 个任务进行中`;
    Notify.setRunning(running);

    for (const button of Utils.$$('#tabs button')) {
      const tab = state.tabs.get(button.dataset.type);
      const busy = tab && tab.taskList.state.tasks.some(
        (t) => t.status === 'running' || t.status === 'queued');
      const dot = button.querySelector('.dot');
      if (busy && !dot) button.append(Utils.el('span', { class: 'dot' }));
      if (!busy && dot) dot.remove();
    }
  }

  // ---------------------------------------------------------------- 系统信息

  async function refreshSysinfo() {
    let data;
    try {
      data = await API.sysinfo();
    } catch (err) {
      if (err && err.unauthorized) return;
      return;
    }
    renderSysinfo(data);
    renderDiskbar(data);
    renderSpeeds(data);
    updateOpenButtons(data.platform);
    updateRunningBadge();
  }

  /** 只有前后端在同一操作系统时，「打开目录」才有意义（打开的是后端机器的文件管理器）。 */
  function detectFrontendOs() {
    const platform = (navigator.userAgentData && navigator.userAgentData.platform)
      || navigator.platform || '';
    const text = `${platform} ${navigator.userAgent || ''}`;
    if (/win/i.test(text)) return 'Windows';
    if (/mac|iphone|ipad/i.test(text)) return 'Darwin';
    if (/linux|x11/i.test(text)) return 'Linux';
    return 'unknown';
  }

  function updateOpenButtons(platform) {
    const backend = platform || {};
    const same = backend.system && backend.system === detectFrontendOs();
    state.canOpen = !!(backend.can_open_files && same);
    for (const [, tab] of state.tabs) {
      tab.openDirBtn.hidden = !state.canOpen;
      tab.taskList.setCanOpen(state.canOpen);
    }
  }

  function renderSysinfo(data) {
    const box = document.getElementById('sysinfo');
    box.innerHTML = '';
    const p = data.platform || {};
    const py = data.python || {};
    box.append(chip(`${p.system || '?'} ${p.release || ''}`, ''));
    box.append(chip(`Python ${py.version || '?'}`, ''));
    for (const [type, probe] of Object.entries(data.probes || {})) {
      const label = typeLabel(type);
      const ok = probe && probe.ok;
      box.append(chip(`${ok ? '✓' : '✗'} ${label}`, ok ? 'ok' : 'bad',
        (probe?.problems || []).join('\n') || (probe?.project_dir || '')));
    }
  }

  function chip(text, cls, title) {
    return Utils.el('span', { class: `chip ${cls || ''}`, text, title: title || '' });
  }

  function renderDiskbar(data) {
    const bar = document.getElementById('diskbar');
    bar.innerHTML = '';
    for (const disk of data.disks || []) {
      bar.append(Utils.el('span', {
        class: 'disk-chip' + (disk.warn ? ' warn' : ''),
        title: disk.path,
      }, [
        Utils.el('b', { text: disk.label || '' }), ' ',
        Utils.el('span', {
          text: `剩余 ${disk.free_gb} GB / 共 ${(disk.total / 1024 ** 3).toFixed(0)} GB（已用 ${disk.used_percent}%）`,
        }),
      ]));
    }
  }

  function renderSpeeds(data) {
    const bar = document.getElementById('diskbar');
    const speeds = data.speeds || [];
    if (!speeds.length) return;
    for (const speed of speeds) {
      bar.append(Utils.el('span', { class: 'disk-chip', title: speed.target }, [
        Utils.el('b', { text: speed.speed_text }),
        ` ${speed.label || ''} （${speed.size_text}）`,
      ]));
    }
  }

  function typeLabel(type) {
    const found = state.adapters.find((a) => a.type === type);
    return found ? found.name : type;
  }

  // ---------------------------------------------------------------- 全局事件

  function subscribeGlobalEvents() {
    const connect = () => {
      API.globalEvents({
        task_created: (task) => { Utils.toast(`任务已创建：${task.label}`, 'info'); },
        task_started: (task) => {
          // 排队任务在前一个结束后会自动开始，这里同样聚焦其输出
          LogView.open(task.id, task.label, { status: task.status });
          const tab = state.tabs.get(task.type);
          if (tab) tab.taskList.loadTasks();
          updateRunningBadge();
        },
        task_finished: (task) => {
          Notify.handleEvent('task_finished', task);
          const tab = state.tabs.get(task.type);
          if (tab) {
            tab.taskList.loadTasks();
            tab.taskList.scan();
          }
          updateRunningBadge();
        },
        task_failed: (task) => {
          Notify.handleEvent('task_failed', task);
          const tab = state.tabs.get(task.type);
          if (tab) tab.taskList.loadTasks();
          updateRunningBadge();
        },
        error: () => { /* EventSource 自动重连 */ },
      });
    };
    connect();
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
