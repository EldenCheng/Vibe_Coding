/**
 * data-source-config.js — DataSourceConfig 模块
 *
 * 负责加载 data-sources.json 配置文件，提供单词库的路径映射。
 *
 * 用法：
 *   import { DataSourceConfig } from './data-source-config.js';
 *   const config = await DataSourceConfig.load();
 *   const path = config.getPath(selectedScope);
 */

/**
 * @typedef {Object} DataSourceEntry
 * @property {string} displayName - 显示名称（如"小学"）
 * @property {string|null} dataPath - PuzzleSet JSON 文件路径
 */

export class DataSourceConfig {
  /** @type {DataSourceEntry[]} */
  #entries = [];

  /**
   * 私有构造函数，通过 load() 静态方法创建实例。
   * @param {DataSourceEntry[]} entries
   */
  constructor(entries) {
    this.#entries = entries;
  }

  /**
   * 加载配置文件并返回 DataSourceConfig 实例。
   *
   * @param {string} [configPath='data/data-sources.json'] - 配置文件路径
   * @returns {Promise<DataSourceConfig>}
   * @throws {Error} 加载失败或解析失败时抛出错误
   */
  static async load(configPath = 'data/data-sources.json') {
    try {
      const response = await fetch(configPath);

      if (!response.ok) {
        throw new Error(`加载配置文件失败: HTTP ${response.status}`);
      }

      const raw = await response.json();

      if (!Array.isArray(raw)) {
        throw new Error('配置文件格式错误：根节点应为数组');
      }

      const entries = raw.map((entry, index) => {
        if (!entry || typeof entry !== 'object') {
          throw new Error(`配置文件第 ${index + 1} 项不是对象`);
        }

        if (typeof entry.displayName !== 'string' || entry.displayName.trim().length === 0) {
          throw new Error(`配置文件第 ${index + 1} 项缺少有效 displayName`);
        }

        return {
          displayName: entry.displayName.trim(),
          dataPath: this._normalizePath(entry.dataPath),
        };
      });

      return new DataSourceConfig(entries);

    } catch (err) {
      throw new Error(`DataSourceConfig.load() 失败: ${err.message}`);
    }
  }

  /**
   * 规范化路径，空值转为 null。
   * @param {string|undefined|null} path
   * @returns {string|null}
   */
  static _normalizePath(path) {
    if (!path || typeof path !== 'string') {
      return null;
    }
    const trimmed = path.trim();
    return trimmed.length === 0 ? null : trimmed;
  }

  /**
   * 获取所有数据源条目。
   * @returns {DataSourceEntry[]}
   */
  getEntries() {
    return [...this.#entries];
  }

  /**
   * 根据显示名称查找条目。
   * @param {string} displayName
   * @returns {DataSourceEntry|null}
   */
  findEntry(displayName) {
    return this.#entries.find(e => e.displayName === displayName) || null;
  }

  /**
   * 获取指定单词库的 JSON 文件路径。
   * @param {string} displayName - 单词库显示名称
   * @returns {string|null} 文件路径，不可用时返回 null
   */
  getPath(displayName) {
    const entry = this.findEntry(displayName);
    if (!entry) return null;
    return entry.dataPath || null;
  }

  /**
   * 检查指定单词库是否可用。
   * @param {string} displayName
   * @returns {boolean}
   */
  isAvailable(displayName) {
    return this.getPath(displayName) !== null;
  }
}
