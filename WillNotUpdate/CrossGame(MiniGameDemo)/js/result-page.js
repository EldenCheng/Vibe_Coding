/**
 * result-page.js — ResultPage 逻辑
 *
 * 负责：
 *   - 从 sessionStorage 读取游戏结果
 *   - 根据结果显示胜利/失败动画和文字
 *   - 启动自动跳转计时器
 *   - 处理"再来一次"按钮点击
 *   - 跳转到用户页面
 */

let autoReturnTimer = null;
let gameResult = 'fail';
let currentUser = '';

function init() {
  const params = new URLSearchParams(window.location.search);
  currentUser = params.get('user') || '';

  const result = loadGameResult();
  gameResult = result.result;

  if (result.result === 'win') {
    showWinState();
  } else {
    showFailState();
  }

  setupEventListeners();
  startAutoReturn();
}

function loadGameResult() {
  try {
    const stored = sessionStorage.getItem('gameResult');
    if (stored) {
      return JSON.parse(stored);
    }
  } catch (err) {
    console.error('读取结果失败:', err);
  }

  return { result: 'fail', errorCount: 0 };
}

function showWinState() {
  const winAnimation = document.getElementById('win-animation');
  const failAnimation = document.getElementById('fail-animation');
  const resultText = document.getElementById('result-text');

  winAnimation.classList.remove('hidden');
  failAnimation.classList.add('hidden');

  resultText.textContent = '太棒了！你全部过关了！';
  resultText.style.color = '#FF6B6B';
}

function showFailState() {
  const winAnimation = document.getElementById('win-animation');
  const failAnimation = document.getElementById('fail-animation');
  const resultText = document.getElementById('result-text');

  winAnimation.classList.add('hidden');
  failAnimation.classList.remove('hidden');

  resultText.textContent = '别灰心，再来一次吧！';
  resultText.style.color = '#5D4037';
}

function setupEventListeners() {
  const retryBtn = document.getElementById('retry-btn');
  retryBtn.addEventListener('click', handleRetry);
}

function startAutoReturn() {
  const delay = Math.floor(Math.random() * 3000) + 2000;

  autoReturnTimer = setTimeout(() => {
    navigateNext();
  }, delay);
}

function handleRetry() {
  if (autoReturnTimer) {
    clearTimeout(autoReturnTimer);
    autoReturnTimer = null;
  }
  navigateNext();
}

/**
 * 无论胜利还是失败，都跳转到用户页面
 */
function navigateNext() {
  sessionStorage.removeItem('gameResult');
  sessionStorage.removeItem('gameState');

  const url = currentUser
    ? `user.html?user=${encodeURIComponent(currentUser)}`
    : 'start.html';
  window.location.href = url;
}

document.addEventListener('DOMContentLoaded', init);
