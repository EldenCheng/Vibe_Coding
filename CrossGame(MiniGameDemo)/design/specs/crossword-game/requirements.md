# Requirements Document

## Introduction

本项目为微信小程序英语填字游戏（Crossword Game）的 H5+JavaScript 演示版本，按微信小程序规范开发，待后续迁移至正式小程序。游戏面向小学生，单词来源于广州科教版小学英语三至五年级单词表，设有初级、中级、高级三个难度等级，旨在以轻松有趣的方式帮助学生记忆英语单词。

---

## Glossary

- **System**：整个填字游戏应用
- **WordLoader**：负责读取和管理单词 JSON 数据的模块
- **PuzzleGenerator**：负责根据单词组合生成填字游戏棋盘布局的模块
- **PuzzleBoard**：填字游戏棋盘，显示单元格矩阵
- **GameController**：管理游戏流程、关卡状态、错误计数的模块
- **StartPage**：游戏启动页面
- **GamePage**：游戏主页面（显示填字棋盘）
- **ResultPage**：游戏结果页面（胜利或失败）
- **单词范围（WordScope）**：单词来源的学段，如"小学"、"初中"（预留）、"高中"（预留）
- **难度（Difficulty）**：游戏难度等级，分为"初级"、"中级"、"高级"
- **单词组合（PuzzleSet）**：一局游戏所使用的单词集合，按难度规则生成并存入 JSON
- **关卡（Level）**：游戏中的一个独立挑战单元，由一个 PuzzleSet 构成
- **错误次数（ErrorCount）**：整局游戏内用户提交错误答案的累计次数（跨关卡不重置，达到 3 次即触发失败流程）
- **输入格**：棋盘中需要用户填写字母的单元格

---

## Requirements

### Requirement 1: 单词数据预处理与 PuzzleSet 生成

**User Story:** As a game developer, I want to pre-generate crossword puzzle sets from the word list and store them as JSON files, so that the game can load them at runtime without real-time computation.

#### Acceptance Criteria

1. THE **WordLoader** SHALL 从 `广州科教版小学英语三至五年级单词表.json` 中读取全部词条的英文单词（`word` 字段）和中文释义（`meaning` 字段）。
2. THE **PuzzleGenerator** SHALL 过滤掉含空格、连字符、标点或字母数量少于 3 个或多于 20 个的词条，仅保留由纯英文字母组成的单词。
3. WHEN 生成初级 PuzzleSet 时，THE **PuzzleGenerator** SHALL 每组包含恰好 3 个单词，且组内所有单词通过共享字母格形成连通图（每个单词至少与组内另一个单词共享 1 个相同字母位置）。
4. WHEN 生成中级 PuzzleSet 时，THE **PuzzleGenerator** SHALL 每组包含 4 至 6 个单词，且组内所有单词通过共享字母格形成连通图。
5. WHEN 生成高级 PuzzleSet 时，THE **PuzzleGenerator** SHALL 每组包含 7 至 10 个单词，且组内所有单词通过共享字母格形成连通图。
6. THE **PuzzleGenerator** SHALL 在每个难度内至少生成 20 组不重复的 PuzzleSet（"不重复"定义为：两组 PuzzleSet 所含单词集合不完全相同，与顺序无关）；IF 可用单词池过小无法满足最小数量，THEN THE **PuzzleGenerator** SHALL 尽可能生成最多数量的组合并记录警告。
7. THE **PuzzleGenerator** SHALL 将初级结果保存为 `小学-初级难度单词组合.json`，中级保存为 `小学-中级难度单词组合.json`，高级保存为 `小学-高级难度单词组合.json`。
8. THE **PuzzleGenerator** SHALL 在每个 PuzzleSet 的 JSON 记录中包含：各单词的英文（`word`）、中文释义（`meaning`）、在棋盘上的起始行列坐标（`row`、`col`，均以 0 为基准）、方向（`direction`：`"across"` 或 `"down"`）以及棋盘总行列数（`boardRows`、`boardCols`，均不超过 20）。
9. IF 某单词无法与组内任意其他单词共享至少一个字母格，THEN THE **PuzzleGenerator** SHALL 从剩余候选词中最多尝试 `min(10, 剩余候选词数量)` 次替换；IF 所有替换均失败，THEN 放弃本组并从下一个候选组合重新开始。

---

### Requirement 2: 单词范围与难度的扩展管理方案

**User Story:** As a game maintainer, I want to manage word scopes and their JSON paths through a unified configuration file, so that adding new grade levels requires no page code changes.

#### Acceptance Criteria

1. THE **System** SHALL 从独立的配置文件（`data-sources.json`）中读取所有单词范围条目，每个条目须包含：显示名称（1–50 个字符）和初级、中级、高级三个难度各自对应的 PuzzleSet JSON 文件路径；路径不得硬编码在 HTML 或 JavaScript 中。
2. WHEN **StartPage** 加载完成时，THE **StartPage** SHALL 依照 `data-sources.json` 中条目的顺序，将每个条目的显示名称填充至"单词范围"下拉菜单中，无需修改 HTML 或 JavaScript 代码。
3. IF `data-sources.json` 加载失败或内容为空，THEN THE **StartPage** SHALL 在下拉菜单区域显示错误提示文字，并禁用"START"按钮，阻止游戏启动。
4. IF 某条目的某个难度对应的 JSON 文件路径为空或缺失，THEN THE **System** SHALL 在难度选择控件中将该难度标记为不可选状态，防止用户选择无效配置。

---

### Requirement 3: 启动页面（StartPage）

**User Story:** As a player, I want to select a word scope and difficulty on the start page and begin the game, so that I can quickly enter game levels appropriate for my learning stage.

#### Acceptance Criteria

1. THE **StartPage** SHALL 呈现以下四项视觉元素：彩虹弧形渐变标题文字、卡通松鼠吉祥物图像（PNG 格式，使用 mix-blend-mode 混合模式过滤白色背景，带 writingAction 摇摆动画）、粉色系渐变背景，以及填字棋盘风格的字母填入动画（使用固定棋盘矩阵展示 C-A-T、D-O-G、A-P-P-L-E 等填字图案，按序列逐格点亮，每格间隔约 400ms，全部点亮后暂停约 2 秒再重置循环播放）。
2. THE **StartPage** SHALL 显示一个"单词范围"下拉菜单，初始选项为"小学"，选项列表动态从 `data-sources.json` 读取。
3. THE **StartPage** SHALL 在"单词范围"下拉菜单旁显示一个"难度"选择控件，默认选中"初级"，可选"中级"和"高级"；不可用的难度项应呈现禁用状态。
4. THE **StartPage** SHALL 显示一个"START"开始按钮；仅当单词范围与难度均为有效可选状态时，该按钮可被点击。
5. WHEN 用户点击"START"按钮时，THE **StartPage** SHALL 根据当前选定的单词范围和难度，从对应路径加载 PuzzleSet JSON 文件，并跳转至 GamePage 开始游戏；文件路径命名示例：`小学-初级难度单词组合.json`。
6. IF PuzzleSet JSON 文件加载失败，THEN THE **StartPage** SHALL 在页面上显示错误提示信息，并保持停留在 StartPage，不跳转至 GamePage。
7. THE **StartPage** SHALL 确保所有交互控件（下拉菜单、难度选择、START 按钮）的可点击区域高度不小于 44px，适配手机拇指操作，且在 320px–430px 宽度范围内无需横向滚动。

---

### Requirement 4: 游戏棋盘构造（PuzzleBoard）

**User Story:** As a player, I want to see a clear and interactive crossword board, so that I can identify given letters and blank cells that need to be filled.

#### Acceptance Criteria

1. WHEN GamePage 加载时，THE **PuzzleBoard** SHALL 根据当前关卡 PuzzleSet 的布局数据（`boardRows`、`boardCols`、每个单词的坐标和方向）渲染填字棋盘单元格矩阵。
2. WHILE 棋盘处于渲染状态时，THE **PuzzleBoard** SHALL 将属于单词的所有单元格渲染为"输入格"（显示空白，可供用户填写字母）。
3. THE **PuzzleBoard** SHALL 在每个"输入格"内渲染可点击的单字符文本输入框；WHEN 用户输入非英文字母字符时，THE **PuzzleBoard** SHALL 静默忽略该输入并保留输入格原有内容。
4. THE **PuzzleBoard** SHALL 将棋盘上不属于任何单词的位置渲染为深色背景（如深灰或黑色）的"空白格"，与提示格和输入格在视觉上明显区分，且该区域不响应点击事件。
5. THE **PuzzleBoard** SHALL 在每个单词起始格的左上角以上标形式显示该单词的编号（数字按单词在 PuzzleSet 中的顺序从 1 开始递增）；IF 两个单词共用同一起始格，THEN 该格同时显示两个编号（如"1,2"）。
6. THE **PuzzleBoard** SHALL 在棋盘下方的提示区域，按编号升序列出所有单词的编号、方向（横向/纵向）及中文释义（格式示例：`1. 横向：苹果`）。
7. THE **PuzzleBoard** SHALL 适配手机屏幕，棋盘及提示区域在竖屏模式下无需横向滚动即可完整显示，每个单元格的触控区域不小于 36×36 像素。

---

### Requirement 5: 游戏输入与提交逻辑

**User Story:** As a player, I want to submit my answers and receive feedback, so that I know whether I passed the current level.

#### Acceptance Criteria

1. THE **GamePage** SHALL 在棋盘下方显示"提交"和"取消"两个按钮。
2. WHEN 用户点击"取消"按钮时，THE **GameController** SHALL 清空当前关卡所有"输入格"中用户已填写的字母，恢复至空白初始状态；ErrorCount 不因取消操作而重置。
3. IF 用户点击"提交"按钮时存在任意"输入格"为空，THEN THE **GameController** SHALL 向用户显示"还有空格未填写，请填完再提交！"的提示，不执行答案比对，不增加 ErrorCount。
4. IF 用户点击"提交"按钮且所有输入格均已填写，THEN THE **GameController** SHALL 将所有"输入格"中的字母与 PuzzleSet 中的正确答案逐一比对（不区分大小写）。
5. IF 比对结果全部正确且当前关卡非最终关卡，THEN THE **GameController** SHALL 判定本关通过，并自动加载下一关。
6. IF 比对结果全部正确且当前关卡为最终关卡，THEN THE **GameController** SHALL 判定全部通关，并触发胜利流程。
7. IF 比对结果存在任意错误且整局 ErrorCount 小于 3，THEN THE **GameController** SHALL 将 ErrorCount 加 1，并向用户显示"答案有误，请再检查一下！（剩余机会：X 次）"的提示，但不指明具体哪格错误。
8. IF 整局 ErrorCount 达到 3 且本次比对仍有错误，THEN THE **GameController** SHALL 判定闯关失败，并触发失败流程。

---

### Requirement 6: 关卡数量与游戏进度

**User Story:** As a player, I want a game session to consist of multiple levels with visible progress, so that I stay motivated throughout the game.

#### Acceptance Criteria

1. WHEN 难度为"初级"时，THE **GameController** SHALL 从可用 PuzzleSet 池中随机抽取 3 个不重复的 PuzzleSet 作为本局关卡序列。
2. WHEN 难度为"中级"时，THE **GameController** SHALL 从可用 PuzzleSet 池中随机抽取 4 个不重复的 PuzzleSet 作为本局关卡序列。
3. WHEN 难度为"高级"时，THE **GameController** SHALL 从可用 PuzzleSet 池中随机抽取 5 个不重复的 PuzzleSet 作为本局关卡序列。
4. IF 可用 PuzzleSet 池中的组合数量少于当前难度所需关卡数，THEN THE **GameController** SHALL 终止游戏启动流程，向用户显示"关卡数据不足，无法开始游戏"的提示，并返回 StartPage。
5. WHILE 游戏处于进行中状态，THE **GamePage** SHALL 在页面顶部以固定格式"第 X 关 / 共 Y 关"显示当前关卡编号，并在每次加载新关卡后立即更新。
6. WHEN 用户通过当前关卡且关卡序列中仍有下一关时，THE **GameController** SHALL 自动加载下一关的 PuzzleSet 并刷新棋盘。
7. IF 用户通过最后一关，THEN THE **GameController** SHALL 触发胜利流程（见需求7）。

---

### Requirement 7: 胜利与失败动画及结果页面

**User Story:** As a player, I want to see engaging animations when I complete all levels or fail a level, so that the game experience is more fun.

#### Acceptance Criteria

1. WHEN 用户通过所有关卡时，THE **System** SHALL 播放胜利动画并显示祝贺文字（如"太棒了！你全部过关了！"），动画持续时长不少于 2 秒且不超过 5 秒。
2. WHEN 用户在任意关卡提交错误且整局 ErrorCount 达到 3 次时，THE **System** SHALL 播放失败动画并显示鼓励文字（如"别灰心，再来一次吧！"），动画持续时长不少于 2 秒且不超过 5 秒。
3. WHEN 胜利或失败动画播放完毕且用户未主动点击"再来一次"按钮时，THE **System** SHALL 立即自动跳转回 StartPage，并将 ErrorCount 重置为 0。
4. WHILE 结果动画播放中或播放结束后，IF 用户点击"再来一次"按钮，THEN THE **System** SHALL 立即取消待执行的自动跳转计时器并跳转回 StartPage，同时将 ErrorCount 重置为 0。

---

### Requirement 8: 项目文档维护

**User Story:** As a developer, I want complete design documents before coding that are kept up to date with every change, so that the project remains maintainable.

#### Acceptance Criteria

1. BEFORE 任何代码文件被创建或修改时，THE **System** SHALL 确保 `项目设计文档.md` 已存在，并包含以下章节：软件架构总览、模块划分与职责、文件结构说明、模块间数据流描述、各模块实现逻辑说明。
2. WHEN 任何涉及架构变动、模块增删、数据结构变更或接口调整的设计决策发生时，THE **System** SHALL 先更新 `项目设计文档.md` 中对应章节，再执行代码变更。
3. WHEN 每次代码版本发布时，THE **System** SHALL 在 `版本变更.md` 中新增一个变更记录条目，包含：版本号（格式 `vX.Y.Z`）、发布日期（格式 `YYYY-MM-DD`）、变更内容摘要。

---

### Requirement 9: 移动端适配

**User Story:** As a user playing on a mobile phone, I want all pages to display correctly and operate smoothly in a mobile browser, so that I have a good gaming experience.

#### Acceptance Criteria

1. THE **System** SHALL 确保所有页面在手机浏览器中视口固定为设备宽度，且用户无法通过手势缩放页面。
2. THE **System** SHALL 确保所有页面在 320px 至 430px 宽度范围内不出现横向溢出或横向滚动条（可使用相对单位、Flexbox、Grid 或其任意组合实现）。
3. THE **GamePage** SHALL 确保棋盘内每个单元格的触控点击区域不小于 36×36 像素，以保证手指可准确点击输入格。
4. THE **GamePage** SHALL 在用户点击输入格唤起软键盘后，自动滚动页面，确保当前被激活的输入格完整显示在可视视口内（不被软键盘遮挡）。
