# 添加题库

插件自动加载 `data/*.jsonl`（默认题库）和 `local_data/*.jsonl`（本地自用题库）。添加后重载插件。`local_data/` 已被 Git 忽略；也可以在设置中指定其他题库目录。

## 官方 JLPT 样题（自行下载）

[官方交互样题](https://www.jlpt.jp/e/samples/forlearners.html)涵盖 N1–N5 各等级题型，带答案、题目图片和逐题听力音频。官方素材保留原权利人的权利，转换结果仅保存在本地，不随插件分发。官方样题没有完整的逐题解析，插件会如实显示这一点。

需要 Node.js，在插件目录执行一次：

```bash
npm install --prefix tmp/tools playwright
node tmp/tools/node_modules/playwright/cli.js install chromium
node scripts/import_official.mjs
```

完成后重载插件。本地会增加 84 道样题，覆盖词汇、文法、阅读、听力共 21 个细分题型。图片和音频保存在 `local_data/official/`，请勿只复制 JSONL 而遗漏媒体。

## JLPTSuccess 额外听力（自行下载）

[JLPTSuccess](https://github.com/gauravhq/JLPTSuccess) 提供 N4/N5 合成语音听力，解析以英文为主。文本和音频分别有内容许可及语音提供方／角色条款；本插件将这批音频作为本地导入，不默认分发。

需要 Python ≥ 3.10：

```bash
python scripts/import_success_audio.py
```

来源含 N4 30 道、N5 50 道听力；导入器会剔除重复选项等无效题目，实际数量以输出为准。安装了 ffprobe 时还会读取实际音频时长。下载的来源声明保留在 `tmp/private_sources/success/`，转换结果和音频保存在 `local_data/`。

## jlpt-test 新制真题（试导入）

[jlpt-test](https://github.com/eulerex/jlpt-test) 收录历年试题的提取文本，原始试卷和听力音频未包含在仓库中。需要 Python ≥ 3.10：

```bash
python scripts/import_jlpt_test.py
```

当前可导入 49 道词汇、文法题（N1 26 道、N4 23 道），重载插件后可用。仅处理 2010 年起的新制题目，跳过 OCR 题面、答案无法对齐、版式缺失及已发现的转录错误；暂不导入阅读、听力、排序等题型，也没有可靠的逐题解析。

来源未提供再分发许可，题目仅写入 Git 忽略的 `local_data/jlpt-test.jsonl`。下载缓存及导入报告在 `tmp/`，不随插件分发。

## 自有 JSONL 题库

每行一个 UTF-8 JSON 对象，例如：

```json
{"id":"my-n5-001","level":"N5","category":"vocabulary","question_type":"vocab_reading","prompt":"「学校」的读音是？","options":["がっこう","がこう","かっこう","がくこ"],"answer":0,"explanation":"「学校」读作「がっこう」。"}
```

- `category`：`vocabulary`／`grammar`／`reading`／`listening`。
- `question_type`：可选，细分题型代码见 `/jlpt题型` 对应名称；常用代码有 `vocab_reading`、`grammar_order`、`reading_short`、`listening_task`。
- `options`：三个或四个不同选项；`answer` 从 0 开始。ID 必须唯一。
- 阅读需提供 `passage` 或 `passage_images`；听力需提供 `audio`。`transcript`、`translation` 在结算后显示。
- `images`／`passage_images` 为图片路径数组；本地媒体路径相对于 JSONL，必须位于题库目录内。媒体也可使用 HTTP(S) URL。
- 图片题或音频内含选项编号时，设 `shuffle_options: false`，避免编号错位。
- 可用 `provenance` 说明生成与审核方式；`ai_generated: true` 表示已确认由 AI 生成，未标记不代表已确认人工编写。

仅添加自己有权使用的材料，并保留对应作者、来源与使用条件。
