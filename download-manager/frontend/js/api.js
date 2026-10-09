/* 后端 API 封装。所有请求自动带上访问令牌。 */

window.API = (function () {
  async function request(method, path, body) {
    const headers = { 'X-Auth-Token': Utils.token };
    const options = { method, headers };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    let resp;
    try {
      resp = await fetch(path, options);
    } catch (err) {
      throw { message: '无法连接到后端服务，请确认服务还在运行' };
    }
    if (resp.status === 401) {
      const data = await resp.json().catch(() => ({}));
      throw { unauthorized: true, ...data };
    }
    const text = await resp.text();
    let data = {};
    if (text) {
      try { data = JSON.parse(text); } catch { data = { raw: text }; }
    }
    if (!resp.ok) {
      throw (data && Object.keys(data).length) ? data : { message: `HTTP ${resp.status}` };
    }
    return data;
  }

  return {
    health: () => fetch('/api/health').then((r) => r.json()),
    sysinfo: () => request('GET', '/api/sysinfo'),
    adapters: () => request('GET', '/api/adapters'),

    getConfig: (type) => request('GET', `/api/adapters/${type}/config`),
    putConfig: (type, patch) => request('PUT', `/api/adapters/${type}/config`, patch),
    restoreConfig: (type, name) => request('POST', `/api/adapters/${type}/config/restore`, { name }),

    createTask: (type, kind, form) => request('POST', '/api/tasks', { type, kind, form }),
    listTasks: (type) => request('GET', `/api/tasks${type ? `?type=${encodeURIComponent(type)}` : ''}`),
    getTask: (id) => request('GET', `/api/tasks/${id}`),
    stopTask: (id) => request('POST', `/api/tasks/${id}/stop`),
    removeTask: (id) => request('DELETE', `/api/tasks/${id}`),
    taskLog: (id, tail) => request('GET', `/api/tasks/${id}/log${tail ? `?tail=${tail}` : ''}`),

    scanDownloads: (type) => request('GET', `/api/downloads/${type}`),
    downloadAction: (type, action, target) =>
      request('POST', `/api/downloads/${type}/action`, { action, target }),
    downloadDetail: (type, path) =>
      request('GET', `/api/downloads/${type}/detail?path=${encodeURIComponent(path)}`),

    /** 在后端本机的文件管理器中打开路径（仅同 OS 时有意义） */
    openPath: (path, select) => request('POST', '/api/system/open', { path, select: !!select }),

    /** SSE：打开即可持续接收；返回 EventSource（调用方负责 close） */
    taskEvents(taskId, handlers) {
      return openStream(`/api/tasks/${taskId}/events`, handlers);
    },
    globalEvents(handlers) {
      return openStream('/api/events', handlers);
    },
  };

  function openStream(path, handlers) {
    const sep = path.includes('?') ? '&' : '?';
    const source = new EventSource(`${path}${sep}token=${encodeURIComponent(Utils.token)}`);
    const known = ['log', 'status', 'event', 'heartbeat', 'hello', 'done',
      'task_created', 'task_started', 'task_finished', 'task_failed'];
    for (const name of known) {
      const handler = handlers[name];
      if (!handler) continue;
      source.addEventListener(name, (evt) => {
        let data = {};
        try { data = JSON.parse(evt.data); } catch { /* 忽略坏帧 */ }
        handler(data);
      });
    }
    source.addEventListener('error', () => {
      // EventSource 会自动重连；这里只通知调用方状态变化
      if (handlers.error) handlers.error();
    });
    return source;
  }
})();
