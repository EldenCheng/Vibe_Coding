/* 任务完成通知：页面标题闪烁 + 桌面通知 + 可选提示音。
   长任务下载完通常人不在页面前，所以这三层都用上。
   移动端浏览器对 Notification 支持不一致，标题闪烁作为兜底始终生效。 */

window.Notify = (function () {
  const state = {
    enabled: localStorage.getItem('dm-notify') !== '0',
    desktop: false,
    runningCount: 0,
    flashTimer: null,
    baseTitle: document.title,
  };

  function init(toggleEl) {
    state.desktop = 'Notification' in window;
    if (toggleEl) {
      toggleEl.checked = state.enabled;
      toggleEl.addEventListener('change', async () => {
        state.enabled = toggleEl.checked;
        localStorage.setItem('dm-notify', state.enabled ? '1' : '0');
        if (state.enabled && state.desktop && Notification.permission === 'default') {
          try { await Notification.requestPermission(); } catch { /* 用户拒绝即可 */ }
        }
      });
    }
  }

  /** 处理一个全局事件（任务创建/开始/结束） */
  function handleEvent(event, task) {
    if (event === 'task_finished' || event === 'task_failed') {
      const status = task.status;
      const label = task.label || task.id;
      const message = task.message || '';
      const kind = status === 'completed' ? 'ok'
        : (status === 'partial_failed' || status === 'completed_unverified') ? 'warn' : 'error';
      const title = status === 'completed' ? '✅ 下载完成'
        : status === 'partial_failed' ? '⚠️ 部分失败'
          : '❌ 任务结束（未完成）';
      fire(`${title}：${label}`, message, kind);
    }
  }

  function fire(title, body, kind = 'ok') {
    Utils.toast(`${title}\n${body}`, kind, 9000);
    if (state.enabled) {
      flashTitle(`【${title}】`);
      beep(kind);
      if (state.desktop && Notification.permission === 'granted') {
        try {
          const n = new Notification(title, { body, tag: 'download-manager' });
          n.onclick = () => { window.focus(); n.close(); };
        } catch { /* 某些浏览器在非安全上下文下会抛错 */ }
      }
    }
  }

  /** 标题闪烁，直到用户回到页面 */
  function flashTitle(prefix) {
    if (state.flashTimer) return;
    let on = false;
    const original = state.baseTitle;
    state.flashTimer = setInterval(() => {
      document.title = on ? original : `${prefix} ${original}`;
      on = !on;
    }, 900);
    const stop = () => {
      if (!state.flashTimer) return;
      clearInterval(state.flashTimer);
      state.flashTimer = null;
      document.title = original;
      window.removeEventListener('focus', stop);
      document.removeEventListener('visibilitychange', onVisible);
    };
    const onVisible = () => { if (!document.hidden) stop(); };
    window.addEventListener('focus', stop);
    document.addEventListener('visibilitychange', onVisible);
  }

  /** 极简提示音，用 WebAudio 生成，不引入音频文件 */
  function beep(kind) {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.type = 'sine';
      const base = kind === 'ok' ? 880 : (kind === 'warn' ? 620 : 420);
      osc.frequency.setValueAtTime(base, ctx.currentTime);
      if (kind === 'ok') osc.frequency.setValueAtTime(base * 1.5, ctx.currentTime + 0.12);
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.34);
      osc.start(); osc.stop(ctx.currentTime + 0.36);
      setTimeout(() => ctx.close(), 600);
    } catch { /* 音频不可用时静默忽略 */ }
  }

  /** 更新运行中任务数（标题里显示，方便切到别的标签页时也能看到） */
  function setRunning(count) {
    state.runningCount = count;
    const original = state.baseTitle;
    document.title = count > 0 ? `(${count}) ${original}` : original;
    state.baseTitle = original;
  }

  return { init, handleEvent, fire, setRunning };
})();
