/**
 * result-page.js — ResultPage 逻辑
 *
 * 负责：
 *   - 从 sessionStorage 读取游戏结果
 *   - 根据结果显示胜利/失败动画和文字
 *   - 启动自动跳转计时器
 *   - 处理"再来一次"按钮点击
 *   - 失败时跳转到错词页（wrong-words.html）
 */

let autoReturnTimer = null;
let gameResult = 'fail';

function init() {
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
 * 根据游戏结果决定跳转目标：
 * - 失败 → wrong-words.html（错词页）
 * - 胜利 → start.html
 */
function navigateNext() {
  sessionStorage.removeItem('gameResult');
  sessionStorage.removeItem('gameState');

  if (gameResult === 'fail') {
    window.location.href = 'wrong-words.html';
  } else {
    window.location.href = 'start.html';
  }
}

document.addEventListener('DOMContentLoaded', init);
