# Implementation Plan: 英语填字游戏（Crossword Game）

## Overview

实现分为两个独立阶段：离线预生成阶段（Node.js 脚本）和运行时阶段（纯 H5 + 原生 JavaScript）。
任务按依赖顺序排列：先建立项目结构和数据层，再实现离线生成脚本，然后实现浏览器运行时模块，最后完成页面集成与测试。

---

## Tasks

- [x] 1. 搭建项目结构与测试框架
  - 按照 design.md 第 3 节创建完整目录结构：`data/`、`scripts/`、`js/`、`css/`、`assets/`
  - 在项目根目录初始化 `package.json`，配置 Vitest 和 fast-check 依赖（pinned 版本）
  - 创建 `vitest.config.js`，配置测试入口为 `tests/` 目录，环境为 node
  - 创建 `tests/` 目录及占位文件 `tests/.gitkeep`
  - 创建 `data/data-sources.json` 初始内容（包含小学范围配置）
  - _Requirements: 1.7, 2.1, 8.1_

- [x] 2. 实现 WordLoader 模块
  - [x] 2.1 编写 `scripts/word-loader.js`
    - 实现 `loadWords(filePath)` 函数，递归遍历 JSON 层级（grade → terms → units → words），提取所有 `en`/`zh` 字段
    - 使用正则 `/^[A-Za-z]{3,20}$/` 过滤非法词条，返回 `Array<{word: string, meaning: string}>`
    - _Requirements: 1.1, 1.2_

  - [-]* 2.2 为 WordLoader 编写属性化测试
    - **Property 1: 单词过滤的完备性**
    - **Validates: Requirements 1.2**
    - 在 `tests/word-loader.test.js` 中，用 fast-check 生成任意字符串，断言：纯英文字母且长度 3–20 的字符串通过过滤，其余均被拒绝
    - 至少运行 100 次迭代

  - [-]* 2.3 为 WordLoader 编写单元测试
    - 在 `tests/word-loader.test.js` 中验证：从真实词表文件读取后，输出数组不含含空格/连字符/标点的词条，且所有词条长度 ∈ [3, 20]
    - _Requirements: 1.1, 1.2_

- [ ] 3. 实现 PuzzleGenerator 核心算法
  - [x] 3.1 编写 `scripts/puzzle-generator.js` 的棋盘操作工具函数
    - 实现 `createBoard(rows, cols)` 空棋盘初始化
    - 实现 `placeWord(board, word, row, col, direction)` 放置单词到棋盘
    - 实现 `hasConflict(board, word, row, col, direction)` 冲突检测（同格字母不同即冲突）
    - 实现 `fitsOnBoard(word, row, col, direction, maxRows, maxCols)` 边界检查
    - 实现 `trimBoard(board, placedWords)` 计算最小外包矩形并裁剪，返回新坐标和棋盘尺寸
    - _Requirements: 1.3, 1.4, 1.5, 1.8_

  - [ ] 3.2 实现交叉放置算法主逻辑
    - 实现 `tryPlaceWord(word, placedWords, board)` 函数：遍历已放置单词寻找共享字母位置，方向取反，通过边界检查和冲突检测后放置
    - 实现 `buildPuzzleSet(words, difficulty)` 函数：第一个单词横向放中心，后续单词调用 `tryPlaceWord`，失败时最多尝试 `min(10, 剩余候选数)` 次替换
    - _Requirements: 1.3, 1.4, 1.5, 1.9_

  - [~] 3.3 实现连通性校验与 PuzzleSet 结构化输出
    - 实现 `isConnected(placedWords)` 函数：以单词为节点、共享字母格为边构建图，BFS/DFS 验证全连通
    - 在 `buildPuzzleSet` 中整合连通性校验，不连通的组合直接丢弃
    - 为每个 PuzzleSet 生成唯一 `id`（格式 `puzzle-XXXX`），含 `boardRows`、`boardCols` 字段
    - _Requirements: 1.3, 1.4, 1.5, 1.8_

  - [ ]* 3.4 为 PuzzleGenerator 编写属性化测试（字段完整性）
    - **Property 2: PuzzleSet 字段完整性与边界合法性**
    - **Validates: Requirements 1.8**
    - 在 `tests/puzzle-generator.test.js` 中，用 fast-check 生成合法单词列表，调用生成器，断言所有 WordEntry 字段存在且满足约束
    - 至少运行 100 次迭代

  - [ ]* 3.5 为 PuzzleGenerator 编写属性化测试（无字母冲突）
    - **Property 3: PuzzleSet 棋盘无字母冲突**
    - **Validates: Requirements 1.3, 1.4, 1.5**
    - 在 `tests/puzzle-generator.test.js` 中，对生成的任意 PuzzleSet，将所有单词填入棋盘后检验所有交叉格字母一致
    - 至少运行 100 次迭代

  - [ ]* 3.6 为 PuzzleGenerator 编写属性化测试（连通性）
    - **Property 4: PuzzleSet 连通性不变量**
    - **Validates: Requirements 1.3, 1.4, 1.5**
    - 在 `tests/puzzle-generator.test.js` 中，对生成的任意 PuzzleSet，验证共享字母格图是连通图
    - 至少运行 100 次迭代

  - [ ]* 3.7 为 PuzzleGenerator 编写属性化测试（难度单词数量）
    - **Property 5: 难度对应的单词数量约束**
    - **Validates: Requirements 1.3, 1.4, 1.5**
    - 在 `tests/puzzle-generator.test.js` 中，验证初级=3个单词，中级=4–6个，高级=7–10个
    - 至少运行 100 次迭代

- [~] 4. 检查点 — 确保离线脚本测试全部通过
  - 确保所有测试通过，如有问题请向用户说明。

- [ ] 5. 实现入口脚本与数据生成
  - [~] 5.1 编写 `scripts/generate.js` 入口脚本
    - 读取 `广州科教版小学英语三至五年级单词表.json`，调用 WordLoader 获取单词列表
    - 分别调用 PuzzleGenerator 生成初级（≥20 组）、中级（≥20 组）、高级（≥20 组）PuzzleSet
    - 若可用单词不足无法生成 20 组，记录 console.warn 警告并保存已生成数量
    - 将结果分别写入 `data/小学-初级难度单词组合.json`、`data/小学-中级难度单词组合.json`、`data/小学-高级难度单词组合.json`
    - _Requirements: 1.6, 1.7_

  - [ ]* 5.2 为入口脚本编写单元测试
    - 验证生成的三个 JSON 文件存在且均为数组，每难度数组长度 ≥ 20（或所有可能组合）
    - _Requirements: 1.6, 1.7_

- [x] 6. 实现浏览器运行时工具模块
  - [x] 6.1 编写 `js/utils.js`
    - 实现 `sampleWithoutReplacement(pool, n)` Fisher-Yates 洗牌后取前 n 个
    - 实现 `checkAnswer(userInput, correctWord)` 大小写不敏感比对（trim + toUpperCase）
    - 实现通用 DOM 工具函数：`qs(selector)`、`qsa(selector)`
    - _Requirements: 5.4, 6.1, 6.2, 6.3_

  - [-]* 6.2 为 utils.js 编写属性化测试（答案比对大小写不敏感）
    - **Property 13: 答案比对的大小写不敏感性**
    - **Validates: Requirements 5.4**
    - 在 `tests/utils.test.js` 中，用 fast-check 生成任意英文单词的任意大小写变体，断言比对结果与全大写/全小写版本一致
    - 至少运行 100 次迭代

  - [-]* 6.3 为 utils.js 编写属性化测试（随机抽取无重复）
    - **Property 15: 随机抽取关卡的无重复性与数量正确性**
    - **Validates: Requirements 6.1, 6.2, 6.3**
    - 在 `tests/utils.test.js` 中，用 fast-check 生成任意池和 n，验证返回数组长度=n 且无重复元素
    - 至少运行 100 次迭代

- [ ] 7. 实现 DataSourceConfig 模块
  - [~] 7.1 编写 `js/data-source-config.js`
    - 实现 `DataSourceConfig` 类：`load()` 方法通过 `fetch` 加载 `data/data-sources.json`，返回 `Array<DataSourceEntry>`
    - 加载失败时抛出错误（含描述性 message），供 StartPage 捕获并展示
    - 实现 `getPath(entry, difficulty)` 返回对应难度的文件路径（`null` 表示不可用）
    - _Requirements: 2.1, 2.3_

- [ ] 8. 实现 StartPage
  - [~] 8.1 创建 `start.html` 结构与 `css/start.css` 样式
    - 实现粉色径向渐变背景、彩虹弧形渐变标题（SVG textPath 方式）、松鼠吉祥物（`assets/mascot-squirrel.svg`，右下角绝对定位）
    - 实现 5×5 字母填入动画网格（CSS Grid）
    - 所有交互控件 min-height: 44px；在 320px–430px 无横向滚动
    - 引入 `js/data-source-config.js`、`js/start-page.js`
    - _Requirements: 3.1, 3.7, 9.1, 9.2_

  - [~] 8.2 编写 `js/start-page.js` 逻辑
    - 页面加载时调用 `DataSourceConfig.load()`，成功后动态填充"单词范围"下拉菜单
    - 加载失败时在下拉区域显示"配置加载失败，请刷新重试"并禁用 START 按钮
    - 根据已选范围+难度更新难度控件可用/禁用状态，更新 START 按钮可点击状态
    - START 按钮点击后加载对应 PuzzleSet JSON，成功则跳转 `game.html?scope=&difficulty=`，失败则显示错误信息
    - 实现字母填入动画循环（每格 400ms，全部填完暂停 2s 再重置）
    - _Requirements: 2.2, 2.3, 2.4, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ]* 8.3 为 StartPage 编写属性化测试（下拉菜单顺序一致性）
    - **Property 6: StartPage 下拉菜单与配置文件的顺序一致性**
    - **Validates: Requirements 2.2**
    - 在 `tests/start-page.test.js` 中，用 fast-check 生成任意条目数组，模拟 DOM 渲染后验证下拉选项顺序与配置顺序一致
    - 至少运行 100 次迭代

  - [ ]* 8.4 为 StartPage 编写属性化测试（START 按钮状态一致性）
    - **Property 7: START 按钮状态与（范围, 难度）有效性的一致性**
    - **Validates: Requirements 3.4**
    - 在 `tests/start-page.test.js` 中，用 fast-check 生成任意 (范围, 难度) 组合，验证按钮状态与有效性严格对应
    - 至少运行 100 次迭代

- [ ] 9. 实现 PuzzleBoard 组件
  - [~] 9.1 编写 `js/puzzle-board.js` 核心渲染逻辑
    - 实现 `PuzzleBoard` 类，接受容器元素和 PuzzleSet 数据
    - 根据 `boardRows × boardCols` 动态计算单元格尺寸（`max(36, floor(availableWidth / boardCols))`）
    - 渲染 CSS Grid 棋盘：输入格（含 `<input maxlength="1">`）与暗格（深色背景，无交互）
    - 在单词起始格左上角添加上标编号；两个单词共用起始格时显示 "N,M" 格式
    - 渲染棋盘下方提示列表，格式 `N. 横向：释义` 或 `N. 纵向：释义`，按编号升序排列
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [~] 9.2 实现输入过滤与软键盘遮挡处理
    - 在每个 `<input>` 的 `keydown`/`input` 事件中过滤非英文字母字符（静默忽略）
    - 监听 `focus` 事件，延迟 300ms 后调用 `scrollIntoView({ behavior: 'smooth', block: 'center' })` 防止软键盘遮挡
    - 实现 `getValues()` 返回当前所有输入格内容、`clearValues()` 清空所有输入格
    - _Requirements: 4.3, 9.3, 9.4_

  - [ ]* 9.3 为 PuzzleBoard 编写属性化测试（格子位置正确性）
    - **Property 8: PuzzleBoard 渲染的格子位置正确性**
    - **Validates: Requirements 4.1, 4.2, 4.4**
    - 在 `tests/puzzle-board.test.js` 中，用 fast-check 生成合法 PuzzleSet，渲染后验证总格数=boardRows×boardCols，单词字母格均为输入格，其余为暗格
    - 至少运行 100 次迭代（使用 jsdom 环境）

  - [ ]* 9.4 为 PuzzleBoard 编写属性化测试（编号上标正确性）
    - **Property 9: 单词编号上标的正确性**
    - **Validates: Requirements 4.5**
    - 在 `tests/puzzle-board.test.js` 中，用 fast-check 生成合法 PuzzleSet，验证起始格上标包含正确编号，共用起始格时显示两个编号
    - 至少运行 100 次迭代

  - [ ]* 9.5 为 PuzzleBoard 编写属性化测试（提示列表完整对应）
    - **Property 10: 提示列表内容与 PuzzleSet 的完整对应性**
    - **Validates: Requirements 4.6**
    - 在 `tests/puzzle-board.test.js` 中，验证提示列表条目数=单词数，每条含编号+方向+释义，按编号升序排列
    - 至少运行 100 次迭代

- [~] 10. 检查点 — 确保 UI 组件测试全部通过
  - 确保所有测试通过，如有问题请向用户说明。

- [ ] 11. 实现 GameController
  - [~] 11.1 编写 `js/game-controller.js` 初始化与关卡序列管理
    - 从 URL 参数读取 `scope` 和 `difficulty`，从 `sessionStorage` 恢复或初始化游戏状态（`levels`、`currentLevelIndex`、`errorCount`、`totalLevels`）
    - 调用 `sampleWithoutReplacement` 随机抽取关卡序列（初级 3 关、中级 4 关、高级 5 关）
    - 若 PuzzleSet 池数量不足，显示"关卡数据不足，无法开始游戏"并跳转 StartPage
    - 实现 `loadLevel(index)` 加载指定关卡 PuzzleSet，实例化 PuzzleBoard，更新顶部进度文字 "第 X 关 / 共 Y 关"
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [~] 11.2 实现提交与取消逻辑
    - 实现"取消"按钮处理：调用 `PuzzleBoard.clearValues()`，不修改 ErrorCount
    - 实现"提交"按钮处理：
      - 有空格时显示"还有空格未填写，请填完再提交！"，不增加 ErrorCount
      - 调用 `checkAnswer` 逐一比对，全部正确且非最终关则调用 `loadLevel(index+1)`
      - 全部正确且最终关则触发胜利流程（写入 sessionStorage，跳转 result.html）
      - 有错误且 ErrorCount < 3 时 ErrorCount+1，显示"答案有误，请再检查一下！（剩余机会：X 次）"
      - 有错误且 ErrorCount = 3 时触发失败流程
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

  - [ ]* 11.3 为 GameController 编写属性化测试（取消操作不影响 ErrorCount）
    - **Property 11: 取消操作清空输入格且不影响 ErrorCount**
    - **Validates: Requirements 5.2**
    - 在 `tests/game-controller.test.js` 中，用 fast-check 生成任意初始 ErrorCount 值和任意输入内容，点击取消后验证 ErrorCount 不变，所有输入格为空
    - 至少运行 100 次迭代

  - [ ]* 11.4 为 GameController 编写属性化测试（有空格提交不增加 ErrorCount）
    - **Property 12: 有空格时提交不增加 ErrorCount**
    - **Validates: Requirements 5.3**
    - 在 `tests/game-controller.test.js` 中，用 fast-check 生成至少一个空格的输入状态，验证提交后 ErrorCount 不变
    - 至少运行 100 次迭代

  - [ ]* 11.5 为 GameController 编写属性化测试（ErrorCount 递增上界）
    - **Property 14: ErrorCount 递增上界约束**
    - **Validates: Requirements 5.7, 5.8**
    - 在 `tests/game-controller.test.js` 中，用 fast-check 生成初始 ErrorCount ∈ {0,1,2}，提交错误答案后验证 ErrorCount 恰好+1；ErrorCount=3 时验证触发失败流程而非继续累加
    - 至少运行 100 次迭代

  - [ ]* 11.6 为 GameController 编写属性化测试（进度文字格式）
    - **Property 16: 进度文字格式正确性**
    - **Validates: Requirements 6.5**
    - 在 `tests/game-controller.test.js` 中，用 fast-check 生成任意 (X, Y) 组合（1 ≤ X ≤ Y ≤ 5），验证顶部进度文字严格符合格式 "第 X 关 / 共 Y 关"
    - 至少运行 100 次迭代

- [~] 12. 创建 `game.html` 与 `css/game.css`
  - 实现顶部固定进度条区域（含返回箭头）
  - 实现棋盘容器和提示区域的 HTML 骨架
  - 实现底部"取消"和"提交"按钮，min-height: 44px
  - 引入 `js/utils.js`、`js/puzzle-board.js`、`js/game-controller.js`
  - 视口锁定 meta 标签（禁止缩放）
  - _Requirements: 5.1, 6.5, 9.1, 9.2_

- [ ] 13. 实现 ResultPage
  - [~] 13.1 创建 `result.html` 与 `css/result.css`
    - 胜利动画（烟花/星星 CSS 动画，2–5 秒）与失败动画（摇摆/下落 CSS 动画，2–5 秒）
    - 显示对应祝贺/鼓励文字
    - "再来一次"按钮（立即可见，min-height: 44px）
    - _Requirements: 7.1, 7.2_

  - [~] 13.2 编写 `js/result-page.js` 逻辑
    - 从 sessionStorage 读取 `gameResult`，根据 `result` 字段切换胜利/失败动画和文字
    - 启动自动跳转计时器（动画结束后跳转 start.html，清除 ErrorCount）
    - "再来一次"按钮：`clearTimeout(autoReturnTimer)` 后立即跳转 start.html，重置 ErrorCount
    - _Requirements: 7.3, 7.4_

- [~] 14. 实现公共样式与松鼠吉祥物资源
  - 编写 `css/common.css`：全局背景色、字体（Fredoka One + Comic Sans 降级）、按钮基础样式
  - 创建或内联 `assets/mascot-squirrel.svg` 松鼠吉祥物 SVG
  - 确认所有页面引入正确的 CSS 文件，无横向溢出（320px–430px）
  - _Requirements: 3.1, 9.1, 9.2_

- [~] 15. 最终检查点 — 确保所有测试通过
  - 运行 `npx vitest --run` 确保全部测试通过
  - 确保所有测试通过，如有问题请向用户说明。

---

## Notes

- 标有 `*` 的子任务为可选测试任务，可在 MVP 阶段跳过，但强烈建议执行以保证正确性
- 每个属性化测试均标注了对应的 Property 编号和需求编号，便于追溯
- 离线脚本（`scripts/`）仅在开发环境本地运行，不部署至浏览器
- `vitest.config.js` 应为浏览器 DOM 相关测试（PuzzleBoard）配置 jsdom 环境，为 Node.js 模块测试配置 node 环境
- Property 3、4、5 分别从不同维度验证生成结果，三者不冗余
- 所有属性化测试需标注注释格式：`// Feature: crossword-game, Property N: <摘要>`

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "6.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.1"] },
    { "id": 3, "tasks": ["3.2", "6.2", "6.3"] },
    { "id": 4, "tasks": ["3.3", "7.1"] },
    { "id": 5, "tasks": ["3.4", "3.5", "3.6", "3.7", "5.1"] },
    { "id": 6, "tasks": ["5.2", "8.1"] },
    { "id": 7, "tasks": ["8.2", "9.1"] },
    { "id": 8, "tasks": ["8.3", "8.4", "9.2"] },
    { "id": 9, "tasks": ["9.3", "9.4", "9.5", "11.1"] },
    { "id": 10, "tasks": ["11.2", "12"] },
    { "id": 11, "tasks": ["11.3", "11.4", "11.5", "11.6", "13.1"] },
    { "id": 12, "tasks": ["13.2", "14"] }
  ]
}
```
