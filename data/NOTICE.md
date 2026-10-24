# 默认题库的来源与授权

`questions.jsonl` 由下列来源转换、清洗、去重而来。它们是练习题，含 AI 生成／审核内容，不是官方真题或真人逐题审核题库。

| 来源 | 内容 | 授权 |
| --- | --- | --- |
| [iamcheyan/jlpt-drill](https://github.com/iamcheyan/jlpt-drill) | N1–N5 词汇、文法及部分阅读 | 上游 README 声明 MIT；原声明保留在 `upstream/drill-README.md` |
| [Mocas-12/Kumitaku](https://github.com/Mocas-12/jlpt-n1-Kumitaku) | N1 文法选择与排序 | MIT，原 LICENSE 保留在 `upstream/kumitaku-LICENSE` |
| [Mocas-12/Yomitaku](https://github.com/Mocas-12/jlpt-n1-Yomitaku) | N1 六类阅读 | MIT，原 LICENSE 保留在 `upstream/yomitaku-LICENSE` |
| [JLPTSuccess N4](https://github.com/gauravhq/JLPTSuccess/tree/708a995691dcd0983e2ede47db423281b1cd343a/N4) | N4 阅读 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，作者 JLPTSuccess contributors／JLPT N4 Tutor |
| [JLPTSuccess N5](https://github.com/gauravhq/JLPTSuccess/tree/708a995691dcd0983e2ede47db423281b1cd343a/N5) | N5 阅读 | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)，作者 JLPTSuccess contributors／JLPT N5 Tutor |

已作修改：统一字段、拆分文章的小题、转换答案索引、合并逐项解析、去除部分选项前缀、过滤重复和可检测的结构性错误。每条记录保留 `source_url`、`license` 和类型。JLPTSuccess N5 相关的改编内容继续按 CC BY-SA 4.0 提供；其他内容遵守对应来源条款。CC 内容的署名也会在解析中显示。

JLPTSuccess 的原始 LICENSE 与分级内容声明保留在 `upstream/success-n4-*`、`upstream/success-n5-*`。默认题库不包含官方题目图片、官方音频或 JLPTSuccess 合成音频；这些数据的本地添加方式见 [添加题库](QUESTION_BANKS.md)。

插件代码许可证不覆盖上述第三方题库内容。
