"""Exercise the adapter with API doubles; no real QQ messages are sent."""

import asyncio
import importlib.util
import logging
import sys
import time
import types
import unittest
from pathlib import Path


def load_plugin():
    modules = {}
    for name in ("astrbot", "astrbot.api", "astrbot.api.event", "astrbot.api.star", "astrbot.api.message_components"):
        modules[name] = types.ModuleType(name)

    class CustomFilter:
        def __init__(self, *args, **kwargs):
            pass

    def command(name, alias=None, **kwargs):
        def decorate(function):
            function.commands = {name, *(alias or set())}
            return function

        return decorate

    def custom_filter(cls, **kwargs):
        def decorate(function):
            function.answer_filter = cls()
            return function

        return decorate

    class Star:
        def __init__(self, context):
            self.context = context

    class MessageChain:
        def __init__(self):
            self.text = ""

        def message(self, text):
            self.text += text
            return self

    class Component:
        def __init__(self, *args, **kwargs):
            self.args, self.kwargs = args, kwargs

        @classmethod
        def fromURL(cls, url):
            return cls(file=url)

        @classmethod
        def fromFileSystem(cls, path):
            return cls(file=path)

    modules["astrbot.api"].AstrBotConfig = dict
    modules["astrbot.api"].logger = logging.getLogger("jlpt-test")
    event_api = modules["astrbot.api.event"]
    event_api.AstrMessageEvent = object
    event_api.MessageChain = MessageChain
    event_api.filter = types.SimpleNamespace(command=command, custom_filter=custom_filter, CustomFilter=CustomFilter)
    modules["astrbot.api.star"].Star = Star
    modules["astrbot.api.star"].Context = object
    modules["astrbot.api.star"].register = lambda *args: lambda cls: cls
    for name in ("Node", "Nodes", "Plain", "Record", "Image"):
        setattr(modules["astrbot.api.message_components"], name, type(name, (Component,), {}))
    package = types.ModuleType("jlpt_test_adapter")
    package.__path__ = [str(Path(__file__).resolve().parents[1])]
    modules["jlpt_test_adapter"] = package
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        spec = importlib.util.spec_from_file_location("jlpt_test_adapter.main", Path(package.__path__[0]) / "main.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


plugin = load_plugin()
TEST_QUESTIONS = tuple(
    plugin.QuestionBank.load(plugin.discover_question_files(Path(__file__).resolve().parents[1] / "data")).questions
)


class Result:
    def __init__(self, text="", chain=None):
        self.text, self.chain = text, chain

    def use_t2i(self, enabled):
        return self


class Event:
    def __init__(self, sender="alice", group="group1", platform="qq1", message="", admin=False):
        self.sender, self.group, self.platform = sender, group, platform
        self.message_str, self.admin = message, admin
        self.unified_msg_origin = f"{platform}:{group or sender}"
        self.messages, self.extras = [], {}
        self.stopped = False
        self.fail_forward = False
        self.fail_send = False

    def get_group_id(self):
        return self.group

    def get_sender_id(self):
        return self.sender

    def get_self_id(self):
        return "bot"

    def get_sender_name(self):
        return self.sender

    def get_platform_id(self):
        return self.platform

    def get_platform_name(self):
        return "aiocqhttp"

    def is_admin(self):
        return self.admin

    def set_extra(self, key, value):
        self.extras[key] = value

    def get_extra(self, key):
        return self.extras.get(key)

    def stop_event(self):
        self.stopped = True

    def plain_result(self, text):
        return Result(text)

    def chain_result(self, chain):
        return Result(chain=chain)

    async def send(self, result):
        if self.fail_send or (self.fail_forward and result.chain and isinstance(result.chain[0], plugin.Nodes)):
            raise RuntimeError("simulated delivery failure")
        self.messages.append(result)


class Context:
    def __init__(self):
        self.sent = []

    async def send_message(self, origin, chain):
        self.sent.append((origin, chain.text))
        return True


class PluginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.context = Context()
        self.bot = plugin.JLPTQuizPlugin(self.context, {"shuffle_options": False, "enable_ai_generated": True})
        self.bot.bank = plugin.QuestionBank(list(TEST_QUESTIONS))

    async def asyncTearDown(self):
        await self.bot.terminate()

    def filter_answer(self, event):
        return plugin.ActiveQuizAnswerFilter().filter(event, {})

    async def test_commands_include_every_level_category_and_alias(self):
        commands = set().union(
            *(getattr(getattr(type(self.bot), name), "commands", set()) for name in dir(type(self.bot)))
        )
        for n in range(1, 6):
            for suffix in ("词汇", "ch", "文法", "wf", "阅读", "yd", "听力", "tl", "综合"):
                self.assertIn(f"n{n}{suffix}", commands)
            self.assertIn(f"N{n}综合", commands)
            self.assertNotIn(f"n{n}全部", commands)
            self.assertNotIn(f"N{n}全部", commands)
        self.assertTrue({"答题", "jlpt答案", "jlptanswer"}.isdisjoint(commands))

    async def test_bare_jlpt_routes_to_help(self):
        expected = Event()
        await self.bot.help(expected)
        for command in ("/jlpt", "jlpt", "  jlpt \t "):
            event = Event(message=command)
            await self.bot.jlpt(event)
            self.assertEqual(event.messages[0].text, expected.messages[0].text)
            self.assertTrue(event.stopped)
        self.assertFalse(self.bot.sessions.rounds)

    async def test_jlpt_and_draw_share_unordered_filters(self):
        for index, command in enumerate(
            ("/jlpt 文法排序 n1", "jlpt N1 文法排序", "/jlpt抽题 文法排序 n1", "jlpt抽题 n1 文法 文法排序")
        ):
            event = Event(group=f"filter-{index}", message=command)
            handler = self.bot.draw_type if "抽题" in command else self.bot.jlpt
            await handler(event)
            question = self.bot.sessions.active(plugin.session_key(event)).question
            self.assertEqual((question.level, question.question_type), ("N1", "grammar_order"))
            self.assertTrue(event.stopped)

    async def test_optional_filters_reach_the_question_bank(self):
        from unittest.mock import AsyncMock

        self.bot.start = AsyncMock()
        for command, expected in (
            ("/jlpt抽题 文法", (None, "grammar", None, None, False)),
            ("/jlpt抽题 n5", ("N5", "all", None, None, False)),
            ("/jlpt抽题", (None, "all", None, None, False)),
            ("/jlpt 词汇填空", (None, "vocabulary", "vocab_context", None, False)),
            ("/jlpt抽题 短文理解 n1 真题", ("N1", "reading", "reading_short", None, True)),
        ):
            event = Event(message=command)
            handler = self.bot.draw_type if "抽题" in command else self.bot.jlpt
            await handler(event)
            self.bot.start.assert_awaited_with(event, *expected)

    async def test_past_paper_label_and_ocr_warning_are_visible_in_question_and_solution(self):
        from dataclasses import replace

        question = replace(TEST_QUESTIONS[0], past_paper=True, ocr_warning=True, shuffle_options=False)
        self.bot.bank = plugin.QuestionBank([question])
        event = Event()
        await self.bot.start(event, question.level, question.category)
        question_text = event.messages[-1].text
        self.assertIn("真题", question_text)
        self.assertIn("OCR 识别可能不准确", question_text)

        answer = Event(message="1")
        self.assertTrue(self.filter_answer(answer))
        await self.bot.answer(answer)
        solution_text = "\n".join(message.text for message in answer.messages)
        self.assertIn("真题", solution_text)
        self.assertIn("OCR 识别可能不准确", solution_text)

    async def test_invalid_filters_do_not_start_a_round(self):
        for command in ("/jlpt抽题 文法排序 n1 拼写错误", "/jlpt 阅读 文法排序", "/jlpt抽题 n1 n2"):
            event = Event(message=command)
            handler = self.bot.draw_type if "抽题" in command else self.bot.jlpt
            await handler(event)
            self.assertIn("用法：", event.messages[-1].text)
            self.assertTrue(event.stopped)
        self.assertFalse(self.bot.sessions.rounds)

    def use_ai_test_bank(self):
        from dataclasses import replace

        original = next(q for q in TEST_QUESTIONS if q.category == "grammar")
        self.bot.bank = plugin.QuestionBank(
            [
                replace(original, id="ai", level="N1", question_type="grammar_fill", ai_generated=True),
                replace(
                    original,
                    id="unknown",
                    level="N1",
                    question_type="grammar_fill",
                    ai_generated=False,
                    provenance="是否由 AI 生成未披露",
                ),
                replace(
                    original,
                    id="reviewed",
                    level="N1",
                    question_type="grammar_fill",
                    ai_generated=False,
                    provenance="含 Claude AI 审核",
                ),
            ]
        )

    async def test_ai_questions_are_disabled_by_default_for_shortcuts_and_generic_draws(self):
        self.use_ai_test_bank()
        self.bot.config.pop("enable_ai_generated")
        for index, (handler, command) in enumerate(
            (
                (self.bot.n1_grammar, "n1wf"),
                (self.bot.n1_all, "n1综合"),
                (self.bot.draw_type, "jlpt抽题 文法"),
                (self.bot.jlpt, "jlpt 文法选择 n1"),
            )
        ):
            event = Event(group=f"disabled-{index}", message=command)
            await handler(event)
            round_ = self.bot.sessions.active(plugin.session_key(event))
            self.assertIsNotNone(round_)
            self.assertFalse(round_.question.ai_generated)

    async def test_ai_selector_cannot_override_the_disabled_setting(self):
        self.use_ai_test_bank()
        self.bot.config["enable_ai_generated"] = False
        for handler, command in (
            (self.bot.draw_type, "jlpt抽题 AI 文法 n1"),
            (self.bot.jlpt, "jlpt n1 ai"),
        ):
            event = Event(message=command)
            await handler(event)
            self.assertIn("AI 生成题目已关闭", event.messages[-1].text)
            self.assertTrue(event.stopped)
        self.assertFalse(self.bot.sessions.rounds)
        self.assertFalse(self.bot.tasks)

    async def test_ai_and_non_ai_selectors_work_in_both_command_forms(self):
        self.use_ai_test_bank()
        cases = (
            ("jlpt抽题 AI n1 文法选择", True),
            ("jlpt n1 文法选择 ai生成", True),
            ("jlpt抽题 非AI n1 文法", False),
            ("jlpt 文法选择 非ai生成 n1", False),
        )
        for index, (command, expected) in enumerate(cases):
            event = Event(group=f"selector-{index}", message=command)
            handler = self.bot.draw_type if "抽题" in command else self.bot.jlpt
            await handler(event)
            question = self.bot.sessions.active(plugin.session_key(event)).question
            self.assertEqual(question.ai_generated, expected)
            self.assertEqual((question.level, question.question_type), ("N1", "grammar_fill"))

    async def test_conflicting_ai_selectors_do_not_start_a_round(self):
        event = Event(message="jlpt抽题 文法 AI 非AI")
        await self.bot.draw_type(event)
        self.assertIn("AI 筛选条件冲突", event.messages[-1].text)
        self.assertFalse(self.bot.sessions.rounds)

    async def test_ai_setting_changes_affect_subsequent_draws_without_reloading(self):
        self.use_ai_test_bank()
        for index, enabled in enumerate((False, True, False)):
            self.bot.config["enable_ai_generated"] = enabled
            event = Event(group=f"toggle-{index}")
            await self.bot.start(event, "N1", "grammar", ai_generated=True if enabled else None)
            question = self.bot.sessions.active(plugin.session_key(event)).question
            self.assertEqual(question.ai_generated, enabled)

    async def test_ai_setting_controls_bank_and_subtype_counts(self):
        self.use_ai_test_bank()
        for enabled, expected in ((False, 2), (True, 3)):
            self.bot.config["enable_ai_generated"] = enabled
            bank = Event()
            await self.bot.bank_info(bank)
            self.assertIn(f"文法 {expected}", bank.messages[0].text)
            self.assertIn("已启用" if enabled else "已关闭", bank.messages[0].text)
            types = Event()
            await self.bot.type_info(types)
            self.assertIn(f"文法选择：{expected}", types.messages[0].text)

    async def test_empty_pool_after_excluding_ai_explains_the_setting(self):
        self.use_ai_test_bank()
        self.bot.bank = plugin.QuestionBank([self.bot.bank.questions[0]])
        self.bot.config["enable_ai_generated"] = False
        event = Event()
        await self.bot.start(event, "N1", "grammar")
        self.assertIn("未标记 AI 生成", event.messages[-1].text)
        self.assertIn("启用 AI 生成题目", event.messages[-1].text)
        self.assertFalse(self.bot.sessions.rounds)
        self.assertFalse(self.bot.tasks)

    async def test_removed_answer_command_does_not_intercept_another_plugin(self):
        await self.bot.start(Event(), "N5", "grammar")
        for message in ("/答题 1", "答题 1", "/jlpt答案", "jlpt答案", "jlptanswer"):
            self.assertFalse(self.filter_answer(Event(message=message)))

    async def test_type_specific_timeouts_and_private_default(self):
        self.assertEqual(self.bot.timeout(True, "grammar"), 60)
        self.assertEqual(self.bot.timeout(True, "reading"), 180)
        self.assertEqual(self.bot.timeout(True, "listening"), 120)
        for category in ("grammar", "reading", "listening"):
            self.assertEqual(self.bot.timeout(False, category), 0)
        self.bot.config.update(group_reading_timeout_seconds=240, group_listening_timeout_seconds=150)
        self.assertEqual(self.bot.timeout(True, "grammar"), 60)
        self.assertEqual(self.bot.timeout(True, "reading"), 240)
        self.assertEqual(self.bot.timeout(True, "listening"), 150)

    async def test_private_default_creates_no_timer(self):
        await self.bot.start(Event(group=""), "N5", "grammar")
        round_ = next(iter(self.bot.sessions.rounds.values()))
        self.assertIsNone(round_.deadline)
        self.assertIsNone(round_.timer)
        self.assertFalse(self.bot.tasks)

    async def test_reading_start_uses_reading_timeout(self):
        from dataclasses import replace

        question = replace(next(q for q in TEST_QUESTIONS if q.category == "reading"), passage="短文です。")
        self.bot.bank = plugin.QuestionBank([question])
        self.bot.config["group_reading_timeout_seconds"] = 245
        event = Event()
        await self.bot.start(event, question.level, "reading")
        self.assertIn("245 秒内作答", event.messages[-1].text)

    async def test_long_reading_timeout_counts_all_visible_text_and_ignores_whitespace(self):
        from dataclasses import replace

        question = replace(
            next(q for q in TEST_QUESTIONS if q.category == "reading"),
            passage="あ" * 1002 + " \n\t　" * 1000,
            prompt="い" * 100,
            options=tuple("う" * 100 + label for label in "ABCD"),
        )
        self.bot.bank = plugin.QuestionBank([question])
        self.bot.config["group_reading_timeout_seconds"] = 60
        event = Event()
        await self.bot.start(event, question.level, "reading")
        # 1,506 visible characters take 302 seconds, plus 30 seconds to decide.
        self.assertIn("332 秒内作答", event.messages[-1].text)
        round_ = self.bot.sessions.active(plugin.session_key(event))
        self.assertAlmostEqual(round_.deadline - time.monotonic(), 332, delta=1)

    async def test_private_reading_extends_only_when_a_timeout_is_enabled(self):
        from dataclasses import replace

        question = replace(next(q for q in TEST_QUESTIONS if q.category == "reading"), passage="あ" * 3000)
        self.bot.bank = plugin.QuestionBank([question])
        event = Event(group="")
        await self.bot.start(event, question.level, "reading")
        self.assertIn("本题不限时", event.messages[-1].text)
        round_ = self.bot.sessions.active(plugin.session_key(event))
        self.assertIsNone(round_.deadline)
        self.assertIsNone(round_.timer)

        self.bot.config["private_timeout_seconds"] = 60
        timed = Event(group="", sender="bob")
        await self.bot.start(timed, question.level, "reading")
        round_ = self.bot.sessions.active(plugin.session_key(timed))
        self.assertGreater(round_.deadline - time.monotonic(), 600)
        self.assertIsNotNone(round_.timer)

    async def test_image_only_reading_uses_configured_timeout(self):
        from dataclasses import replace

        question = replace(
            next(q for q in TEST_QUESTIONS if q.category == "reading"),
            passage=" \n\t　",
            passage_images=("https://example.com/passage.png",),
        )
        self.bot.bank = plugin.QuestionBank([question])
        self.bot.config["group_reading_timeout_seconds"] = 90
        event = Event()
        await self.bot.start(event, question.level, "reading")
        self.assertIn("90 秒内作答", event.messages[-1].text)

    async def test_zero_threshold_folds_short_passages(self):
        self.bot.config["reading_forward_threshold"] = 0
        event = Event()
        await self.bot.send_passage(event, "阅读", "短文です。", True)
        self.assertIsInstance(event.messages[0].chain[0], plugin.Nodes)
        self.bot.config["reading_forward"] = False
        plain = Event()
        await self.bot.send_passage(plain, "阅读", "短文です。", True)
        self.assertIn("短文です。", plain.messages[0].text)

    async def test_reveal_phrases_only_wake_during_active_round(self):
        for message in ("查看答案", "放弃作答"):
            self.assertFalse(self.filter_answer(Event(message=message)))
        await self.bot.start(Event(), "N5", "grammar")
        for message in ("查看答案", "放弃作答"):
            self.assertTrue(self.filter_answer(Event(message=message)))
        self.assertFalse(self.filter_answer(Event(message="我想查看答案了")))

    async def test_give_up_reveals_answer(self):
        await self.bot.start(Event(), "N5", "grammar")
        event = Event(message="放弃作答")
        self.assertTrue(self.filter_answer(event))
        await self.bot.answer(event)
        self.assertIn("正确答案", event.messages[0].text)
        self.assertFalse(self.bot.sessions.rounds)

    async def test_three_option_question_ignores_fourth_answer(self):
        from dataclasses import replace

        original = TEST_QUESTIONS[0]
        question = replace(original, options=("甲", "乙", "丙"), answer=1)
        self.bot.bank = plugin.QuestionBank([question])
        event = Event()
        await self.bot.start(event, question.level, question.category)
        self.assertFalse(self.filter_answer(Event(message="4")))
        self.assertFalse(self.filter_answer(Event(message="D")))
        self.assertTrue(self.filter_answer(Event(message="3")))

    async def test_listening_timeout_allows_complete_playback(self):
        from dataclasses import replace

        original = TEST_QUESTIONS[0]
        question = replace(
            original,
            category="listening",
            question_type="listening_integrated",
            audio="https://example.com/clip.mp3",
            audio_duration_seconds=132.3,
        )
        self.bot.bank = plugin.QuestionBank([question])
        event = Event()
        await self.bot.start(event, question.level, "listening")
        self.assertIn("163 秒内作答", event.messages[-1].text)

    async def test_image_question_keeps_image_and_answer_numbering(self):
        from dataclasses import replace

        question = replace(TEST_QUESTIONS[0], images=("https://example.com/question.png",), shuffle_options=False)
        self.bot.bank = plugin.QuestionBank([question])
        self.bot.config["shuffle_options"] = True
        event = Event()
        await self.bot.start(event, question.level, question.category)
        self.assertIsInstance(event.messages[0].chain[0], plugin.Image)
        self.assertEqual(next(iter(self.bot.sessions.rounds.values())).question.options, question.options)

    async def test_vocab_command_and_subtype_command(self):
        event = Event()
        await self.bot.n5_vocabulary(event)
        round_ = next(iter(self.bot.sessions.rounds.values()))
        self.assertEqual(round_.question.category, "vocabulary")
        await self.bot.stop(Event())
        await self.bot.draw_type(Event(message="jlpt抽题 N1 文法排序"))
        round_ = next(iter(self.bot.sessions.rounds.values()))
        self.assertEqual(round_.question.question_type, "grammar_order")

    async def test_cc_attribution_cannot_be_hidden_by_source_toggle(self):
        from dataclasses import replace

        question = replace(
            TEST_QUESTIONS[0], credit="JLPTSuccess · CC BY-SA 4.0", source_url="https://example.com/source"
        )
        self.bot.config["show_source"] = False
        round_ = self.bot.sessions.reserve(("test",), question, "alice", "origin", True)
        result = self.bot.solution_text(round_, "答案")
        self.assertIn("CC BY-SA 4.0", result)
        self.assertIn("https://example.com/source", result)

    async def test_source_notes_distinguish_unknown_generation_and_ai_review(self):
        from dataclasses import replace

        for note in ("是否由 AI 生成未披露", "原始生成方式未披露；含 Claude AI 审核"):
            question = replace(TEST_QUESTIONS[0], ai_generated=False, provenance=note)
            round_ = plugin.Round(("test",), question, "alice", "origin", True)
            result = self.bot.solution_text(round_, "答案")
            self.assertIn(note, result)
            self.assertNotIn("AI／辅助生成练习题", result)

    async def test_legacy_custom_bank_ai_flag_keeps_its_source_label(self):
        from dataclasses import replace

        question = replace(TEST_QUESTIONS[0], ai_generated=True, provenance="")
        result = self.bot.solution_text(plugin.Round(("test",), question, "alice", "origin", True), "答案")
        self.assertIn("AI／辅助生成练习题", result)

    async def test_reveal_phrase_keeps_owner_permission(self):
        await self.bot.start(Event(), "N5", "grammar")
        event = Event(sender="bob", message="查看答案")
        self.assertTrue(self.filter_answer(event))
        await self.bot.answer(event)
        self.assertIn("仅出题者", event.messages[0].text)
        self.assertIsNotNone(self.bot.sessions.active(plugin.session_key(event)))
        admin = Event(sender="admin", admin=True, message="放弃作答")
        self.filter_answer(admin)
        await self.bot.answer(admin)
        self.assertIn("正确答案", admin.messages[0].text)

    async def test_stale_reveal_request_never_reveals_next_question(self):
        await self.bot.start(Event(), "N1", "grammar")
        stale = Event(message="查看答案")
        self.assertTrue(self.filter_answer(stale))
        await self.bot.stop(Event())
        await self.bot.start(Event(), "N5", "grammar")
        await self.bot.answer(stale)
        self.assertFalse(stale.messages)
        self.assertEqual(len(self.bot.sessions.rounds), 1)

    async def test_group_answer_from_another_user_needs_no_mention(self):
        await self.bot.n1_grammar(Event())
        answer = Event(sender="bob", message="A")
        self.assertTrue(self.filter_answer(answer))
        await self.bot.answer(answer)
        self.assertIn("正确答案", answer.messages[0].text)
        self.assertTrue(answer.stopped)
        self.assertFalse(self.bot.sessions.rounds)

    async def test_wrong_first_answer_also_ends_group_round(self):
        await self.bot.start(Event(), "N5", "grammar")
        round_ = next(iter(self.bot.sessions.rounds.values()))
        answer = Event(sender="bob", message=str((round_.question.answer + 1) % 4 + 1))
        self.assertTrue(self.filter_answer(answer))
        await self.bot.answer(answer)
        self.assertIn("答错了", answer.messages[0].text)
        self.assertFalse(self.bot.sessions.rounds)

    async def test_parallel_answers_only_send_one_solution(self):
        await self.bot.start(Event(), "N1", "grammar")
        answers = [Event(sender=str(i), message="1") for i in range(12)]
        self.assertTrue(all(self.filter_answer(e) for e in answers))
        await asyncio.gather(*(self.bot.answer(e) for e in answers))
        self.assertEqual(sum(len(e.messages) for e in answers), 1)

    async def test_inactive_or_unrelated_chat_does_not_wake(self):
        self.assertFalse(self.filter_answer(Event(message="1")))
        await self.bot.start(Event(), "N1", "grammar")
        self.assertFalse(self.filter_answer(Event(message="今晚1点开始吗")))
        self.assertFalse(self.filter_answer(Event(message="1", group="other")))
        self.assertFalse(self.filter_answer(Event(message="1", platform="qq2")))

    async def test_private_chats_isolated_by_sender(self):
        await self.bot.start(Event(group=""), "N5", "grammar")
        self.assertFalse(self.filter_answer(Event(sender="bob", group="", message="1")))
        self.assertTrue(self.filter_answer(Event(group="", message="1")))

    async def test_duplicate_start_preserves_existing_question(self):
        first = Event()
        await self.bot.start(first, "N1", "grammar")
        round_ = next(iter(self.bot.sessions.rounds.values()))
        duplicate = Event(sender="bob")
        await self.bot.start(duplicate, "N5", "grammar")
        self.assertIs(next(iter(self.bot.sessions.rounds.values())), round_)
        self.assertIn("已有题目", duplicate.messages[0].text)

    async def test_stale_queued_answer_never_answers_new_round(self):
        await self.bot.start(Event(), "N1", "grammar")
        stale = Event(sender="bob", message="1")
        self.assertTrue(self.filter_answer(stale))
        await self.bot.stop(Event())
        await self.bot.start(Event(), "N5", "grammar")
        await self.bot.answer(stale)
        self.assertFalse(stale.messages)
        self.assertEqual(len(self.bot.sessions.rounds), 1)

    async def test_timeout_pushes_once_to_original_origin(self):
        self.bot.timeout = lambda group, category: 0.01
        event = Event()
        await self.bot.start(event, "N1", "grammar")
        await asyncio.gather(*list(self.bot.tasks))
        self.assertEqual(len(self.context.sent), 1)
        self.assertEqual(self.context.sent[0][0], event.unified_msg_origin)
        self.assertIn("超时无人作答", self.context.sent[0][1])
        self.assertFalse(self.bot.sessions.rounds)

    async def test_answer_cancels_timeout_without_double_publication(self):
        self.bot.timeout = lambda group, category: 0.01
        await self.bot.start(Event(), "N1", "grammar")
        tasks = list(self.bot.tasks)
        answer = Event(message="1")
        self.filter_answer(answer)
        await self.bot.answer(answer)
        await asyncio.gather(*tasks, return_exceptions=True)
        self.assertFalse(self.context.sent)
        self.assertFalse(self.bot.sessions.rounds)

    async def test_expired_answer_reports_timeout(self):
        await self.bot.start(Event(), "N1", "grammar")
        next(iter(self.bot.sessions.rounds.values())).deadline = time.monotonic() - 1
        answer = Event(message="1")
        self.filter_answer(answer)
        await self.bot.answer(answer)
        self.assertIn("已超时", answer.messages[0].text)

    async def test_cancel_restricted_to_owner_or_admin(self):
        await self.bot.start(Event(), "N1", "grammar")
        denied = Event(sender="bob")
        await self.bot.stop(denied)
        self.assertEqual(len(self.bot.sessions.rounds), 1)
        await self.bot.stop(Event(sender="admin", admin=True))
        self.assertFalse(self.bot.sessions.rounds)

    async def test_reading_forward_failure_falls_back_to_text(self):
        self.bot.config["reading_forward_threshold"] = 100
        event = Event()
        event.fail_forward = True
        await self.bot.start(event, "N2", "reading")
        self.assertTrue(self.bot.sessions.active(plugin.session_key(event)))
        self.assertIn("阅读材料", event.messages[0].text)

    async def test_question_send_failure_releases_reservation(self):
        event = Event()
        event.fail_send = True
        with self.assertRaises(RuntimeError):
            await self.bot.start(event, "N1", "grammar")
        self.assertFalse(self.bot.sessions.rounds)
        self.assertFalse(self.bot.tasks)

    async def test_answers_ignored_until_entire_question_delivered(self):
        event = Event()
        original_send = event.send

        async def send(result):
            self.assertFalse(self.filter_answer(Event(message="1")))
            await original_send(result)

        event.send = send
        await self.bot.start(event, "N1", "grammar")
        self.assertTrue(self.filter_answer(Event(message="1")))

    async def test_missing_audio_bank_reports_unavailable(self):
        event = Event()
        await self.bot.n1_listening(event)
        self.assertIn("没有 N1 听力题", event.messages[0].text)
        self.assertFalse(self.bot.sessions.rounds)

    async def test_audio_sent_as_record_and_transcript_only_after_answer(self):
        question = plugin.QuestionBank.load(
            plugin.discover_question_files(Path(__file__).resolve().parents[1] / "data")
        ).questions[0]
        from dataclasses import replace

        listening = replace(
            question,
            id="custom-listening",
            category="listening",
            audio="https://example.com/test.wav",
            transcript="仅结算后显示的听力原文",
        )
        self.bot.bank = plugin.QuestionBank([listening])
        event = Event()
        await self.bot.start(event, listening.level, "listening")
        self.assertIsInstance(event.messages[0].chain[0], plugin.Record)
        self.assertEqual(event.messages[0].chain[0].kwargs["file"], listening.audio)
        self.assertFalse(any(listening.transcript in message.text for message in event.messages))
        answer = Event(message="1")
        self.assertTrue(self.filter_answer(answer))
        await self.bot.answer(answer)
        self.assertTrue(any(listening.transcript in message.text for message in answer.messages))

    async def test_reading_forward_is_a_single_nodes_message(self):
        event = Event()
        await self.bot.send_passage(event, "阅读", "日" * 3200, True)
        self.assertEqual(len(event.messages), 1)
        nodes = event.messages[0].chain[0]
        self.assertIsInstance(nodes, plugin.Nodes)
        self.assertEqual(len(nodes.args[0]), 3)

    async def test_reveal_publishes_solution_and_cancels_timer(self):
        await self.bot.start(Event(), "N1", "grammar")
        tasks = list(self.bot.tasks)
        owner = Event(message="查看答案")
        self.assertTrue(self.filter_answer(owner))
        await self.bot.answer(owner)
        self.assertIn("正确答案", owner.messages[0].text)
        await asyncio.gather(*tasks, return_exceptions=True)
        self.assertFalse(self.bot.sessions.rounds)
        self.assertFalse(self.context.sent)

    async def test_timeout_delivery_failure_still_releases_session(self):
        async def fail(origin, chain):
            raise RuntimeError("simulated protocol failure")

        self.context.send_message = fail
        self.bot.timeout = lambda group, category: 0.01
        await self.bot.start(Event(), "N1", "grammar")
        await asyncio.gather(*list(self.bot.tasks))
        self.assertFalse(self.bot.sessions.rounds)

    async def test_unload_cancels_all_tasks_and_filter(self):
        await self.bot.start(Event(), "N1", "grammar")
        tasks = list(self.bot.tasks)
        await self.bot.terminate()
        self.assertTrue(all(task.done() for task in tasks))
        self.assertFalse(self.filter_answer(Event(message="1")))
        self.assertFalse(self.bot.sessions.rounds)
