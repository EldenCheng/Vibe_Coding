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
 *   - 用户昵称输入 / Cookie 自动登录
 */

import { DataSourceConfig } from './data-source-config.js';
import { UserManager } from './user-manager.js';

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
  setupNicknameModal();
  setupUserSelectModal();
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

// 成就显示（已移到 UserPage，此处不再展示）

function setupEventListeners() {
  const select = document.getElementById('scope-select');
  const startBtn = document.getElementById('start-btn');

  select.addEventListener('change', () => {
    updateStartButton();
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

  // 检测是否有未过期的 cookie 用户
  const lastUser = UserManager.getLastUser();
  if (lastUser) {
    // 直接使用上次用户
    proceedToUserPage(lastUser.nickname);
  } else {
    // 检查是否有多个用户，展示用户选择
    const allUsers = UserManager.getAllUsers();
    const userNames = Object.keys(allUsers);
    
    if (userNames.length > 0) {
      showUserSelectModal(userNames);
    } else {
      showNicknameModal();
    }
  }
}

function showUserSelectModal(userNames) {
  const modal = document.getElementById('user-select-modal');
  const list = document.getElementById('user-list');
  list.innerHTML = '';

  userNames.forEach(name => {
    const btn = document.createElement('button');
    btn.className = 'user-select-btn';
    btn.textContent = name;
    btn.addEventListener('click', () => {
      modal.classList.add('hidden');
      proceedToUserPage(name);
    });
    list.appendChild(btn);
  });

  modal.classList.remove('hidden');
}

function showNicknameModal() {
  const modal = document.getElementById('nickname-modal');
  const input = document.getElementById('nickname-input');
  input.value = '';
  document.getElementById('nickname-error').style.display = 'none';
  modal.classList.remove('hidden');
  input.focus();
}

function setupNicknameModal() {
  const confirmBtn = document.getElementById('nickname-confirm-btn');
  const input = document.getElementById('nickname-input');
  const errorEl = document.getElementById('nickname-error');

  const handleConfirm = () => {
    const nickname = input.value.trim();
    if (!nickname) {
      errorEl.textContent = '请输入昵称';
      errorEl.style.display = '';
      return;
    }
    if (nickname.length > 20) {
      errorEl.textContent = '昵称不能超过 20 个字符';
      errorEl.style.display = '';
      return;
    }

    const user = UserManager.getUser(nickname);
    if (!user) {
      UserManager.createUser(nickname);
    }

    document.getElementById('nickname-modal').classList.add('hidden');
    proceedToUserPage(nickname);
  };

  confirmBtn.addEventListener('click', handleConfirm);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') handleConfirm();
  });
}

function setupUserSelectModal() {
  document.getElementById('new-user-btn').addEventListener('click', () => {
    document.getElementById('user-select-modal').classList.add('hidden');
    showNicknameModal();
  });
}

function proceedToUserPage(nickname) {
  UserManager.setLastUser(nickname);
  sessionStorage.setItem('crossword-current-user', nickname);
  window.location.href = `user.html?user=${encodeURIComponent(nickname)}`;
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
