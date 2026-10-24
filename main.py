import asyncio
import math
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image, Node, Nodes, Plain, Record
from astrbot.api.star import Context, Star, register

from .quiz.bank import QuestionBank, discover_question_files
from .quiz.session import QuizSessions, Round, is_reveal_request, parse_answer, session_key
from .quiz.types import CATEGORIES, TYPES, parse_filters

ROOT = Path(__file__).resolve().parent
ROUND_EXTRA = "astrbot_plugin_jlpt_quiz:round"
READING_CHARS_PER_MINUTE = 300


class ActiveQuizAnswerFilter(filter.CustomFilter):
    """Wake only for explicit answers to an active quiz, including unmentioned replies."""

    sessions: QuizSessions | None = None

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        if not self.sessions or str(event.get_sender_id()) == str(event.get_self_id()):
            return False
        if parse_answer(event.message_str) is None and not is_reveal_request(event.message_str):
            return False
        round_ = self.sessions.active(session_key(event))
        if not round_:
            return False
        selected = parse_answer(event.message_str)
        if selected is not None and selected >= len(round_.question.options):
            return False
        # A queued answer must never be applied to a subsequent question.
        event.set_extra(ROUND_EXTRA, round_)
        return True


@register("astrbot_plugin_jlpt_quiz", "0And1Story", "JLPT 私聊刷题与群聊抢答", "0.2.0")
class JLPTQuizPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.sessions = QuizSessions()
        ActiveQuizAnswerFilter.sessions = self.sessions
        self.bank: QuestionBank | None = None
        self.tasks: set[asyncio.Task] = set()
        self.closing = False

    async def initialize(self):
        try:
            directories = [ROOT / "data", ROOT / "local_data"]
            custom = str(self.config.get("custom_bank_dir", "")).strip()
            if custom:
                directory = Path(custom).expanduser()
                if not directory.is_absolute():
                    directory = ROOT / directory
                if not directory.is_dir():
                    raise ValueError("自定义题库目录不存在")
                directories.append(directory)
            paths = discover_question_files(*directories)
            self.bank = await asyncio.to_thread(QuestionBank.load, paths)
            logger.info("[JLPT] 已加载 %s 道题目", len(self.bank.questions))
        except Exception as exc:
            logger.error("[JLPT] 加载题库失败: %s", exc)

    def integer(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(maximum, int(self.config.get(key, default))))
        except (ValueError, TypeError):
            return default

    def timeout(self, group: bool, category: str) -> int:
        if not group:
            return self.integer("private_timeout_seconds", 0, 0, 86400)
        defaults = {"vocabulary": 60, "grammar": 60, "reading": 180, "listening": 120}
        default = defaults[category]
        # Preserve the old setting as a grammar-only fallback for existing installs.
        if category == "grammar":
            default = self.integer("group_timeout_seconds", default, 5, 3600)
        return self.integer(f"group_{category}_timeout_seconds", default, 5, 3600)

    async def send_text(self, event: AstrMessageEvent, text: str):
        await event.send(event.plain_result(text).use_t2i(False))

    @filter.command("jlpt帮助", alias={"jlpthelp"})
    async def help(self, event: AstrMessageEvent):
        """查看 JLPT 刷题帮助。"""
        event.stop_event()
        await self.send_text(
            event,
            "JLPT 刷题\n"
            "/n1词汇 或 /n1ch：词汇题（n1–n5 均可）\n"
            "/n1文法 或 /n1wf：文法题（n1–n5 均可）\n"
            "/n1阅读 或 /n1yd：阅读题\n"
            "/n1听力 或 /n1tl：听力题（需题库音频）\n"
            "/n1综合：综合抽题；/jlpt题型：查看具体题型\n"
            "/jlpt抽题 文法：所有等级的文法题\n"
            "/jlpt 文法排序 n1：N1 文法排序题\n"
            "/jlpt抽题 n1 AI 或 /jlpt抽题 n1 非AI：筛选 AI 生成标记\n"
            "AI 生成默认关闭，需在配置中启用；非AI表示未标记 AI 生成，不保证人工编写。\n"
            "/jlpt抽题 真题 或 /jlpt抽题 n1 短文理解 真题：只抽取真题\n"
            "筛选条件用空格分隔、顺序不限，省略的条件不限制；/jlpt 无参数显示帮助。\n"
            "直接发送 1–4 或 A–D，无需 @机器人。\n"
            "群聊首个有效答案立即结算，答错也公布答案。\n"
            "发送「查看答案」或「放弃作答」公布答案；/jlpt结束 取消本题。\n"
            "提前公布或取消限出题者或 AstrBot 管理员。\n"
            "/jlpt题库：题目数量。来源随解析显示。",
        )

    @filter.command("jlpt题库", alias={"jlptbank"})
    async def bank_info(self, event: AstrMessageEvent):
        """查看各等级题库数量。"""
        event.stop_event()
        if not self.bank:
            await self.send_text(event, "题库未就绪，请管理员检查日志或运行 scripts/prepare_data.py。")
            return
        enabled = self.config.get("enable_ai_generated", False)
        counts = self.bank.counts(ai_generated=None if enabled else False)
        lines = [f"JLPT 当前可抽取题库（AI 生成题目{'已启用' if enabled else '已关闭'}）"]
        for n in range(1, 6):
            lines.append(
                f"N{n}：" + " / ".join(f"{name} {counts[(f'N{n}', category)]}" for category, name in CATEGORIES.items())
            )
        await self.send_text(event, "\n".join(lines))

    @filter.command("jlpt题型")
    async def type_info(self, event: AstrMessageEvent):
        """查看细分题型与已加载题数。"""
        event.stop_event()
        enabled = self.config.get("enable_ai_generated", False)
        lines = ["使用 /jlpt抽题 题型名，可加 N1–N5、AI、非AI 或真题，参数顺序不限。题量为当前可抽取总数："]
        for key, (_, name) in TYPES.items():
            count = (
                sum(q.question_type == key and (enabled or not q.ai_generated) for q in self.bank.questions)
                if self.bank
                else 0
            )
            lines.append(f"{name}：{count}")
        await self.send_text(event, "\n".join(lines))

    @filter.command("jlpt抽题")
    async def draw_type(self, event: AstrMessageEvent):
        """按等级、大类、具体题型、AI 标记和真题标记抽题；空格分隔，顺序不限。"""
        await self.draw_filtered(event, self.command_arguments(event))

    @filter.command("jlpt")
    async def jlpt(self, event: AstrMessageEvent):
        """无参数显示帮助，有参数时按条件抽题。"""
        arguments = self.command_arguments(event)
        if arguments:
            await self.draw_filtered(event, arguments)
        else:
            await self.help(event)

    @staticmethod
    def command_arguments(event: AstrMessageEvent) -> str:
        # Read the entire remainder without depending on newer AstrBot GreedyStr APIs.
        parts = event.message_str.split(maxsplit=1)
        return parts[1] if len(parts) == 2 else ""

    async def draw_filtered(self, event: AstrMessageEvent, arguments: str):
        try:
            selected = parse_filters(arguments)
        except ValueError as exc:
            event.stop_event()
            await self.send_text(event, f"{exc}\n用法：/jlpt抽题 文法排序 n1，条件用空格分隔、顺序不限。")
            return
        await self.start(event, *selected)

    async def start(
        self,
        event: AstrMessageEvent,
        level: str | None,
        category: str,
        question_type: str | None = None,
        ai_generated: bool | None = None,
        past_paper: bool = False,
    ):
        event.stop_event()
        if self.closing or str(event.get_sender_id()) == str(event.get_self_id()):
            return
        if not self.bank:
            await self.send_text(event, "题库未就绪，请管理员检查日志或运行 scripts/prepare_data.py。")
            return
        if not self.config.get("enable_ai_generated", False):
            if ai_generated is True:
                await self.send_text(event, "AI 生成题目已关闭，请先在插件配置中开启「启用 AI 生成题目」。")
                return
            ai_generated = False
        key = session_key(event)
        if key in self.sessions.rounds:
            await self.send_text(event, "本会话已有题目，请先作答，或由出题者发送 /jlpt结束。")
            return
        question = self.bank.draw(
            level,
            category,
            key,
            self.integer("recent_questions", 20, 0, 200),
            bool(self.config.get("shuffle_options", True)),
            question_type,
            ai_generated,
            past_paper,
        )
        if not question:
            await self.send_text(
                event,
                f"题库暂时没有 {level or '所有等级'} "
                f"{TYPES[question_type][1] if question_type else CATEGORIES.get(category, '综合')}题。"
                + (
                    f"当前筛选：{'仅 AI 生成' if ai_generated else '未标记 AI 生成'}。"
                    if ai_generated is not None
                    else ""
                )
                + ("当前筛选：仅真题。" if past_paper else "")
                + (
                    "可检查插件配置中的「启用 AI 生成题目」。"
                    if not self.config.get("enable_ai_generated", False)
                    else ""
                )
                + ("请导入带逐题音频的自定义题库。" if category == "listening" else ""),
            )
            return
        round_ = self.sessions.reserve(
            key, question, str(event.get_sender_id()), event.unified_msg_origin, bool(event.get_group_id())
        )
        if not round_:
            return
        timeout = self.timeout(round_.group, question.category)
        if timeout and question.category == "reading" and question.passage.strip():
            text = question.passage + question.prompt + "".join(question.options)
            characters = sum(not character.isspace() for character in text)
            estimated_seconds = math.ceil(characters * 60 / READING_CHARS_PER_MINUTE) + 30
            timeout = max(timeout, estimated_seconds)
        if timeout and question.category == "listening" and question.audio_duration_seconds:
            timeout = max(timeout, math.ceil(question.audio_duration_seconds) + 30)
        try:
            await self.send_question(event, round_, timeout)
            if self.sessions.activate(round_, timeout) and timeout:
                task = asyncio.create_task(self.expire(round_, timeout), name=f"jlpt:{question.id}")
                round_.timer = task
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
        except asyncio.CancelledError:
            self.sessions.release(round_)
            raise
        except Exception:
            self.sessions.release(round_)
            logger.exception("[JLPT] 发送题目失败，会话已清理")
            await self.send_text(event, "题目发送失败，本题已取消。请检查转发／语音权限后重试。")

    async def send_question(self, event: AstrMessageEvent, round_: Round, timeout: int):
        question = round_.question
        title = f"【JLPT {question.level} · {TYPES.get(question.question_type, ('', CATEGORIES[question.category]))[1]}】"
        if question.past_paper:
            title += "【真题】"
        notice = "OCR 识别可能不准确。\n" if question.ocr_warning else ""
        if question.passage:
            await self.send_passage(event, title, question.passage, round_.group)
        if question.passage_images:
            await self.send_passage_images(event, title, question.passage_images, round_.group)
        for path in question.images:
            await event.send(event.chain_result([self.image_component(path)]))
        if question.audio:
            audio = (
                Record.fromURL(question.audio)
                if question.audio.startswith(("https://", "http://"))
                else Record.fromFileSystem(question.audio)
            )
            await event.send(event.chain_result([audio]))
        options = "\n".join(f"{i + 1}. {option}" for i, option in enumerate(question.options))
        choices = f"1–{len(question.options)} 或 A–{'ABCD'[len(question.options) - 1]}"
        rule = "群聊抢答：首个有效答案即结算。" if round_.group else "请作答。"
        timer = f"{timeout} 秒内作答，超时公布答案。" if timeout else "本题不限时。"
        await self.send_text(
            event,
            f"{title}\n{notice}{question.prompt}\n\n{options}\n\n发送 {choices}，{rule}\n{timer}\n"
            f"出题者可发送「查看答案」或「放弃作答」。\n题号：{question.id}",
        )

    @staticmethod
    def image_component(path: str):
        return Image.fromURL(path) if path.startswith(("https://", "http://")) else Image.fromFileSystem(path)

    async def send_passage_images(self, event: AstrMessageEvent, title: str, paths: tuple[str, ...], group: bool):
        nodes = [
            Node(uin=str(event.get_self_id()), name="JLPT 阅读材料", content=[Plain(title), self.image_component(path)])
            for path in paths
        ]
        threshold = self.integer("reading_forward_threshold", 300, 0, 5000)
        if (
            group
            and len(paths) * 1000 >= threshold
            and self.config.get("reading_forward", True)
            and event.get_platform_name() == "aiocqhttp"
        ):
            try:
                await event.send(event.chain_result([Nodes(nodes)]))
                return
            except Exception:
                logger.warning("[JLPT] 图片材料转发失败，回退普通图片", exc_info=True)
        for path in paths:
            await event.send(event.chain_result([self.image_component(path)]))

    async def send_passage(self, event: AstrMessageEvent, title: str, passage: str, group: bool):
        chunks = [passage[i : i + 1500] for i in range(0, len(passage), 1500)]
        threshold = self.integer("reading_forward_threshold", 300, 0, 5000)
        if (
            group
            and len(passage) >= threshold
            and self.config.get("reading_forward", True)
            and event.get_platform_name() == "aiocqhttp"
        ):
            nodes = [
                Node(
                    uin=str(event.get_self_id()),
                    name="JLPT 阅读材料",
                    content=[Plain(f"{title} · {i + 1}/{len(chunks)}\n{chunk}")],
                )
                for i, chunk in enumerate(chunks)
            ]
            try:
                await event.send(event.chain_result([Nodes(nodes)]))
                return
            except Exception:
                logger.warning("[JLPT] 合并转发失败，回退分段文本", exc_info=True)
        for i, chunk in enumerate(chunks):
            await self.send_text(event, f"{title} 阅读材料（{i + 1}/{len(chunks)}）\n{chunk}")

    @filter.custom_filter(ActiveQuizAnswerFilter, priority=100)
    async def answer(self, event: AstrMessageEvent):
        round_ = event.get_extra(ROUND_EXTRA)
        if not isinstance(round_, Round):
            return
        if is_reveal_request(event.message_str):
            await self.control(event, True, expected_round=round_)
            return
        selected = parse_answer(event.message_str)
        if selected is None or selected >= len(round_.question.options):
            return
        if not self.sessions.claim(round_):
            event.stop_event()
            return
        event.stop_event()
        try:
            if round_.deadline is not None and time.monotonic() >= round_.deadline:
                heading = "⏰ 已超时，公布答案。"
            else:
                name = event.get_sender_name() or event.get_sender_id()
                verdict = "答对了！" if selected == round_.question.answer else "答错了。"
                heading = f"{name} 选择了 {selected + 1}（{'ABCD'[selected]}），{verdict}"
            await self.send_solution(event, round_, heading)
        finally:
            self.sessions.release(round_)

    def solution_text(self, round_: Round, heading: str) -> str:
        question = round_.question
        text = (
            f"{heading}\n"
            + ("【真题】\n" if question.past_paper else "")
            + ("OCR 识别可能不准确。\n" if question.ocr_warning else "")
            + f"题号：{question.id}\n"
            f"正确答案：{question.answer + 1}（{'ABCD'[question.answer]}）{question.options[question.answer]}\n\n"
        )
        if question.original_options and question.original_options != question.options:
            text += (
                "解析中的编号按原题顺序：\n"
                + "\n".join(f"{i + 1}（{'ABCD'[i]}）{option}" for i, option in enumerate(question.original_options))
                + "\n\n"
            )
        text += "解析：\n" + question.explanation
        if question.translation:
            text += "\n\n译文：\n" + question.translation
        if question.transcript:
            text += "\n\n听力原文：\n" + question.transcript
        if self.config.get("show_source", True) and question.source:
            text += "\n\n来源：" + question.source
            if question.provenance:
                text += "（" + question.provenance + "）"
            elif question.ai_generated:
                text += "（AI／辅助生成练习题）"
        if question.credit:
            text += "\n\n" + question.credit
            if question.source_url:
                text += "\n" + question.source_url
        return text

    async def send_solution(self, event: AstrMessageEvent, round_: Round, heading: str):
        text = self.solution_text(round_, heading)
        for i in range(0, len(text), 3000):
            await self.send_text(event, text[i : i + 3000])

    async def expire(self, round_: Round, timeout: int):
        claimed = False
        try:
            await asyncio.sleep(timeout)
            claimed = self.sessions.claim(round_)
            if not claimed:
                return
            text = self.solution_text(round_, "⏰ 超时无人作答，公布答案。")
            for i in range(0, len(text), 3000):
                result = await self.context.send_message(round_.origin, MessageChain().message(text[i : i + 3000]))
                if result is False:
                    raise RuntimeError("平台未能发送超时答案")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[JLPT] 超时答案发送失败")
        finally:
            if claimed:
                self.sessions.release(round_)

    async def control(self, event: AstrMessageEvent, reveal: bool, expected_round: Round | None = None):
        event.stop_event()
        round_ = self.sessions.rounds.get(session_key(event))
        if expected_round is not None and round_ is not expected_round:
            return
        if not round_:
            await self.send_text(event, "当前没有正在进行的题目。")
            return
        if str(event.get_sender_id()) != round_.owner_id and not event.is_admin():
            await self.send_text(event, "仅出题者或 AstrBot 管理员可以提前结束／公布答案。")
            return
        if round_.state != "active":
            await self.send_text(event, "题目正在发送或结算，请稍候。")
            return
        if not self.sessions.claim(round_):
            return
        try:
            if reveal:
                await self.send_solution(event, round_, "已提前公布答案。")
            else:
                await self.send_text(event, f"已取消题目 {round_.question.id}。")
        finally:
            self.sessions.release(round_)

    @filter.command("jlpt结束", alias={"jlpt取消", "jlptstop"})
    async def stop(self, event: AstrMessageEvent):
        """取消本题，限出题者或 AstrBot 管理员。"""
        await self.control(event, False)

    async def terminate(self):
        self.closing = True
        if ActiveQuizAnswerFilter.sessions is self.sessions:
            ActiveQuizAnswerFilter.sessions = None
        for round_ in list(self.sessions.rounds.values()):
            self.sessions.release(round_)
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()

    @filter.command("n1文法", alias={"N1WF", "N1文法", "N1wf", "n1wf"})
    async def n1_grammar(self, event: AstrMessageEvent):
        """抽取 N1 文法题。"""
        await self.start(event, "N1", "grammar")

    @filter.command("n1阅读", alias={"N1yd", "N1阅读", "N1YD", "n1yd"})
    async def n1_reading(self, event: AstrMessageEvent):
        """抽取 N1 阅读题。"""
        await self.start(event, "N1", "reading")

    @filter.command("n1听力", alias={"N1听力", "N1tl", "N1TL", "n1tl"})
    async def n1_listening(self, event: AstrMessageEvent):
        """抽取 N1 听力题。"""
        await self.start(event, "N1", "listening")

    @filter.command("n2文法", alias={"N2WF", "n2wf", "N2wf", "N2文法"})
    async def n2_grammar(self, event: AstrMessageEvent):
        """抽取 N2 文法题。"""
        await self.start(event, "N2", "grammar")

    @filter.command("n2阅读", alias={"N2yd", "N2YD", "N2阅读", "n2yd"})
    async def n2_reading(self, event: AstrMessageEvent):
        """抽取 N2 阅读题。"""
        await self.start(event, "N2", "reading")

    @filter.command("n2听力", alias={"n2tl", "N2TL", "N2听力", "N2tl"})
    async def n2_listening(self, event: AstrMessageEvent):
        """抽取 N2 听力题。"""
        await self.start(event, "N2", "listening")

    @filter.command("n3文法", alias={"n3wf", "N3WF", "N3wf", "N3文法"})
    async def n3_grammar(self, event: AstrMessageEvent):
        """抽取 N3 文法题。"""
        await self.start(event, "N3", "grammar")

    @filter.command("n3阅读", alias={"N3YD", "N3yd", "N3阅读", "n3yd"})
    async def n3_reading(self, event: AstrMessageEvent):
        """抽取 N3 阅读题。"""
        await self.start(event, "N3", "reading")

    @filter.command("n3听力", alias={"N3听力", "n3tl", "N3tl", "N3TL"})
    async def n3_listening(self, event: AstrMessageEvent):
        """抽取 N3 听力题。"""
        await self.start(event, "N3", "listening")

    @filter.command("n4文法", alias={"N4文法", "N4WF", "N4wf", "n4wf"})
    async def n4_grammar(self, event: AstrMessageEvent):
        """抽取 N4 文法题。"""
        await self.start(event, "N4", "grammar")

    @filter.command("n4阅读", alias={"n4yd", "N4yd", "N4阅读", "N4YD"})
    async def n4_reading(self, event: AstrMessageEvent):
        """抽取 N4 阅读题。"""
        await self.start(event, "N4", "reading")

    @filter.command("n4听力", alias={"N4tl", "N4TL", "n4tl", "N4听力"})
    async def n4_listening(self, event: AstrMessageEvent):
        """抽取 N4 听力题。"""
        await self.start(event, "N4", "listening")

    @filter.command("n5文法", alias={"n5wf", "N5WF", "N5文法", "N5wf"})
    async def n5_grammar(self, event: AstrMessageEvent):
        """抽取 N5 文法题。"""
        await self.start(event, "N5", "grammar")

    @filter.command("n5阅读", alias={"n5yd", "N5阅读", "N5yd", "N5YD"})
    async def n5_reading(self, event: AstrMessageEvent):
        """抽取 N5 阅读题。"""
        await self.start(event, "N5", "reading")

    @filter.command("n5听力", alias={"N5tl", "N5听力", "n5tl", "N5TL"})
    async def n5_listening(self, event: AstrMessageEvent):
        """抽取 N5 听力题。"""
        await self.start(event, "N5", "listening")

    @filter.command("n1词汇", alias={"n1ch", "N1词汇", "N1ch"})
    async def n1_vocabulary(self, event: AstrMessageEvent):
        """抽取 N1 词汇题。"""
        await self.start(event, "N1", "vocabulary")

    @filter.command("n1综合", alias={"n1jlpt", "N1综合", "N1jlpt"})
    async def n1_all(self, event: AstrMessageEvent):
        """抽取 N1 综合题。"""
        await self.start(event, "N1", "all")

    @filter.command("n2词汇", alias={"n2ch", "N2词汇", "N2ch"})
    async def n2_vocabulary(self, event: AstrMessageEvent):
        """抽取 N2 词汇题。"""
        await self.start(event, "N2", "vocabulary")

    @filter.command("n2综合", alias={"n2jlpt", "N2综合", "N2jlpt"})
    async def n2_all(self, event: AstrMessageEvent):
        """抽取 N2 综合题。"""
        await self.start(event, "N2", "all")

    @filter.command("n3词汇", alias={"n3ch", "N3词汇", "N3ch"})
    async def n3_vocabulary(self, event: AstrMessageEvent):
        """抽取 N3 词汇题。"""
        await self.start(event, "N3", "vocabulary")

    @filter.command("n3综合", alias={"n3jlpt", "N3综合", "N3jlpt"})
    async def n3_all(self, event: AstrMessageEvent):
        """抽取 N3 综合题。"""
        await self.start(event, "N3", "all")

    @filter.command("n4词汇", alias={"n4ch", "N4词汇", "N4ch"})
    async def n4_vocabulary(self, event: AstrMessageEvent):
        """抽取 N4 词汇题。"""
        await self.start(event, "N4", "vocabulary")

    @filter.command("n4综合", alias={"n4jlpt", "N4综合", "N4jlpt"})
    async def n4_all(self, event: AstrMessageEvent):
        """抽取 N4 综合题。"""
        await self.start(event, "N4", "all")

    @filter.command("n5词汇", alias={"n5ch", "N5词汇", "N5ch"})
    async def n5_vocabulary(self, event: AstrMessageEvent):
        """抽取 N5 词汇题。"""
        await self.start(event, "N5", "vocabulary")

    @filter.command("n5综合", alias={"n5jlpt", "N5综合", "N5jlpt"})
    async def n5_all(self, event: AstrMessageEvent):
        """抽取 N5 综合题。"""
        await self.start(event, "N5", "all")
