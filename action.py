"""article_manager 自然语言动作组件。"""

from __future__ import annotations

from typing import Annotated

from src.app.plugin_system.base import BaseAction
from src.kernel.concurrency import get_task_manager
from src.kernel.logger import get_logger

from .service import ArticleLibraryService, ArticleOrchestratorService
from .schemas import JobResult

logger = get_logger("article_manager.action")


class ManageArticleAction(BaseAction):
    """通过自然语言管理文章、章节、定时任务和番茄发布。"""

    _PUBLISH_MARKERS = (
        "上传",
        "发布",
        "推上去",
        "发到番茄",
        "番茄发布",
        "番茄上传",
        "上架",
        "投递",
        "投稿",
        "发出去",
        "同步到平台",
        "同步到番茄",
        "小说平台",
        "作者后台",
        "publish",
        "upload",
    )
    _DRAFT_ONLY_MARKERS = (
        "不上传",
        "不要上传",
        "无需上传",
        "先别上传",
        "不发布",
        "不要发布",
        "先不发布",
        "暂不发布",
        "只生成",
        "只写",
        "仅生成",
        "保存草稿",
        "草稿",
        "draft",
    )

    action_name = "manage_article"
    action_description = (
        "小说/文章章节管理与小说平台对接工具。用户提到创建作品、管理作品、查询作品列表、"
        "生成章节、续写下一章、保存草稿、定时续写、章节发布、上传到番茄/小说平台、"
        "绑定番茄账号或导入 Playwright 登录态时必须优先使用本动作。"
        "不要因为用户没有直接提供 chapter_id 就拒绝触发；生成/续写/定时发布可通过 work_id 或 work_title 定位作品，"
        "只有单独发布已有章节时才需要 chapter_id。第一版平台仅支持 fanqie。"
    )
    associated_types = ["text"]
    primary_action = False
    dependencies = [
        "article_manager:service:article_library",
        "article_manager:service:article_orchestrator",
    ]

    async def execute(
        self,
        intent: Annotated[
            str,
            (
                "操作意图，必须选以下之一：create_work（新建作品/小说项目）、generate（生成某作品新章节）、"
                "continue（续写下一章）、publish（发布已有章节到番茄，需要 chapter_id）、"
                "bind_account（绑定番茄账号登录态）、schedule（创建定时续写/定时发布计划）、list（查询作品/账号/发布概况）。"
                "当用户说章节管理、小说管理、作品管理、小说平台发布工具、发到番茄、上传小说平台时，应选择最接近的意图，"
                "不要返回无对应工具。"
            ),
        ],
        user_id: Annotated[str, "触发操作的平台用户 ID，用于账号、作品、章节和发布记录的用户隔离。"],
        platform: Annotated[str, "触发用户所在平台名称；为空时使用当前聊天流平台，不确定时留空。"] = "",
        work_id: Annotated[str, "作品 ID；生成、续写、定时任务时优先使用。没有 ID 但用户给了作品名时填 work_title。"] = "",
        work_title: Annotated[str, "作品标题/小说名；创建作品时必填，按标题查找作品、生成下一章、续写或定时时也可使用。"] = "",
        instruction: Annotated[
            str,
            (
                "用户对作品、章节生成、续写、排期或发布的自然语言要求。"
                "例如章节剧情、风格、字数、是否接续上一章、是否发到番茄/小说平台。"
            ),
        ] = "",
        chapter_id: Annotated[str, "要发布的已有章节 ID；只有 intent=publish 且发布数据库里已有章节时才必填。生成后发布不需要填写。"] = "",
        account_id: Annotated[str, "番茄账号 ID 或绑定标签；未指定时使用 default。"] = "default",
        state_file: Annotated[str, "用户手动登录后导出的 Playwright storage_state 文件路径；仅 bind_account 需要。"] = "",
        auto_publish: Annotated[bool, "用户明确要求生成/续写/定时完成后上传、发布、发到番茄或同步小说平台时设为 true。"] = False,
        interval_seconds: Annotated[int, "定时续写间隔秒数；仅 schedule 使用，未指定时默认一天。"] = 86400,
        first_run_delay_seconds: Annotated[int, "首次运行延迟秒数；仅 schedule 使用。"] = 60,
        reason: Annotated[str, "模型选择该动作的简短原因；请保留用户是否要求发布、上传、发到番茄、仅草稿等关键信号。"] = "",
    ) -> tuple[bool, str]:
        """执行文章管理动作。"""

        library = ArticleLibraryService(self.plugin)
        resolved_platform = self._resolve_runtime_platform(platform)
        resolved_user_id = self._resolve_runtime_user_id(user_id)
        owner = library.resolve_owner(resolved_platform, resolved_user_id)
        normalized_intent = self._normalize_intent(intent, instruction, reason)
        publish_without_chapter = (
            normalized_intent == "publish"
            and not chapter_id.strip()
            and (work_id.strip() or work_title.strip())
        )
        if publish_without_chapter:
            normalized_intent = self._normalize_publish_without_chapter(instruction, reason)

        try:
            if normalized_intent == "bind_account":
                if not state_file.strip():
                    return await self._finish(False, "绑定番茄账号需要提供 state_file。")
                account = await library.bind_fanqie_account(
                    owner_person_id=owner.owner_person_id,
                    label=account_id or "default",
                    state_file=state_file,
                    auto_publish_enabled=bool(auto_publish),
                )
                status = "已允许自动发布" if account.get("auto_publish_enabled") else "未启用自动发布"
                return await self._finish(True, f"已绑定番茄账号：{account['label']}（{status}）")

            if normalized_intent == "create_work":
                work = await library.create_work(
                    owner_person_id=owner.owner_person_id,
                    title=work_title or instruction,
                    synopsis=instruction,
                )
                return await self._finish(True, f"已创建作品：{work['title']}（{work['id']}）")

            if normalized_intent in {"generate", "continue"}:
                target_work_id = await self._resolve_work_id(library, owner.owner_person_id, work_id, work_title)
                if not target_work_id:
                    return await self._finish(False, "请提供有效作品 ID 或作品标题。")
                effective_auto_publish = publish_without_chapter or self._should_auto_publish(
                    auto_publish=auto_publish,
                    instruction=instruction,
                    reason=reason,
                )
                task = get_task_manager().create_task(
                    self._run_generation_job(
                        owner_person_id=owner.owner_person_id,
                        work_id=target_work_id,
                        instruction=instruction,
                        auto_publish=effective_auto_publish,
                        account_id=account_id,
                    ),
                    name=f"article_manager_{normalized_intent}_{target_work_id}",
                    daemon=True,
                )
                mode = "生成并尝试发布" if effective_auto_publish else "生成草稿"
                message = f"已开始{mode}任务：{target_work_id}。完成后会在当前聊天里通知。"
                await self._send_status(message)
                logger.info(
                    f"已创建文章后台任务: task={task.task_id}, intent={normalized_intent}, "
                    f"work={target_work_id}, auto_publish={effective_auto_publish}"
                )
                return True, message

            if normalized_intent == "publish":
                if not chapter_id.strip():
                    return await self._finish(False, "发布需要提供 chapter_id。")
                orchestrator = ArticleOrchestratorService(self.plugin)
                result = await orchestrator.publish_chapter(
                    owner_person_id=owner.owner_person_id,
                    chapter_id=chapter_id,
                    account_id=account_id,
                )
                return await self._finish(result.ok, result.message)

            if normalized_intent == "schedule":
                target_work_id = await self._resolve_work_id(library, owner.owner_person_id, work_id, work_title)
                if not target_work_id:
                    return await self._finish(False, "请提供有效作品 ID 或作品标题。")
                schedule = await library.create_schedule(
                    owner_person_id=owner.owner_person_id,
                    work_id=target_work_id,
                    account_id=account_id,
                    instruction=instruction,
                    auto_publish=auto_publish,
                    interval_seconds=interval_seconds,
                    first_run_delay_seconds=first_run_delay_seconds,
                )
                return await self._finish(True, f"已创建定时续写计划：{schedule['id']}")

            if normalized_intent == "list":
                works = await library.list_works(owner.owner_person_id)
                return await self._finish(True, f"你当前有 {len(works)} 个作品。")
        except Exception as exc:
            return await self._finish(False, f"文章管理操作失败：{exc}")
        return await self._finish(False, f"未知 article_manager 意图：{intent}")

    async def _run_generation_job(
        self,
        *,
        owner_person_id: str,
        work_id: str,
        instruction: str,
        auto_publish: bool,
        account_id: str,
    ) -> None:
        """在后台执行耗时章节生成，并把最终结果发送回当前聊天流。"""

        try:
            orchestrator = ArticleOrchestratorService(self.plugin)
            result = await orchestrator.continue_work(
                owner_person_id=owner_person_id,
                work_id=work_id,
                instruction=instruction,
                auto_publish=auto_publish,
                account_id=account_id,
            )
        except Exception as exc:
            logger.error(f"文章后台生成任务失败: work={work_id}, error={exc}", exc_info=True)
            await self._send_status(f"文章任务失败：{exc}")
            return

        await self._send_status(self._format_job_result(result))

    async def _finish(self, ok: bool, message: str) -> tuple[bool, str]:
        """返回 action 结果前尽量把结果主动发回聊天流。"""

        await self._send_status(message)
        return ok, message

    async def _send_status(self, message: str) -> bool:
        """在具备聊天流上下文时发送状态消息。"""

        if not message or not self._can_send_status():
            return False
        return await self._send_to_stream(message)

    def _can_send_status(self) -> bool:
        """判断当前 Action 实例是否具备发送状态消息所需的上下文。"""

        return bool(
            getattr(self.chat_stream, "stream_id", "")
            and getattr(self.chat_stream, "platform", "")
            and getattr(self.chat_stream, "chat_type", "")
            and getattr(self.chat_stream, "context", None) is not None
        )

    @classmethod
    def _normalize_intent(cls, intent: str, instruction: str, reason: str) -> str:
        """把模型可能给出的中文意图归一为内部意图。"""

        raw = intent.strip().lower()
        if raw in {"create_work", "generate", "continue", "publish", "bind_account", "schedule", "list"}:
            return raw
        text = f"{raw}\n{instruction}\n{reason}".lower()
        if any(marker in text for marker in ("绑定", "账号", "登录态", "storage_state", "state_file", "cookie")):
            return "bind_account"
        if any(marker in text for marker in ("定时", "排期", "每天", "每隔", "周期", "自动续写")):
            return "schedule"
        if any(marker in text for marker in ("新建", "创建", "开一本", "新作品", "小说项目", "作品项目")):
            return "create_work"
        if any(marker in text for marker in ("续写", "下一章", "接着写", "继续写")):
            return "continue"
        if any(marker in text for marker in ("生成", "写一章", "写章节", "章节管理", "小说管理")):
            return "generate"
        if any(marker in text for marker in ("查询", "列表", "有哪些", "管理工具", "管理面板", "状态", "概况")):
            return "list"
        if any(marker in text for marker in cls._PUBLISH_MARKERS):
            return "publish"
        return raw

    @staticmethod
    def _normalize_publish_without_chapter(instruction: str, reason: str) -> str:
        """没有 chapter_id 的发布请求按生成/续写后发布处理。"""

        text = f"{instruction}\n{reason}".lower()
        if any(marker in text for marker in ("续写", "下一章", "接着写", "继续写")):
            return "continue"
        return "generate"

    def _resolve_runtime_user_id(self, user_id: str) -> str:
        """优先使用真实触发消息发送者 ID，兜底使用模型传入 user_id。"""

        context = getattr(self.chat_stream, "context", None)
        candidates = [
            getattr(context, "triggering_user_id", "") if context is not None else "",
            getattr(getattr(context, "current_message", None), "sender_id", "") if context is not None else "",
        ]
        if context is not None:
            candidates.extend(
                str(getattr(message, "sender_id", "") or "")
                for message in reversed(getattr(context, "unread_messages", []) or [])
            )
            candidates.extend(
                str(getattr(message, "sender_id", "") or "")
                for message in reversed(getattr(context, "history_messages", []) or [])
            )
        for candidate in candidates:
            resolved = str(candidate or "").strip()
            if resolved:
                return resolved
        return user_id.strip()

    def _resolve_runtime_platform(self, platform: str) -> str:
        """优先使用显式平台，其次使用当前聊天流平台。"""

        explicit_platform = platform.strip()
        if explicit_platform:
            return explicit_platform
        stream_platform = str(getattr(self.chat_stream, "platform", "") or "").strip()
        return stream_platform or "qq"

    def _format_job_result(self, result: JobResult) -> str:
        """格式化后台生成/发布任务结果。"""

        prefix = "文章任务完成" if result.ok else "文章任务失败"
        refs = []
        if result.work_id:
            refs.append(f"作品 {result.work_id}")
        if result.chapter_id:
            refs.append(f"章节 {result.chapter_id}")
        if result.publish_record_id:
            refs.append(f"发布记录 {result.publish_record_id}")
        suffix = f"（{'，'.join(refs)}）" if refs else ""
        return f"{prefix}{suffix}：{result.message}"

    @classmethod
    def _should_auto_publish(cls, *, auto_publish: bool, instruction: str, reason: str) -> bool:
        """根据显式参数和自然语言上下文判断生成后是否尝试发布。"""

        if auto_publish:
            return True
        text = f"{instruction}\n{reason}".lower()
        if any(marker.lower() in text for marker in cls._DRAFT_ONLY_MARKERS):
            return False
        return any(marker.lower() in text for marker in cls._PUBLISH_MARKERS)

    @staticmethod
    async def _resolve_work_id(
        library: ArticleLibraryService,
        owner_person_id: str,
        work_id: str,
        work_title: str,
    ) -> str:
        """根据作品 ID 或标题解析作品 ID。"""

        if work_id.strip():
            return work_id.strip()
        for work in await library.list_works(owner_person_id):
            if str(work.get("title")) == work_title.strip():
                return str(work.get("id"))
        return ""
