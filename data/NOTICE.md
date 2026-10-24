# 默认题库的来源与授权

`questions.jsonl` 由下列来源转换、清洗、去重而来。它们是社区练习题，包含明确的 AI 生成和 AI 审核内容；其他来源的生成方式未披露。不能将“原创”视为“人工编写”，也不能将自动校验视为逐题人工审核。

| 来源 | 内容 | 授权 |
| --- | --- | --- |
| [iamcheyan/jlpt-drill](https://github.com/iamcheyan/jlpt-drill) | N1–N5 词汇、文法及部分阅读 | 上游 README 声明 MIT；原声明保留在 `upstream/drill-README.md` |
| [Mocas-12/Kumitaku](https://github.com/Mocas-12/jlpt-n1-Kumitaku) | N1 文法选择与排序 | MIT，原 LICENSE 保留在 `upstream/kumitaku-LICENSE` |
| [Mocas-12/Yomitaku](https://github.com/Mocas-12/jlpt-n1-Yomitaku) | N1 六类阅读 | MIT，原 LICENSE 保留在 `upstream/yomitaku-LICENSE` |
| [JLPTSuccess N4](https://github.com/gauravhq/JLPTSuccess/tree/708a995691dcd0983e2ede47db423281b1cd343a/N4) | N4 阅读 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，作者 JLPTSuccess contributors／JLPT N4 Tutor |
| [JLPTSuccess N5](https://github.com/gauravhq/JLPTSuccess/tree/708a995691dcd0983e2ede47db423281b1cd343a/N5) | N5 阅读 | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)，作者 JLPTSuccess contributors／JLPT N5 Tutor |

## AI 参与情况

以下结论针对插件锁定的来源版本，不将本插件的历史标签作为生成方式的证据。

| 来源 | 已核实的情况 |
| --- | --- |
| jlpt-drill | [上游 README](upstream/drill-README.md)明确声明：所有题目、选项、解析均由大语言模型生成。部分记录附模型生成和模型审核字段，`verified: true` 不代表人工审核。 |
| Kumitaku | [README](upstream/kumitaku-README.md)声明为原创模拟题，未明确披露题目是否由 AI 生成；不能据此判断为纯人工题库。提供 AI 转录提示词也不能证明默认题目由 AI 生成。 |
| Yomitaku | [README](upstream/yomitaku-README.md)声明为原创模拟题，未明确披露题目是否由 AI 生成；不能据此判断为纯人工题库。 |
| JLPTSuccess N4 | [内容声明](upstream/success-n4-CONTENT-LICENSE.md)称项目维护者原创，未明确披露文本生成方式。额外听力使用合成语音；语音合成与题目文本生成方式是两件事。 |
| JLPTSuccess N5 | [内容声明第 9 节](upstream/success-n5-CONTENT-LICENSE.md)明确说明 `native_reviewed` 实际为 Claude 扮演母语审核者进行的 AI 审核。能确认有 AI 审核，不能据此认定全部题目由 AI 生成或已经人工审核。额外听力使用合成语音。 |
| 官方 JLPT 样题（仅本地导入） | 来源于 [JLPT 官方公开样题](https://www.jlpt.jp/e/samples/sample09.html)，属于官方试题资料，与社区生成练习题分开。 |

历史版本曾对全部社区来源统一标记 `ai_generated: true`，该标签过于粗略，现改为仅对已确认 AI 生成的来源设置此标志，并通过 `provenance` 展示上述具体情况。`ai_generated: false` 不代表已证实是人工编写。

## 清洗与使用限制

已作修改：统一字段、拆分文章的小题、转换答案索引、合并逐项解析、去除部分选项前缀、过滤重复和可检测的结构性错误。排序题需与来源完整句的星号位置一致；已排除英文释义套用的伪语境填空、重复原词的同义题及可识别的题干与解析目标词冲突，并避免在填空和汉字表记题中提示答案。完整句校验只能确认数据内部一致，无法保证语序唯一或语言正确。

每条记录保留 `source_url`、`license` 和类型。JLPTSuccess N5 相关的改编内容继续按 CC BY-SA 4.0 提供；其他内容遵守对应来源条款。CC 内容的署名也会在解析中显示。

JLPTSuccess 的原始 LICENSE 与分级内容声明保留在 `upstream/success-n4-*`、`upstream/success-n5-*`。默认题库不包含官方题目图片、官方音频或 JLPTSuccess 合成音频；这些数据的本地添加方式见 [添加题库](QUESTION_BANKS.md)。

插件代码许可证不覆盖上述第三方题库内容。
