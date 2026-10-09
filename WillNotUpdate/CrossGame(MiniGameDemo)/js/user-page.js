/**
 * user-page.js — 用户页面逻辑
 *
 * 显示用户统计数据、提供继续/错词表/重置/删除操作
 */

import { UserManager } from './user-manager.js';
import { qs } from './utils.js';

const PAGE_SIZE = 20;
let currentPage = 0;
let currentUser = '';

function init() {
  currentUser = getCurrentUser();
  if (!currentUser) {
    window.location.href = 'start.html';
    return;
  }

  renderUserInfo();
  setupEventListeners();
}

function getCurrentUser() {
  try {
    const fromSession = sessionStorage.getItem('crossword-current-user');
    if (fromSession) return fromSession;
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get('user');
    if (fromUrl) {
      sessionStorage.setItem('crossword-current-user', fromUrl);
      return fromUrl;
    }
    return '';
  } catch (e) {
    return '';
  }
}

function renderUserInfo() {
  const user = UserManager.getUser(currentUser);
  if (!user) {
    window.location.href = 'start.html';
    return;
  }

  document.getElementById('user-nickname').textContent = currentUser;

  const passedCount = user.progress.passedLevels.length;
  const failedCount = user.progress.failedLevels.length;
  const wrongCount = Object.keys(user.wrongWords || {}).length;

  document.getElementById('stat-passed').textContent = passedCount;
  document.getElementById('stat-failed').textContent = failedCount;
  document.getElementById('stat-wrong-words').textContent = wrongCount;

  const continueBtn = document.getElementById('continue-btn');
  const hasProgress = passedCount > 0 || failedCount > 0;
  if (hasProgress) {
    continueBtn.textContent = '继续游戏';
  } else {
    continueBtn.textContent = '开始游戏';
  }

  const wrongBtn = document.getElementById('wrong-words-btn');
  wrongBtn.style.display = wrongCount > 0 ? '' : 'none';

  const resetBtn = document.getElementById('reset-btn');
  resetBtn.style.display = hasProgress ? '' : 'none';
}

function setupEventListeners() {
  qs('#continue-btn').addEventListener('click', handleContinue);
  qs('#wrong-words-btn').addEventListener('click', handleWrongWords);
  qs('#reset-btn').addEventListener('click', handleReset);
  qs('#delete-btn').addEventListener('click', handleDelete);
  qs('#switch-user-btn').addEventListener('click', handleSwitchUser);

  // 错词表弹窗事件
  qs('#modal-close-top').addEventListener('click', closeWrongWordsModal);
  qs('#prev-page-btn').addEventListener('click', () => changePage(-1));
  qs('#next-page-btn').addEventListener('click', () => changePage(1));

  // 重置确认弹窗事件
  qs('#reset-confirm-btn').addEventListener('click', confirmReset);
  qs('#reset-cancel-btn').addEventListener('click', closeResetModal);

  // 删除确认弹窗事件
  qs('#delete-confirm-btn').addEventListener('click', confirmDelete);
  qs('#delete-cancel-btn').addEventListener('click', closeDeleteModal);
}

/**
 * 继续/开始游戏
 * 保存用户到 sessionStorage，跳转到 game.html
 */
function handleContinue() {
  sessionStorage.setItem('crossword-current-user', currentUser);
  window.location.href = `game.html?scope=小学&user=${encodeURIComponent(currentUser)}`;
}

/**
 * 错词表
 */
function handleWrongWords() {
  currentPage = 0;
  renderWrongWordsTable();
  qs('#wrong-words-modal').classList.remove('hidden');
}

function renderWrongWordsTable() {
  const allWords = UserManager.getWrongWordsList(currentUser);
  const totalPages = Math.ceil(allWords.length / PAGE_SIZE) || 1;

  if (currentPage >= totalPages) currentPage = totalPages - 1;
  if (currentPage < 0) currentPage = 0;

  const start = currentPage * PAGE_SIZE;
  const pageWords = allWords.slice(start, start + PAGE_SIZE);
  const tbody = qs('#wrong-words-table-body');
  tbody.innerHTML = '';

  pageWords.forEach(item => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="ww-word">${item.word}</td>
      <td class="ww-meaning">${item.meaning}</td>
      <td class="ww-count">${item.count}</td>
    `;
    tbody.appendChild(tr);
  });

  // 分页控件
  const pagination = qs('#modal-pagination');
  if (totalPages <= 1) {
    pagination.style.display = 'none';
  } else {
    pagination.style.display = '';
    qs('#page-info').textContent = `第 ${currentPage + 1} / ${totalPages} 页`;
    qs('#prev-page-btn').disabled = currentPage <= 0;
    qs('#next-page-btn').disabled = currentPage >= totalPages - 1;
  }
}

function changePage(delta) {
  currentPage += delta;
  renderWrongWordsTable();
}

function closeWrongWordsModal() {
  qs('#wrong-words-modal').classList.add('hidden');
}

/**
 * 重置
 */
function handleReset() {
  qs('#reset-confirm-modal').classList.remove('hidden');
}

function confirmReset() {
  UserManager.resetProgress(currentUser);
  closeResetModal();
  renderUserInfo();
  showToast('已重置关卡记录');
}

function closeResetModal() {
  qs('#reset-confirm-modal').classList.add('hidden');
}

/**
 * 删除用户
 */
function handleDelete() {
  qs('#delete-nickname-input').value = '';
  qs('#delete-error').style.display = 'none';
  qs('#delete-confirm-modal').classList.remove('hidden');
}

function confirmDelete() {
  const input = qs('#delete-nickname-input').value.trim();
  if (input !== currentUser) {
    qs('#delete-error').style.display = '';
    return;
  }

  UserManager.deleteUser(currentUser);
  UserManager.clearLastUser();
  sessionStorage.removeItem('crossword-current-user');
  closeDeleteModal();
  showToast('用户已删除');
  setTimeout(() => {
    window.location.href = 'start.html';
  }, 1000);
}

function closeDeleteModal() {
  qs('#delete-confirm-modal').classList.add('hidden');
}

/**
 * 切换用户
 */
function handleSwitchUser() {
  sessionStorage.removeItem('crossword-current-user');
  window.location.href = 'start.html';
}

function showToast(message) {
  const toast = document.getElementById('message-toast');
  toast.textContent = message;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2000);
}

document.addEventListener('DOMContentLoaded', init);
