# data/ 题库来源说明

最后核查：2026-05-04

## 结论

`data/n2/` 里的题库本体不是直接从网上下载的现成题库。它更像是由本项目的生成和抽取脚本产生：

```text
模型生成 HTML/JSON
-> extract_template.py / extract.js 抽取
-> 追加写入 data/n2/*.json
```

主要证据：

- `data/n2/*.json` 中大量题目带有 `generated_by`、`reviewed_by`、`review_explanation`、`source: ai` 等字段。
- `extract_template.py` 文件头说明它会从 `output/template.html` 抽取题目并追加到 `data/n2/*.json`，且标注模型为 Google Gemini。
- `generate_bank.py` 是配置驱动的 AI 题库生成器，目标输出就是 `data/n2/*.json`。
- 当前 git 初始提交只包含 `resources/` 和 `test_api.py` 等基础资源；`data/` 是未跟踪目录，不属于初始下载内容。

## 网上下载或参考的来源

### 已下载的官方 PDF

已从 JLPT 官方样题页下载 2012 和 2018 两套官方样题 PDF，保存到：

```text
docs/jlpt-official-pdfs/
```

当前已补齐的级别：

- N1
- N3
- N4
- N5

每个级别每个年份包含：

- `V`：文字・語彙
- `G`：文法
- `R`：読解
- `L`：聴解题册 PDF
- `sheet`：答案纸样本
- `answer`：正答表
- `script`：聴解文字稿

命名格式示例：

```text
N1V_2018.pdf
N3answer_2012.pdf
N5script_2018.pdf
```

### 1. 词汇资源

本项目的 `resources/vocabulary/n1-n5.csv` 来自：

- `stephenmk/yomitan-jlpt-vocab`
- URL: https://github.com/stephenmk/yomitan-jlpt-vocab

该仓库说明它为 Yomitan 单词添加 JLPT 级别标签，数据源来自 Jonathan Waller 的 JLPT Resources，并结合 JMdict 修正词条。

### 2. 语法资源

本项目的 `resources/grammar/n1-n5.json` 来自：

- `jkindrix/japanese-language-data`
- URL: https://github.com/jkindrix/japanese-language-data

该仓库说明它包含 595 个手工整理的 grammar points，但 grammar entries 仍是 draft，native-speaker review pending。

### 3. 汉字资源

本项目的 `resources/kanji/jlpt-kanji.json` 来自：

- `AnchorI/jlpt-kanji-dictionary`
- URL: https://github.com/AnchorI/jlpt-kanji-dictionary

该仓库说明 `jlpt-kanji.json` 是按 JLPT N5-N1 分级的汉字列表。

### 4. 官方样题和 PDF

本项目的 `docs/jlpt-official-pdfs/` 与 `docs/jlpt-n2-official-sample-questions.md` 对应 JLPT 官方样题页：

- URL: https://www.jlpt.jp/samples/sampleindex.html

官方页面提供 N1-N5 的样题 PDF、答案表、听力音频和听力文字稿。

## 使用建议

如果后续要生成 `data/n1/`、`data/n3/`、`data/n4/`、`data/n5/`，建议不要直接手写或完整搬运官方 PDF 题目，而是复刻现有链路：

```text
官方样题 PDF 用作题型结构参考
resources/vocabulary 用作词汇约束
resources/grammar 用作语法约束
resources/kanji 用作汉字约束
AI 生成候选题
本地校验 + 模型审核
写入 data/{level}/*.json
```

注意：JLPT 官方页面有版权说明，尤其 N1/N2 部分文法、读解题和听力音频包含第三方著作限制。正式发布前应避免直接复制官方题目正文作为题库内容。
