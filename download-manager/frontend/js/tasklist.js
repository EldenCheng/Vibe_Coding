/* 下载列表（v0.2.0 重构）：
   - 「任务与队列」卡片：主视觉，限高可展开；排队任务显示队列位置；
   - 「已下载的产物」卡片：单独刷新，限高可展开；产物行可打开目录；
   两处都只在点「刷新」时才去读磁盘。 */

window.TaskList = (function () {

  function create(typeId, options = {}) {
    const root = Utils.el('div');
    const canOpen = options.canOpen || (() => false);
    const outputRoot = options.outputRoot || (() => '');

    const state = { tasks: [], items: [], scannedAt: null, error: '', canOpen: false, sort: { key: null, dir: 1 } };

    // ==================== 任务与队列 ====================

    const queueHint = Utils.el('span', { class: 'hint' });
    const taskExpandBtn = Utils.el('button', { class: 'btn small ghost', text: '展开' });
    const taskRefreshBtn = Utils.el('button', { class: 'btn small', text: '刷新任务' });
    const taskHead = Utils.el('div', { class: 'card-head static' }, [
      Utils.el('span', { text: '任务与队列' }),
      queueHint,
      Utils.el('span', { class: 'spacer' }),
      taskExpandBtn, taskRefreshBtn,
    ]);
    const taskArea = Utils.el('div', { class: 'card-body scroll-area' });
    const tasksCard = Utils.el('div', { class: 'card' }, [taskHead, taskArea]);

    taskRefreshBtn.addEventListener('click', () => loadTasks());
    wireExpand(taskExpandBtn, taskArea);

    // ==================== 已下载的产物 ====================

    const scanInfo = Utils.el('span', { class: 'faint' });
    const scanExpandBtn = Utils.el('button', { class: 'btn small ghost', text: '展开' });
    const scanRefreshBtn = Utils.el('button', { class: 'btn primary small', text: '刷新产物' });
    const openRootBtn = Utils.el('button', { class: 'btn small', text: '📂 打开下载目录', hidden: true });
    const scanHead = Utils.el('div', { class: 'card-head static' }, [
      Utils.el('span', { text: '📋 已下载的产物' }),
      scanInfo,
      Utils.el('span', { class: 'spacer' }),
      openRootBtn, scanExpandBtn, scanRefreshBtn,
    ]);
    const productArea = Utils.el('div', { class: 'card-body scroll-area' });
    const productsCard = Utils.el('div', { class: 'card' }, [scanHead, productArea]);

    scanRefreshBtn.addEventListener('click', () => scan());
    openRootBtn.addEventListener('click', () => openPath(outputRoot()));
    wireExpand(scanExpandBtn, productArea);

    root.append(tasksCard, productsCard);

    // ==================== 工具函数 ====================

    function wireExpand(button, area) {
      button.addEventListener('click', () => {
        area.classList.toggle('expanded');
        button.textContent = area.classList.contains('expanded') ? '收起' : '展开';
      });
    }

    async function openPath(path, select) {
      if (!path) { Utils.toast('没有可打开的目录', 'warn'); return; }
      try {
        const res = await API.openPath(path, select);
        Utils.toast(res.message || '已打开目录', 'ok');
      } catch (err) {
        Utils.toast(`打开失败：${Utils.errorMessage(err)}`, 'error', 8000);
      }
    }

    function statusBadge(task) {
      return Utils.el('span', {
        class: `status ${task.status}`,
        text: task.status_label || task.status,
      });
    }

    function progressCell(progress, status) {
      const prog = progress || {};
      const done = prog.done, total = prog.total;
      if (done === null || done === undefined || !total) {
        return Utils.el('span', { class: 'faint', text: prog.summary || '-' });
      }
      const pct = Utils.percent(done, total);
      const cls = status === 'completed' ? 'done' : (prog.failed ? 'partial' : '');
      return Utils.el('div', {}, [
        Utils.el('span', { text: `${done}/${total} ${prog.unit || ''}` + (prog.failed ? `  失败 ${prog.failed}` : '') }),
        Utils.el('div', { class: `bar ${cls}` }, [Utils.el('i', { style: `width:${pct}%` })]),
      ]);
    }

    // ==================== 任务表 ====================

    function renderTasks() {
      taskArea.textContent = '';
      const running = state.tasks.filter((t) => t.status === 'running').length;
      const queued = state.tasks.filter((t) => t.status === 'queued').length;
      queueHint.textContent = state.tasks.length
        ? `运行 ${running} · 排队 ${queued} · 共 ${state.tasks.length}` : '';

      if (!state.tasks.length) {
        taskArea.append(Utils.el('div', { class: 'empty', text: '该下载器暂无任务记录' }));
        return;
      }
      const table = Utils.el('table');
      table.append(Utils.el('thead', {}, [Utils.el('tr', {}, [
        Utils.el('th', { text: '状态' }),
        Utils.el('th', { text: '任务' }),
        Utils.el('th', { text: '进度' }),
        Utils.el('th', { text: '说明' }),
        Utils.el('th', { class: 'hide-sm', text: '开始时间' }),
        Utils.el('th', { text: '' }),
      ])]));
      const tbody = Utils.el('tbody');
      for (const task of state.tasks) {
        const actions = Utils.el('td', { class: 'actions' });
        actions.append(Utils.el('button', {
          class: 'btn small', text: '日志',
          onclick: () => LogView.open(task.id, task.label, { status: task.status, after: 0 }),
        }));
        if (task.status === 'running') {
          actions.append(Utils.el('button', {
            class: 'btn small danger', text: '停止', onclick: () => stopTask(task.id),
          }));
        } else if (task.status === 'queued') {
          actions.append(Utils.el('button', {
            class: 'btn small danger', text: '取消排队', onclick: () => stopTask(task.id),
          }));
        } else {
          actions.append(Utils.el('button', {
            class: 'btn small', text: '续跑',
            title: '用相同参数重新发起，已完成的会自动跳过',
            onclick: () => resumeTask(task),
          }));
          actions.append(Utils.el('button', {
            class: 'btn small ghost', text: '移除', onclick: () => removeTask(task.id),
          }));
        }
        const queueTag = task.queue_position
          ? Utils.el('span', { class: 'faint', text: `队列第 ${task.queue_position} 位` }) : null;
        tbody.append(Utils.el('tr', {}, [
          Utils.el('td', {}, [statusBadge(task)]),
          Utils.el('td', { class: 'ellipsis', style: 'max-width:280px', title: task.label },
            [task.label, queueTag ? [' ', queueTag] : null]),
          Utils.el('td', { style: 'min-width:150px' }, [progressCell(task.progress, task.status)]),
          Utils.el('td', { class: 'ellipsis', style: 'max-width:320px', title: task.message },
            [task.message || '']),
          Utils.el('td', { class: 'hide-sm faint nowrap', text: Utils.time(task.created_at) }),
          actions,
        ]));
      }
      table.append(tbody);
      taskArea.append(table);
    }

    async function loadTasks() {
      try {
        const data = await API.listTasks(typeId);
        state.tasks = data.tasks || [];
        renderTasks();
        if (options.onTasks) options.onTasks(state.tasks);
      } catch (err) {
        taskArea.textContent = '';
        taskArea.append(Utils.el('div', { class: 'empty', text: `读取任务失败：${Utils.errorMessage(err)}` }));
      }
    }

    async function stopTask(id) {
      if (!confirm('确定停止这个任务吗？（会终止整棵子进程树，包括浏览器/ffmpeg）')) return;
      try {
        await API.stopTask(id);
        Utils.toast('已请求停止', 'warn');
        loadTasks();
      } catch (err) {
        Utils.toast(`停止失败：${Utils.errorMessage(err)}`, 'error');
      }
    }

    async function resumeTask(task) {
      const form = options.collectForm ? options.collectForm() : null;
      if (!form) { Utils.toast('请先在右侧「新建任务」填好参数再续跑', 'warn'); return; }
      try {
        const res = await API.createTask(typeId, 'download', form);
        Utils.toast(`已重新发起（任务 ${res.task.id}），已完成的会自动跳过`, 'ok');
        LogView.open(res.task.id, res.task.label, { status: res.task.status });
        loadTasks();
      } catch (err) {
        Utils.toast(`发起失败：${Utils.errorMessage(err)}`, 'error');
      }
    }

    async function removeTask(id) {
      try {
        await API.removeTask(id);
        loadTasks();
      } catch (err) {
        Utils.toast(`移除失败：${Utils.errorMessage(err)}`, 'error');
      }
    }

    // ==================== 产物排序 ====================

    function progressValue(item) {
      const p = item.progress || {};
      const done = p.done, total = p.total;
      if (typeof done === 'number' && typeof total === 'number' && total > 0) return done / total;
      return -1;   // 无进度信息的排最前（优先看未完成/未核实）
    }

    function sortItems(items) {
      const { key, dir } = state.sort;
      if (!key) return items.slice();
      const arr = items.slice();
      arr.sort((a, b) => {
        let r = 0;
        if (key === 'name') r = String(a.name || '').localeCompare(String(b.name || ''), 'zh');
        else if (key === 'progress') r = progressValue(a) - progressValue(b);
        else if (key === 'size') r = (a.size || 0) - (b.size || 0);
        else if (key === 'mtime') r = (a.mtime || 0) - (b.mtime || 0);
        return r;
      });
      if (dir === -1) arr.reverse();
      return arr;
    }

    /** 可点击的排序列头；点击排序，再点同列切换升/降序。 */
    function sortableTh(label, key, cls) {
      const th = Utils.el('th', { class: cls || '' });
      const active = state.sort.key === key;
      const btn = Utils.el('button', {
        class: 'sort-btn' + (active ? ' active' : ''),
        text: label + (active ? (state.sort.dir === 1 ? ' ▲' : ' ▼') : ''),
        title: '点击排序',
      });
      btn.addEventListener('click', () => {
        if (state.sort.key === key) {
          state.sort.dir = -state.sort.dir;
        } else {
          state.sort.key = key;
          // 首次点击的默认方向：名称/进度升序，大小/修改时间降序
          state.sort.dir = (key === 'name' || key === 'progress') ? 1 : -1;
        }
        renderItems();
      });
      th.append(btn);
      return th;
    }

    // ==================== 产物表 ====================

    function renderItems() {
      productArea.textContent = '';
      if (state.error) {
        productArea.append(Utils.el('div', { class: 'banner err', text: state.error, style: 'margin:12px' }));
        return;
      }
      if (!state.items.length) {
        productArea.append(Utils.el('div', {
          class: 'empty',
          text: state.scannedAt ? '该目录下没有发现产物' : '点上方「刷新产物」读取下载目录',
        }));
        return;
      }
      const table = Utils.el('table');
      table.append(Utils.el('thead', {}, [Utils.el('tr', {}, [
        sortableTh('名称', 'name'),
        sortableTh('进度', 'progress'),
        sortableTh('大小', 'size', 'hide-sm'),
        sortableTh('修改时间', 'mtime', 'hide-sm'),
        Utils.el('th', { text: '' }),
      ])]));
      const tbody = Utils.el('tbody');
      for (const item of sortItems(state.items)) {
        const prog = item.progress || {};
        const actions = Utils.el('td', { class: 'actions' });
        for (const action of (options.actions || [])) {
          actions.append(Utils.el('button', {
            class: 'btn small' + (action.primary ? ' primary' : ''),
            text: action.label,
            title: action.help || '',
            onclick: () => runAction(action.action, item),
          }));
        }
        if (prog.failed) {
          actions.append(Utils.el('button', {
            class: 'btn small ghost', text: `查看失败(${prog.failed})`,
            onclick: () => showDetail(item),
          }));
        }
        if (state.canOpen) {
          actions.append(Utils.el('button', {
            class: 'btn small ghost', text: '📂 打开',
            title: '在后端机器的文件管理器中打开该目录',
            onclick: () => openPath(item.path, true),
          }));
        }
        let progressNode;
        if (prog.done === null || prog.done === undefined) {
          progressNode = Utils.el('span', { class: 'faint', text: prog.summary || '无进度信息' });
        } else {
          const pct = Utils.percent(prog.done, prog.total);
          const cls = prog.status === 'completed' ? 'done' : (prog.failed ? 'partial' : '');
          progressNode = Utils.el('div', {}, [
            Utils.el('span', {
              class: `status ${prog.status || ''}`, text: prog.status === 'completed' ? '已完成'
                : (prog.failed ? '部分失败' : '未完成'),
            }),
            ' ',
            Utils.el('span', {
              text: `${prog.done}/${prog.total ?? '?'} ${prog.unit || ''}`
                + (prog.failed ? `  失败 ${prog.failed}` : ''),
            }),
            pct !== null ? Utils.el('div', { class: `bar ${cls}` }, [Utils.el('i', { style: `width:${pct}%` })]) : null,
          ]);
        }
        tbody.append(Utils.el('tr', {}, [
          Utils.el('td', { class: 'ellipsis', style: 'max-width:340px', title: item.path }, [
            Utils.el('div', { text: item.name }),
            Utils.el('div', { class: 'faint ellipsis', text: item.path }),
          ]),
          Utils.el('td', { style: 'min-width:160px' }, [progressNode]),
          Utils.el('td', { class: 'hide-sm faint nowrap', text: item.size_text }),
          Utils.el('td', { class: 'hide-sm faint nowrap', text: item.mtime_text }),
          actions,
        ]));
      }
      table.append(tbody);
      productArea.append(table);
    }

    async function scan() {
      scanRefreshBtn.disabled = true;
      scanRefreshBtn.textContent = '扫描中…';
      try {
        const data = await API.scanDownloads(typeId);
        state.items = data.items || [];
        state.scannedAt = data.scanned_at;
        state.error = '';
        scanInfo.textContent = `共 ${state.items.length} 项 · ${(data.roots || []).join(' | ')}`;
      } catch (err) {
        state.error = `扫描失败：${Utils.errorMessage(err)}`;
        state.items = [];
      } finally {
        scanRefreshBtn.disabled = false;
        scanRefreshBtn.textContent = '刷新产物';
        renderItems();
      }
    }

    async function runAction(action, item) {
      const target = {
        id: item.id, name: item.name, path: item.path,
        url: (item.progress && (item.progress.gallery_url || item.progress.list_url))
             || item.extra?.url || '',
        book_id: item.extra?.book_id || '',
        book_arg: item.extra?.book_arg || '',
      };
      // v0.5.1 守门：该产物没有任何可恢复的下载地址（如已完成的散文件，
      // 本来也无事可续跑）——直接提示，不调后端（后端只会报"缺少地址"）。
      // 通用规则，四个下载器都受益。
      if (!target.url && !target.book_id && !target.book_arg) {
        Utils.toast('该产物没有可恢复的下载地址（如已完成的散文件），无需续跑', 'warn');
        return;
      }
      const label = (options.actions || []).find((a) => a.action === action)?.label || action;
      if (!confirm(`确定对「${item.name}」执行「${label}」吗？`)) return;
      try {
        const res = await API.downloadAction(typeId, action, target);
        Utils.toast(`已发起：${label}（任务 ${res.task.id}）`, 'ok');
        LogView.open(res.task.id, res.task.label, { status: res.task.status });
        loadTasks();
      } catch (err) {
        Utils.toast(`发起失败：${Utils.errorMessage(err)}`, 'error', 8000);
      }
    }

    async function showDetail(item) {
      try {
        const data = await API.downloadDetail(typeId, item.path);
        const detail = data.detail || {};
        const failed = detail.failed_items || detail.failed || [];
        const box = Utils.el('div', { class: 'banner' });
        box.append(Utils.el('div', { text: '失败明细：' }));
        if (!failed.length) {
          box.append(Utils.el('div', { class: 'faint', text: '没有失败项' }));
        } else {
          const list = Utils.el('ul', { class: 'failed-list' });
          for (const entry of failed.slice(0, 200)) {
            list.append(Utils.el('li', {
              text: typeof entry === 'object'
                ? `${entry.title || entry.index}（索引 ${entry.index}）` : String(entry),
            }));
          }
          box.append(list);
        }
        productArea.prepend(box);
        box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } catch (err) {
        Utils.toast(`读取明细失败：${Utils.errorMessage(err)}`, 'error');
      }
    }

    /** 前后端同 OS 时才显示「打开目录」按钮，由 app.js 在收到 sysinfo 后调用 */
    function setCanOpen(value) {
      value = !!value;
      openRootBtn.hidden = !value;
      if (state.canOpen === value) return;
      state.canOpen = value;
      renderItems();
    }

    renderItems();
    loadTasks();
    return { root, scan, loadTasks, setCanOpen, state };
  }

  return { create };
})();
