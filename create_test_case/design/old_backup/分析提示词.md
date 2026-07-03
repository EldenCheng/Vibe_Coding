这是项目flowchart的图片，请帮我分析一下这个流程图, 我将使用它来生成test case.

## 分析要求

1. 记录它所有的逻辑, 判断, 步骤与内容, 特别是每一步操作之后对应播放的sound, animation, action或者特别的检查点, 这将是重要的测试要点。比如按下一个按键之后, 将会有什么表现. (例子: **Mouth Button**(Yes) -> Play **EATSTART**)

2. 记录操作之间的逻辑, 比如先做一个操作, 会有一个表现, 然后在这个表现后, 再做一个后继操作(或者相同的操作), 就会有另一个表现(**Mouth Button**(Yes) -> Play **EATSTART**->**Mouth Button**(Held less than 0.5 sec(yes))-> Play **CHOMPxx**)

3. 一个sound, animation, action或者特别的检查点要对应一个测试用例的, 所以要明确分开记录, 除非flowchart里表明多个sound, animation, action或者特别的检查点是同时播放或出现的

## 输出

生成对应的logical structure文档。并记录为一个Json格式的文件