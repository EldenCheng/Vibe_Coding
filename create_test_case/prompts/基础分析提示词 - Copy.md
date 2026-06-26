## 分析要求

1. 请仔细分析内容, 并帮我梳理其核心大意，提取出关键的数据和指标, 我需要根据它来为我的项目生成test case

2. 记录它所有的逻辑, 判断, 步骤与内容, 特别是每一步操作之后对应播放的sound, animation, action或者特别的检查点, 这将是重要的测试要点。比如, 按下一个按键之后, 被测试物将会有什么表现. (例子: **Mouth Button**(Yes) -> Play **EATSTART**)

3. 记录操作之间的逻辑, 比如先做一个操作, 被操作物会有一个表现, 然后在这个表现后, 再做一个后继操作(或者相同的操作), 被操作物就会有另一个表现(**Mouth Button**(Yes) -> Play **EATSTART**->**Mouth Button**(Held less than 0.5 sec(yes))-> Play **CHOMPxx**)

4. 一个sound, animation, action或者特别的检查点要对应一个测试用例的, 所以要明确分开记录, 除非文档里表明多个sound, animation, action或者特别的检查点是同时播放或同时出现的

## 输出

1. 输出的文档使用英文

2. 分析的结果生成对应的logical structure。并记录为一个markdown格式的文本文件  