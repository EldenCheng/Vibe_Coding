/* 下载器配置表单（v0.2.0 起在弹窗中显示，不再常驻占用页面空间）。
   把后端返回的 config schema 渲染成表单，支持保存与恢复备份。
   敏感字段（cookies、Authorization 等）不会从后端回传明文，只显示「已设置」，
   提交时留空表示不修改。 */

window.ConfigForm = (function () {

  function create(typeId, options = {}) {
    // 注意：root 是一个普通容器（放进模态框的 body），不再是 <details class="card">
    const root = Utils.el('div');

    const state = { fields: [], path: '', backups: [], loaded: false, exists: false, extra: {} };

    const statusLine = Utils.el('div', { class: 'faint' });
    const grid = Utils.el('div', { class: 'grid2' });
    const extraBox = Utils.el('details', {}, [
      Utils.el('summary', { text: '未在表单中声明的字段（只读）' }),
      Utils.el('pre', { class: 'mono faint' }),
    ]);
    extraBox.hidden = true;

    const saveBtn = Utils.el('button', { class: 'btn primary', text: '保存配置', disabled: true });
    const reloadBtn = Utils.el('button', { class: 'btn', text: '重新读取' });
    const restoreBtn = Utils.el('button', { class: 'btn', text: '恢复最近备份', disabled: true });
    const backupInfo = Utils.el('span', { class: 'faint' });

    const actions = Utils.el('div', { class: 'btn-row', style: 'margin-top:14px' }, [
      saveBtn, reloadBtn, restoreBtn, Utils.el('span', { class: 'spacer' }), backupInfo,
    ]);

    root.append(Utils.el('div', { class: 'faint', text: '配置文件路径：' }), statusLine, grid, extraBox, actions);

    saveBtn.addEventListener('click', async () => {
      const patch = collect();
      if (patch === null) return;
      saveBtn.disabled = true;
      saveBtn.textContent = '保存中…';
      try {
        const res = await API.putConfig(typeId, patch);
        Utils.toast(`配置已保存${res.backup ? `（已备份为 ${res.backup}）` : ''}`, 'ok');
        await load();
        if (options.onSaved) options.onSaved(res);
      } catch (err) {
        Utils.toast(`保存失败：${Utils.errorMessage(err)}`, 'error', 8000);
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '保存配置';
      }
    });

    reloadBtn.addEventListener('click', () => load());

    restoreBtn.addEventListener('click', async () => {
      if (!confirm('确定用最近一次备份覆盖当前配置吗？当前配置会先被备份。')) return;
      try {
        const res = await API.restoreConfig(typeId);
        Utils.toast(`已恢复备份 ${res.restored}`, 'ok');
        await load();
        if (options.onSaved) options.onSaved(res);
      } catch (err) {
        Utils.toast(`恢复失败：${Utils.errorMessage(err)}`, 'error');
      }
    });

    function renderFields(data) {
      grid.textContent = '';
      state.fields = data.fields || [];
      for (const field of state.fields) {
        grid.append(renderField(field));
      }
      const extra = data.extra || {};
      const keys = Object.keys(extra);
      if (keys.length) {
        extraBox.hidden = false;
        extraBox.querySelector('pre').textContent = JSON.stringify(extra, null, 2);
      } else {
        extraBox.hidden = true;
      }
    }

    function renderField(field) {
      const inputId = `cfg-${typeId}-${field.key.replace(/\./g, '-')}`;
      let input;
      const sensitiveSet = field.is_sensitive && field.is_set;

      if (field.type === 'bool') {
        input = Utils.el('input', { type: 'checkbox', id: inputId });
        input.checked = !!field.value;
        input.dataset.key = field.key;
        input.dataset.type = 'bool';
      } else if (field.type === 'select') {
        input = Utils.el('select', { id: inputId });
        for (const opt of field.options || []) {
          input.append(Utils.el('option', { value: opt.value, text: opt.label }));
        }
        input.value = field.value ?? field.default ?? '';
        input.dataset.key = field.key;
        input.dataset.type = 'select';
      } else if (field.type === 'json') {
        input = Utils.el('textarea', { id: inputId, spellcheck: 'false' });
        if (sensitiveSet) {
          input.placeholder = '已设置（留空表示不修改）';
          input.dataset.leaveBlank = '1';
        } else {
          input.value = field.value === undefined || field.value === null
            ? '' : JSON.stringify(field.value, null, 2);
        }
        input.dataset.key = field.key;
        input.dataset.type = 'json';
      } else {
        const isNumber = field.type === 'number' || field.type === 'float';
        input = Utils.el('input', {
          type: isNumber ? 'number' : 'text',
          id: inputId,
          step: field.type === 'float' ? 'any' : null,
        });
        if (sensitiveSet) {
          input.type = 'password';
          input.placeholder = '已设置（留空表示不修改）';
          input.dataset.leaveBlank = '1';
        } else {
          input.value = field.value ?? '';
        }
        input.dataset.key = field.key;
        input.dataset.type = field.type || 'text';
      }

      const label = Utils.el('label', { for: inputId }, [
        document.createTextNode(field.label),
        field.required ? Utils.el('span', { class: 'req', text: '*' }) : null,
      ]);
      const wrap = Utils.el('div', { class: 'field' }, [label, input]);
      if (field.help) wrap.append(Utils.el('div', { class: 'help', text: field.help }));
      if (field.is_sensitive) {
        wrap.append(Utils.el('div', {
          class: 'help',
          text: sensitiveSet ? '敏感字段：已设置，留空则保持不变' : '敏感字段：未设置',
        }));
      }
      return wrap;
    }

    /** 收集表单值；类型转换交给后端校验，这里只把 JSON 文本先解析出来 */
    function collect() {
      const patch = {};
      for (const input of Utils.$$('input,select,textarea', grid)) {
        const key = input.dataset.key;
        if (!key) continue;
        const type = input.dataset.type;
        if (type === 'bool') { patch[key] = input.checked; continue; }
        const raw = input.value;
        if (input.dataset.leaveBlank && raw === '') continue;   // 敏感字段留空 = 不改
        if (type === 'json') {
          if (raw.trim() === '') continue;
          try { patch[key] = JSON.parse(raw); }
          catch {
            Utils.toast(`「${key}」不是合法的 JSON`, 'error');
            return null;
          }
          continue;
        }
        if (type === 'number' || type === 'float') {
          if (raw === '') continue;
          const num = Number(raw);
          if (Number.isNaN(num)) { Utils.toast(`「${key}」需要数字`, 'error'); return null; }
          patch[key] = num;
          continue;
        }
        patch[key] = raw;
      }
      return patch;
    }

    async function load() {
      try {
        const data = await API.getConfig(typeId);
        state.loaded = true;
        state.path = data.path;
        state.exists = !!data.exists;
        state.backups = data.backups || [];
        statusLine.textContent = data.exists ? (data.path || '') : `${data.path}（文件不存在，保存后会创建）`;
        renderFields(data);
        saveBtn.disabled = false;
        restoreBtn.disabled = !state.backups.length;
        backupInfo.textContent = state.backups.length
          ? `${state.backups.length} 个备份，最新：${state.backups[0]}`
          : '暂无备份';
      } catch (err) {
        statusLine.textContent = `读取配置失败：${Utils.errorMessage(err)}`;
      }
    }

    load();
    return { root, load, isLoaded: () => state.loaded };
  }

  return { create };
})();
