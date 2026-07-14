/**
 * user-manager.js — 用户管理器
 * 
 * 负责：
 * - 用户的 CRUD 操作
 * - 基于 localStorage 的持久化存储
 * - 7 天有效期 cookie 机制（模拟）
 * - 关卡序列生成（含失败关卡混入逻辑）
 * - 错词表管理
 */

const USERS_STORAGE_KEY = 'crossword-users';
const LAST_USER_STORAGE_KEY = 'crossword-last-user';
const COOKIE_EXPIRY_DAYS = 7;

export class UserManager {
  /**
   * 获取所有用户数据
   * @returns {Object} { nickname: userData }
   */
  static getAllUsers() {
    try {
      const raw = localStorage.getItem(USERS_STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (e) {
      console.error('读取用户数据失败:', e);
      return {};
    }
  }

  /**
   * 保存所有用户数据
   * @param {Object} users 
   */
  static saveAllUsers(users) {
    localStorage.setItem(USERS_STORAGE_KEY, JSON.stringify(users));
  }

  /**
   * 获取指定用户
   * @param {string} nickname 
   * @returns {Object|null}
   */
  static getUser(nickname) {
    const users = this.getAllUsers();
    return users[nickname] || null;
  }

  /**
   * 创建新用户
   * @param {string} nickname 
   * @returns {Object} 新创建的用户对象
   */
  static createUser(nickname) {
    const users = this.getAllUsers();
    const newUser = {
      createdAt: new Date().toISOString(),
      lastPlayed: new Date().toISOString(),
      progress: {
        passedLevels: [],
        failedLevels: [],
        currentIndex: 0
      },
      wrongWords: {} // { "word": { meaning: "...", count: 1 } }
    };
    users[nickname] = newUser;
    this.saveAllUsers(users);
    return newUser;
  }

  /**
   * 删除用户
   * @param {string} nickname 
   */
  static deleteUser(nickname) {
    const users = this.getAllUsers();
    if (users[nickname]) {
      delete users[nickname];
      this.saveAllUsers(users);
      if (this.getLastUser()?.nickname === nickname) {
        this.clearLastUser();
      }
    }
  }

  /**
   * 重置进度（不重置错词）
   * @param {string} nickname 
   */
  static resetProgress(nickname) {
    const users = this.getAllUsers();
    if (users[nickname]) {
      users[nickname].progress = {
        passedLevels: [],
        failedLevels: [],
        currentIndex: 0
      };
      this.saveAllUsers(users);
    }
  }

  /**
   * 设置最后登录用户（Cookie 机制）
   * @param {string} nickname 
   */
  static setLastUser(nickname) {
    const expiry = new Date();
    expiry.setDate(expiry.getDate() + COOKIE_EXPIRY_DAYS);
    localStorage.setItem(LAST_USER_STORAGE_KEY, JSON.stringify({
      nickname,
      expires: expiry.toISOString()
    }));
  }

  /**
   * 获取上次登录用户（检查过期时间）
   * @returns {{nickname: string, expires: string}|null}
   */
  static getLastUser() {
    try {
      const raw = localStorage.getItem(LAST_USER_STORAGE_KEY);
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (new Date() > new Date(data.expires)) {
        this.clearLastUser();
        return null;
      }
      return data;
    } catch (e) {
      return null;
    }
  }

  static clearLastUser() {
    localStorage.removeItem(LAST_USER_STORAGE_KEY);
  }

  /**
   * 生成本局关卡序列
   * @param {string} nickname 
   * @param {string} scope 
   * @param {Array} allPuzzles 全部可用 PuzzleSet
   * @returns {string[]} 3 个 puzzleId
   */
  static generateLevelSequence(nickname, scope, allPuzzles) {
    const user = this.getUser(nickname);
    if (!user) return [];

    const { passedLevels, failedLevels } = user.progress;
    const totalNeeded = 3;
    const result = [];

    // 1. 如果有不通过的关卡，随机选 1 个
    if (failedLevels.length > 0) {
      const failed = [...failedLevels];
      const randIdx = Math.floor(Math.random() * failed.length);
      result.push(failed[randIdx]);
    }

    // 2. 确定剩余需要的数量
    const remainingCount = totalNeeded - result.length;
    
    // 3. 从未玩过/未通过的池子中抽取
    // 排除已经在这个 result 里的，且排除已经 passed 的
    const pool = allPuzzles
      .filter(p => !passedLevels.includes(p.id))
      .filter(p => !result.includes(p.id))
      .map(p => p.id);

    if (pool.length >= remainingCount) {
      // 随机抽取
      const shuffled = pool.sort(() => Math.random() - 0.5);
      result.push(...shuffled.slice(0, remainingCount));
    } else {
      // 如果正常池子不够，全部从失败池子里补（排除已在 result 里的）
      const remainingFailed = failedLevels.filter(id => !result.includes(id));
      const shuffledFailed = remainingFailed.sort(() => Math.random() - 0.5);
      result.push(...shuffledFailed.slice(0, remainingCount));
      
      // 如果还是不够，就从全部里随机补
      if (result.length < totalNeeded) {
        const allIds = allPuzzles.map(p => p.id);
        const finalPool = allIds.filter(id => !result.includes(id));
        const finalShuffled = finalPool.sort(() => Math.random() - 0.5);
        result.push(...finalShuffled.slice(0, totalNeeded - result.length));
      }
    }

    return result.slice(0, totalNeeded);
  }

  /**
   * 记录错词
   * @param {string} nickname 
   * @param {Array<{word: string, meaning: string}>} wrongWords 
   */
  static addWrongWords(nickname, wrongWords) {
    const users = this.getAllUsers();
    const user = users[nickname];
    if (!user) return;

    wrongWords.forEach(item => {
      const word = item.word.toUpperCase();
      if (!user.wrongWords[word]) {
        user.wrongWords[word] = { meaning: item.meaning, count: 0 };
      }
      user.wrongWords[word].count++;
    });

    this.saveAllUsers(users);
  }

  /**
   * 获取排序后的错词列表
   * @param {string} nickname 
   * @returns {Array} [{word, meaning, count}]
   */
  static getWrongWordsList(nickname) {
    const user = this.getUser(nickname);
    if (!user || !user.wrongWords) return [];

    return Object.entries(user.wrongWords).map(([word, data]) => ({
      word,
      ...data
    })).sort((a, b) => {
      // 错误次数降序
      if (b.count !== a.count) return b.count - a.count;
      // 字母升序
      return a.word.localeCompare(b.word);
    });
  }

  /**
   * 标记关卡通过
   * @param {string} nickname 
   * @param {string} puzzleId 
   */
  static markLevelPassed(nickname, puzzleId) {
    const users = this.getAllUsers();
    const user = users[nickname];
    if (!user) return;

    if (!user.progress.passedLevels.includes(puzzleId)) {
      user.progress.passedLevels.push(puzzleId);
    }
    // 如果之前在失败列表里，移除之
    user.progress.failedLevels = user.progress.failedLevels.filter(id => id !== puzzleId);
    
    this.saveAllUsers(users);
  }

  /**
   * 标记关卡不通过
   * @param {string} nickname 
   * @param {string} puzzleId 
   */
  static markLevelFailed(nickname, puzzleId) {
    const users = this.getAllUsers();
    const user = users[nickname];
    if (!user) return;

    if (!user.progress.failedLevels.includes(puzzleId)) {
      user.progress.failedLevels.push(puzzleId);
    }
    
    this.saveAllUsers(users);
  }

  /**
   * 从用户错词表中移除指定单词（全部正确时调用）
   * @param {string} nickname 
   * @param {string[]} words 要移除的单词列表
   */
  static removeWrongWords(nickname, words) {
    const users = this.getAllUsers();
    const user = users[nickname];
    if (!user) return;

    words.forEach(word => {
      const upper = word.toUpperCase();
      if (user.wrongWords[upper]) {
        user.wrongWords[upper].count--;
        if (user.wrongWords[upper].count <= 0) {
          delete user.wrongWords[upper];
        }
      }
    });

    this.saveAllUsers(users);
  }
}
