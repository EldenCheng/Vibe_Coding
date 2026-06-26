/**
 * start-page.js — StartPage 逻辑
 *
 * 负责：
 *   - 加载配置并填充下拉菜单
 *   - 管理难度选择控件状态
 *   - 更新 START 按钮可用性
 *   - 从 localStorage 读取进度，在下拉菜单旁显示星星
 *   - 实现填字棋盘风格字母填入动画循环
 *   - 处理游戏启动流程
 */

import { DataSourceConfig } from './data-source-config.js';

const STORAGE_KEY = 'crossword-game-progress';

// 填字棋盘矩阵（展示填字游戏风格：C-A-T, D-O-G, A-P-P-L-E）
const boardMatrix = [
  'C', 'A', 'T', '', '',
  'O', '', 'O', '', '',
  'W', '', 'G', '', 'A',
  '', '', '', '', 'P',
  'A', 'P', 'P', 'L', 'E'
];

// 填充序列（模拟逐格填入的效果，点亮所有有字母的格子）
// C→A→T→O→O→W→G→A→P→A→P→P→L→E
const fillSequence = [0, 1, 2, 5, 7, 10, 12, 14, 19, 20, 21, 22, 23, 24];

let dataSourceConfig = null;

async function init() {
  initAnimation();
  await loadConfig();
  setupEventListeners();
}

function initAnimation() {
  const board = document.getElementById('board');

  boardMatrix.forEach(letter => {
    const cell = document.createElement('div');
    cell.className = 'letter-cell';
    cell.textContent = letter;
    board.appendChild(cell);
  });

  const cells = board.querySelectorAll('.letter-cell');
  let step = 0;

  function runAnimation() {
    if (step === 0) {
      cells.forEach(c => c.classList.remove('active'));
    }

    if (step < fillSequence.length) {
      cells[fillSequence[step]].classList.add('active');
      step++;
      setTimeout(runAnimation, 400);
    } else {
      setTimeout(() => {
        step = 0;
        runAnimation();
      }, 2000);
    }
  }

  runAnimation();
}

async function loadConfig() {
  const select = document.getElementById('scope-select');
  const configError = document.getElementById('config-error');
  const startBtn = document.getElementById('start-btn');
  const difficultyRadios = document.querySelectorAll('input[name="difficulty"]');

  try {
    dataSourceConfig = await DataSourceConfig.load();
    const entries = dataSourceConfig.getEntries();

    select.innerHTML = '';
    entries.forEach(entry => {
      const option = document.createElement('option');
      option.value = entry.displayName;
      option.textContent = entry.displayName;
      select.appendChild(option);
    });

    if (entries.length > 0) {
      select.value = entries[0].displayName;
    }

    select.disabled = false;
    configError.textContent = '';

    difficultyRadios.forEach(radio => {
      radio.disabled = false;
    });

    updateStartButton();
    updateAchievementDisplay();

  } catch (err) {
    console.error('配置加载失败:', err);
    configError.textContent = '配置加载失败，请刷新重试';
    select.innerHTML = '<option value="">加载失败</option>';
    select.disabled = true;
    startBtn.disabled = true;
  }
}

function updateStartButton() {
  const select = document.getElementById('scope-select');
  const selectedScope = select.value;
  const startBtn = document.getElementById('start-btn');

  if (!selectedScope || !dataSourceConfig) {
    startBtn.disabled = true;
    return;
  }

  const isAvailable = dataSourceConfig.isAvailable(selectedScope);
  startBtn.disabled = !isAvailable;
}

/**
 * 从 localStorage 读取进度，在下拉菜单旁显示星星。
 */
function updateAchievementDisplay() {
  const select = document.getElementById('scope-select');
  const display = document.getElementById('achievement-display');
  const selectedScope = select.value;

  if (!selectedScope || !display) {
    if (display) display.innerHTML = '';
    return;
  }

  const progress = loadProgress(selectedScope);
  if (!progress || progress.total === 0) {
    display.innerHTML = '';
    return;
  }

  const used = progress.usedIds.length;
  const total = progress.total;
  const percent = total > 0 ? used / total : 0;

  let starsHtml = '';
  if (percent >= 1) {
    starsHtml = '⭐⭐⭐';
  } else if (percent >= 0.6) {
    starsHtml = '⭐⭐';
  } else if (percent >= 0.3) {
    starsHtml = '⭐';
  } else {
    starsHtml = '';
  }

  display.innerHTML = starsHtml
    ? `<div class="stars">${starsHtml}</div><div class="progress-text">${used} / ${total} 题</div>`
    : `<div class="progress-text">${used} / ${total} 题</div>`;
}

/**
 * 从 localStorage 读取指定单词库的进度。
 * @param {string} scope
 * @returns {{ usedIds: number[], total: number }|null}
 */
function loadProgress(scope) {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;

    const all = JSON.parse(raw);
    return all[scope] || null;
  } catch (e) {
    return null;
  }
}

function setupEventListeners() {
  const select = document.getElementById('scope-select');
  const startBtn = document.getElementById('start-btn');

  select.addEventListener('change', () => {
    updateStartButton();
    updateAchievementDisplay();
  });

  startBtn.addEventListener('click', handleStartClick);
}

async function handleStartClick() {
  const select = document.getElementById('scope-select');
  const selectedScope = select.value;
  const selectedDifficulty = document.querySelector('input[name="difficulty"]:checked')?.value;

  if (!selectedScope || !selectedDifficulty || !dataSourceConfig) {
    return;
  }

  const path = dataSourceConfig.getPath(selectedScope);
  if (!path) {
    showToast('所选单词库不可用');
    return;
  }

  const loadingIndicator = document.getElementById('loading-indicator');
  loadingIndicator.classList.add('show');

  try {
    const response = await fetch(path);
    if (!response.ok) {
      throw new Error(`加载失败: ${response.status}`);
    }

    const puzzleSets = await response.json();

    if (!Array.isArray(puzzleSets) || puzzleSets.length === 0) {
      throw new Error('关卡数据为空');
    }

    sessionStorage.removeItem('gameState');

    const url = `game.html?scope=${encodeURIComponent(selectedScope)}&difficulty=${selectedDifficulty}`;
    window.location.href = url;

  } catch (err) {
    console.error('启动失败:', err);
    showToast('关卡数据加载失败，请检查网络后重试');
  } finally {
    loadingIndicator.classList.remove('show');
  }
}

function showToast(message) {
  const toast = document.getElementById('message-toast');
  toast.textContent = message;
  toast.classList.add('show');

  setTimeout(() => {
    toast.classList.remove('show');
  }, 2000);
}

document.addEventListener('DOMContentLoaded', init);
