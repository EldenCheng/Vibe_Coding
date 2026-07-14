/**
 * game-controller.js — GameController 模块
 *
 * 负责：
 *   - 加载单个 PuzzleSet JSON 文件
 *   - 读取当前用户，通过 UserManager 获取关卡序列
 *   - 按单词逐一比对答案，错词记录到用户档案
 *   - 每关错词扣减对应次数，3 次机会用完则游戏结束
 *   - 自动进入下一关，失败关卡标记为"不通过"
 *   - 计时器超时处理
 */

import { PuzzleBoard } from './puzzle-board.js';
import { DataSourceConfig } from './data-source-config.js';
import { LetterSelectionPanel } from './letter-selection-panel.js';
import { Timer } from './timer.js';
import { WrongWordModal } from './wrong-word-modal.js';
import { UserManager } from './user-manager.js';
import { sampleWithoutReplacement, checkAnswer, qs } from './utils.js';

const LEVELS_PER_GAME = 3;

/** @type {Object} */
let gameState = {
  scope: '',
  difficulty: '',
  levels: [],
  currentLevelIndex: 0,
  errorCount: 0,
  totalLevels: 0,
  puzzleSets: [],
  currentUser: '',
};

/** @type {PuzzleBoard} */
let puzzleBoard = null;

/** @type {LetterSelectionPanel} */
let letterPanel = null;

/** @type {Timer|null} */
let timer = null;

/** @type {number} */
const MAX_ERRORS = 3;

async function init() {
  puzzleBoard = new PuzzleBoard(document.getElementById('puzzle-board'));
  letterPanel = new LetterSelectionPanel(
    document.getElementById('letter-selection-panel'),
    puzzleBoard
  );

  const wrongWordsModal = new WrongWordModal(
    document.getElementById('wrong-word-modal')
  );
  window.__wrongWordsModal = wrongWordsModal;

  puzzleBoard.setOnLetterRemoved((letter) => {
    letterPanel.restoreLetter(letter);
  });

  const timerDisplay = document.getElementById('timer-display');
  timer = new Timer(timerDisplay, handleTimeout);

  const params = new URLSearchParams(window.location.search);
  const scope = params.get('scope');
  const difficulty = params.get('difficulty') || 'easy';
  const user = params.get('user') || sessionStorage.getItem('crossword-current-user') || '';

  if (!scope || !user) {
    showToast('参数错误，返回首页');
    setTimeout(() => goToStart(), 2000);
    return;
  }

  gameState.scope = scope;
  gameState.difficulty = difficulty;
  gameState.errorCount = 0;
  gameState.currentUser = user;

  try {
    await loadPuzzleSets();
    initLevelSequence();
    loadLevel(0);
    setupEventListeners();
    updateAchievementBadge();

  } catch (err) {
    console.error('游戏初始化失败:', err);
    showToast('关卡数据加载失败，请返回重试');
    setTimeout(() => goToStart(), 2000);
  }
}

/**
 * 从 data-sources.json 获取数据路径，加载全部 PuzzleSet。
 */
async function loadPuzzleSets() {
  const config = await DataSourceConfig.load();
  const path = config.getPath(gameState.scope);

  if (!path) {
    throw new Error('所选单词库不可用');
  }

  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`加载失败: ${response.status}`);
  }

  const puzzleSets = await response.json();

  if (!Array.isArray(puzzleSets) || puzzleSets.length === 0) {
    throw new Error('关卡数据为空');
  }

  gameState.puzzleSets = puzzleSets;
}

/**
 * 通过 UserManager 生成含不通过关卡的序列。
 */
function initLevelSequence() {
  const allPuzzles = gameState.puzzleSets;

  if (allPuzzles.length < LEVELS_PER_GAME) {
    throw new Error('关卡数据不足，无法开始游戏');
  }

  const levelIds = UserManager.generateLevelSequence(
    gameState.currentUser,
    gameState.scope,
    allPuzzles
  );

  // 保证刚好 3 关
  while (levelIds.length < LEVELS_PER_GAME) {
    const unused = allPuzzles.filter(p => !levelIds.includes(p.id));
    if (unused.length === 0) break;
    const pick = unused[Math.floor(Math.random() * unused.length)];
    levelIds.push(pick.id);
  }

  gameState.levels = levelIds.slice(0, LEVELS_PER_GAME);
  gameState.currentLevelIndex = 0;
  gameState.totalLevels = gameState.levels.length;

  saveGameState();
}

/**
 * 加载指定索引的关卡并渲染棋盘。
 */
function loadLevel(index) {
  if (index < 0 || index >= gameState.levels.length) {
    return;
  }

  gameState.currentLevelIndex = index;
  saveGameState();

  const puzzleId = gameState.levels[index];
  const puzzleSet = gameState.puzzleSets.find(p => p.id === puzzleId);

  if (!puzzleSet) {
    showToast('关卡数据丢失');
    goToStart();
    return;
  }

  puzzleBoard.render(puzzleSet, gameState.difficulty);
  letterPanel.render(puzzleSet, gameState.difficulty, puzzleBoard.getHintPositions());
  puzzleBoard.focusFirstEmptyCell();

  if (gameState.difficulty === 'hard') {
    timer.start(120);
  } else {
    timer.stop();
  }

  updateProgressText();
  updateErrorCountText();
}

function updateProgressText() {
  const progressText = document.getElementById('progress-text');
  const current = gameState.currentLevelIndex + 1;
  const total = gameState.totalLevels;
  progressText.textContent = `第 ${current} 关 / 共 ${total} 关`;
}

function updateErrorCountText() {
  const errorCountEl = document.getElementById('error-count');
  const remaining = MAX_ERRORS - gameState.errorCount;
  errorCountEl.textContent = `剩余机会：${remaining}`;
}

/**
 * 在游戏页 header 显示当前单词库的星星。
 */
function updateAchievementBadge() {
  const badge = document.getElementById('achievement-badge');
  if (!badge) return;

  const user = UserManager.getUser(gameState.currentUser);
  if (!user) {
    badge.innerHTML = '';
    return;
  }

  const passed = user.progress.passedLevels.length;
  const total = gameState.puzzleSets.length;
  const percent = total > 0 ? passed / total : 0;

  if (percent >= 1) {
    badge.textContent = '⭐⭐⭐';
  } else if (percent >= 0.6) {
    badge.textContent = '⭐⭐';
  } else if (percent >= 0.3) {
    badge.textContent = '⭐';
  } else {
    badge.textContent = '';
  }
}

function setupEventListeners() {
  const cancelBtn = document.getElementById('cancel-btn');
  const submitBtn = document.getElementById('submit-btn');
  const backBtn = document.getElementById('back-btn');

  cancelBtn.addEventListener('click', handleCancel);
  submitBtn.addEventListener('click', handleSubmit);
  backBtn.addEventListener('click', goToStart);
}

function handleCancel() {
  puzzleBoard.clearValues();
  letterPanel.render(puzzleBoard.getPuzzleSet(), gameState.difficulty, puzzleBoard.getHintPositions());
  puzzleBoard.focusFirstEmptyCell();
}

function handleSubmit() {
  const values = puzzleBoard.getValues();
  const puzzleSet = puzzleBoard.getPuzzleSet();

  if (hasEmptyCells(values)) {
    showToast('还有空格未填写，请填完再提交！');
    return;
  }

  // 按单词逐一检查，收集错词
  const wrongWords = collectWrongWords(values, puzzleSet);

  if (wrongWords.length === 0) {
    // 全部正确
    handleAllCorrect();
  } else {
    // 有错词
    handleWithWrongWords(wrongWords, puzzleSet);
  }
}

function hasEmptyCells(values) {
  for (const row in values) {
    for (const col in values[row]) {
      if (!values[row][col] && !puzzleBoard.isHintCell(Number(row), Number(col))) {
        return true;
      }
    }
  }
  return false;
}

/**
 * 收集当前关卡中用户填错的单词
 * @returns {{ word: string, meaning: string }[]}
 */
function collectWrongWords(values, puzzleSet) {
  const wrongWords = [];
  const seen = new Set();

  for (const wordData of puzzleSet.words) {
    const { word: correctWord, meaning, row, col, direction } = wordData;
    let isWrong = false;

    for (let i = 0; i < correctWord.length; i++) {
      const r = direction === 'across' ? row : row + i;
      const c = direction === 'across' ? col + i : col;

      if (puzzleBoard.isHintCell(r, c)) continue;

      const userValue = (values[r]?.[c] || '').toUpperCase();
      if (userValue !== correctWord[i].toUpperCase()) {
        isWrong = true;
        break;
      }
    }

    if (isWrong && !seen.has(correctWord)) {
      seen.add(correctWord);
      wrongWords.push({ word: correctWord, meaning });
    }
  }

  return wrongWords;
}

/**
 * 全部正确 → 标记通过（移除失败标记），移除本关单词的错词记录，进入下一关或胜利
 */
function handleAllCorrect() {
  const puzzleId = gameState.levels[gameState.currentLevelIndex];
  UserManager.markLevelPassed(gameState.currentUser, puzzleId);

  // 从用户错词表中移除本关所有单词（因为全都答对了）
  const puzzleSet = puzzleBoard.getPuzzleSet();
  const correctWords = puzzleSet.words.map(w => w.word.toUpperCase());
  UserManager.removeWrongWords(gameState.currentUser, correctWords);

  if (gameState.currentLevelIndex >= gameState.totalLevels - 1) {
    triggerWin();
  } else {
    showToast('回答正确！');
    setTimeout(() => {
      loadLevel(gameState.currentLevelIndex + 1);
      updateAchievementBadge();
    }, 1000);
  }
}

/**
 * 有错词 → 扣减次数 + 记录错词 + 标记关卡不通过 + 展示弹窗
 */
function handleWithWrongWords(wrongWords, puzzleSet) {
  const puzzleId = gameState.levels[gameState.currentLevelIndex];
  const wrongCount = wrongWords.length;

  // 扣减机会
  gameState.errorCount += wrongCount;
  updateErrorCountText();

  // 记录错词到用户档案
  UserManager.addWrongWords(gameState.currentUser, wrongWords);

  // 标记关卡不通过
  UserManager.markLevelFailed(gameState.currentUser, puzzleId);

  // 判断是否游戏结束（单关 3+ 错词 或 总机会 ≥3）
  if (wrongCount >= 3 || gameState.errorCount >= MAX_ERRORS) {
    gameState.errorCount = Math.min(gameState.errorCount, MAX_ERRORS);
    triggerFail();
    return;
  }

  // 展示错词弹窗，关闭后自动进入下一关
  const modal = window.__wrongWordsModal;
  modal.show(wrongWords, wrongCount, () => {
    if (gameState.currentLevelIndex >= gameState.totalLevels - 1) {
      // 最后一关虽有错词，但未达到失败条件 → 仍需回到用户页
      goToUserPage();
    } else {
      loadLevel(gameState.currentLevelIndex + 1);
    }
  });
}

function triggerWin() {
  sessionStorage.setItem('gameResult', JSON.stringify({
    result: 'win',
    errorCount: gameState.errorCount,
  }));
  sessionStorage.removeItem('gameState');
  window.location.href = `result.html?user=${encodeURIComponent(gameState.currentUser)}`;
}

/**
 * 计时器超时处理：收集当前所有已填和未填单词中错误的，直接判负。
 */
function handleTimeout() {
  const values = puzzleBoard.getValues();
  const puzzleSet = puzzleBoard.getPuzzleSet();
  const wrongWords = collectWrongWords(values, puzzleSet);

  // 记录错词
  UserManager.addWrongWords(gameState.currentUser, wrongWords);

  // 标记关卡不通过
  const puzzleId = gameState.levels[gameState.currentLevelIndex];
  UserManager.markLevelFailed(gameState.currentUser, puzzleId);

  gameState.errorCount = MAX_ERRORS;
  updateErrorCountText();
  triggerFail();
}

function triggerFail() {
  sessionStorage.setItem('gameResult', JSON.stringify({
    result: 'fail',
    errorCount: gameState.errorCount,
    user: gameState.currentUser,
  }));

  sessionStorage.removeItem('gameState');
  window.location.href = `result.html?user=${encodeURIComponent(gameState.currentUser)}`;
}

function saveGameState() {
  sessionStorage.setItem('gameState', JSON.stringify(gameState));
}

function goToStart() {
  sessionStorage.removeItem('gameState');
  window.location.href = 'start.html';
}

function goToUserPage() {
  sessionStorage.removeItem('gameState');
  window.location.href = `user.html?user=${encodeURIComponent(gameState.currentUser)}`;
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
