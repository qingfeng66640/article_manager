"""article_manager 核心服务。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from plugins.novel_writer.schemas import NovelGenerationRequest

from src.app.plugin_system.api import permission_api, service_api
from src.app.plugin_system.base import BaseService
from src.kernel.logger import get_logger

from .config import ArticleManagerConfig
from .models import ArticleAccount, ArticleChapter, ArticleSchedule, ArticleWork
from .platforms.fanqie import FanqiePlatformAdapter
from .repository import ArticleRepository, now_ts
from .schemas import FanqieCreateWorkPayload, FanqiePublishPayload, JobResult, OwnerContext
from .session_store import FanqieSessionStore

logger = get_logger("article_manager.service")


class ArticleLibraryService(BaseService):
    """文章内容、账号和发布账本服务。"""

    service_name = "article_library"
    service_description = "按用户隔离管理文章作品、章节、番茄账号、排期和发布记录。"
    version = "1.0.0"

    def _config(self) -> ArticleManagerConfig:
        """返回插件配置。"""

        cfg = getattr(self.plugin, "config", None)
        return cfg if isinstance(cfg, ArticleManagerConfig) else ArticleManagerConfig()

    def _repo(self) -> ArticleRepository:
        """返回插件共享仓储。"""

        return self.plugin.repository

    def resolve_owner(self, platform: str, user_id: str) -> OwnerContext:
        """把平台用户 ID 解析为隔离 owner_person_id。"""

        owner = permission_api.generate_person_id(platform, user_id)
        return OwnerContext(owner_person_id=owner, platform=platform, user_id=user_id)

    async def bind_fanqie_account(
        self,
        *,
        owner_person_id: str,
        label: str,
        state_file: str,
        auto_publish_enabled: bool = True,
    ) -> dict[str, Any]:
        """绑定用户的番茄账号登录态。"""

        account_id = label.strip() or "default"
        session_store = FanqieSessionStore(self._config().fanqie.session_root)
        target = session_store.import_state_file(
            owner_person_id=owner_person_id,
            account_id=account_id,
            source_path=state_file,
        )
        account = await self._repo().upsert_account(
            owner_person_id=owner_person_id,
            platform="fanqie",
            label=account_id,
            state_path=str(target),
            auto_publish_enabled=auto_publish_enabled,
        )
        return ArticleRepository._row_dict(account)

    async def list_accounts(self, owner_person_id: str) -> list[dict[str, Any]]:
        """列出用户绑定的平台账号。"""

        return await self._repo().list_accounts(owner_person_id)

    async def create_work(
        self,
        *,
        owner_person_id: str,
        title: str,
        synopsis: str = "",
        style_prompt: str = "",
        worldbuilding: str = "",
        remote_book_id: str = "",
    ) -> dict[str, Any]:
        """创建文章或小说作品。"""

        if not title.strip():
            raise ValueError("作品标题不能为空")
        work = await self._repo().create_work(
            owner_person_id=owner_person_id,
            title=title,
            synopsis=synopsis,
            style_prompt=style_prompt,
            worldbuilding=worldbuilding,
            platform="fanqie",
            remote_book_id=remote_book_id,
        )
        return ArticleRepository._row_dict(work)

    async def list_works(self, owner_person_id: str) -> list[dict[str, Any]]:
        """列出用户作品。"""

        return await self._repo().list_works(owner_person_id)

    async def link_remote_book(
        self,
        *,
        owner_person_id: str,
        work_id: str,
        remote_book_id: str,
    ) -> bool:
        """绑定本地作品到番茄远端作品 ID。"""

        work = await self._repo().get_work(owner_person_id, work_id)
        if work is None:
            return False
        return await self._repo().update_work_remote_book_id(
            owner_person_id=owner_person_id,
            work_id=work_id,
            remote_book_id=remote_book_id,
        )

    async def create_remote_fanqie_work(
        self,
        *,
        owner_person_id: str,
        work_id: str,
        account_id: str,
    ) -> JobResult:
        """在番茄创建远端作品并绑定到本地作品。"""

        work = await self._repo().get_work(owner_person_id, work_id)
        if work is None:
            return JobResult(ok=False, message="作品不存在或不属于当前用户。", work_id=work_id)
        result = await FanqiePlatformService(self.plugin).create_work(
            owner_person_id=owner_person_id,
            work=work,
            account_id=account_id,
        )
        if not result.ok:
            return JobResult(ok=False, message=result.message, work_id=work_id, details=asdict(result))
        remote_book_id = str(result.details.get("remote_id") or result.details.get("remote_url") or work.title)
        linked = await self.link_remote_book(
            owner_person_id=owner_person_id,
            work_id=work_id,
            remote_book_id=remote_book_id,
        )
        if not linked:
            return JobResult(ok=False, message="番茄作品已创建，但本地绑定失败。", work_id=work_id, details=asdict(result))
        return JobResult(
            ok=True,
            message=f"已创建番茄作品并绑定：{work.title} -> {remote_book_id}",
            work_id=work_id,
            details=asdict(result),
        )

    async def get_work_detail(
        self,
        *,
        owner_person_id: str,
        work_id: str,
    ) -> dict[str, Any] | None:
        """获取作品详情。"""

        work = await self._repo().get_work(owner_person_id, work_id)
        if work is None:
            return None
        return {
            "work": ArticleRepository._row_dict(work),
            "chapters": await self._repo().list_chapters(owner_person_id, work_id),
            "publish_records": await self._repo().list_publish_records(owner_person_id),
        }

    async def preview_work(
        self,
        *,
        owner_person_id: str,
        work_id: str,
    ) -> JobResult:
        """读取作品章节用于本地预览。"""

        detail = await self.get_work_detail(owner_person_id=owner_person_id, work_id=work_id)
        if detail is None:
            return JobResult(ok=False, message="作品不存在或不属于当前用户。", work_id=work_id)
        chapters = detail.get("chapters") or []
        if not chapters:
            return JobResult(ok=False, message="该作品还没有章节。", work_id=work_id)
        return JobResult(
            ok=True,
            message="作品预览数据已读取。",
            work_id=work_id,
            details=detail,
        )

    async def list_publish_records(self, owner_person_id: str) -> list[dict[str, Any]]:
        """列出用户发布记录。"""

        return await self._repo().list_publish_records(owner_person_id)

    async def create_schedule(
        self,
        *,
        owner_person_id: str,
        work_id: str,
        account_id: str,
        instruction: str,
        auto_publish: bool,
        interval_seconds: int,
        first_run_delay_seconds: int,
    ) -> dict[str, Any]:
        """创建定时续写计划。"""

        work = await self._repo().get_work(owner_person_id, work_id)
        if work is None:
            raise ValueError("作品不存在或不属于当前用户")
        schedule = await self._repo().create_schedule(
            owner_person_id=owner_person_id,
            work_id=work_id,
            account_id=account_id,
            instruction=instruction,
            auto_publish=auto_publish,
            interval_seconds=max(60, interval_seconds),
            next_run_at=now_ts() + max(1, first_run_delay_seconds),
        )
        return ArticleRepository._row_dict(schedule)


class FanqiePlatformService(BaseService):
    """番茄平台账号和发布服务。"""

    service_name = "fanqie_platform"
    service_description = "番茄小说平台登录态校验、发布、删除与查看。"
    version = "1.0.0"

    def _config(self) -> ArticleManagerConfig:
        cfg = getattr(self.plugin, "config", None)
        return cfg if isinstance(cfg, ArticleManagerConfig) else ArticleManagerConfig()

    def _adapter(self) -> FanqiePlatformAdapter:
        return FanqiePlatformAdapter(self._config())

    async def validate_account(
        self,
        *,
        owner_person_id: str,
        account_id: str,
    ) -> dict[str, Any]:
        """校验用户番茄账号登录态。"""

        account = await self.plugin.repository.get_account(owner_person_id, account_id)
        if account is None:
            return {"ok": False, "status": "missing", "message": "番茄账号不存在或不属于当前用户。"}
        result = await self._adapter().validate_account(account)
        await self.plugin.repository.update_account_status(
            owner_person_id=owner_person_id,
            account_id=account.id,
            status=result.status,
        )
        return asdict(result)

    async def create_work(
        self,
        *,
        owner_person_id: str,
        work: ArticleWork,
        account_id: str,
    ) -> JobResult:
        """在番茄作者后台创建作品。"""

        config = self._config()
        if config.fanqie.kill_switch:
            return JobResult(ok=False, message="番茄发布熔断开关已开启。", work_id=work.id)
        if not config.fanqie.enabled:
            return JobResult(ok=False, message="番茄适配器未启用。", work_id=work.id)
        account = await self._resolve_account(owner_person_id, account_id)
        if account is None:
            return JobResult(ok=False, message=await self._missing_account_message(owner_person_id, account_id), work_id=work.id)
        payload = FanqieCreateWorkPayload(
            work_title=work.title,
            synopsis=work.synopsis,
            remote_book_id=work.remote_book_id,
        )
        result = await self._adapter().create_work(account, payload)
        return JobResult(ok=result.ok, message=result.message, work_id=work.id, details=asdict(result))

    async def get_work_status(
        self,
        *,
        owner_person_id: str,
        work: ArticleWork,
        account_id: str,
    ) -> JobResult:
        """查询番茄线上作品和章节状态。"""

        config = self._config()
        if config.fanqie.kill_switch:
            return JobResult(ok=False, message="番茄发布熔断开关已开启。", work_id=work.id)
        if not config.fanqie.enabled:
            return JobResult(ok=False, message="番茄适配器未启用。", work_id=work.id)
        if not work.remote_book_id.strip():
            return JobResult(
                ok=False,
                message="该作品尚未绑定番茄作品 ID。请先使用 /小说 remote-create 或 /小说 link 绑定。",
                work_id=work.id,
            )
        account = await self._resolve_account(owner_person_id, account_id)
        if account is None:
            return JobResult(ok=False, message=await self._missing_account_message(owner_person_id, account_id), work_id=work.id)
        result = await self._adapter().get_work_status(account, work.remote_book_id, work.title)
        return JobResult(ok=result.ok, message=result.message, work_id=work.id, details=asdict(result))

    async def publish_chapter(
        self,
        *,
        owner_person_id: str,
        chapter: ArticleChapter,
        work: ArticleWork,
        account: ArticleAccount,
    ) -> JobResult:
        """发布章节到番茄并写入发布记录。"""

        config = self._config()
        if not config.fanqie.auto_publish_enabled or not account.auto_publish_enabled:
            return JobResult(ok=False, message="番茄自动发布未启用。", chapter_id=chapter.id)
        existing = await self.plugin.repository.existing_publish_record(
            owner_person_id=owner_person_id,
            chapter_id=chapter.id,
            account_id=account.id,
            content_hash_value=chapter.content_hash,
        )
        if existing is not None and existing.status == "published":
            return JobResult(
                ok=True,
                message="相同内容已发布，跳过重复发布。",
                chapter_id=chapter.id,
                publish_record_id=existing.id,
            )
        payload = FanqiePublishPayload(
            work_title=work.title,
            chapter_title=chapter.title,
            chapter_body=chapter.body,
            chapter_index=chapter.chapter_index,
            remote_book_id=work.remote_book_id,
            declare_ai_used=bool(config.ai_declaration.declare_ai_used),
            content_hash=chapter.content_hash,
        )
        result = await self._adapter().publish_chapter(account, payload)
        status = "published" if result.ok else result.status
        record = await self.plugin.repository.create_publish_record(
            owner_person_id=owner_person_id,
            chapter=chapter,
            account_id=account.id,
            platform="fanqie",
            status=status,
            declared_ai_used=bool(config.ai_declaration.declare_ai_used),
            platform_item_id=result.remote_id,
            platform_url=result.remote_url,
            error_message="" if result.ok else result.message,
        )
        await self.plugin.repository.update_chapter_status(
            owner_person_id=owner_person_id,
            chapter_id=chapter.id,
            status="published" if result.ok else "publish_failed",
        )
        return JobResult(
            ok=result.ok,
            message=result.message,
            work_id=work.id,
            chapter_id=chapter.id,
            publish_record_id=record.id,
            details=asdict(result),
        )
    async def _resolve_account(self, owner_person_id: str, account_id: str) -> ArticleAccount | None:
        """解析番茄账号，默认账号不存在时允许唯一账号兜底。"""

        account = await self.plugin.repository.get_account(owner_person_id, account_id)
        if account is not None or account_id != "default":
            return account
        accounts = await self.plugin.repository.list_accounts(owner_person_id)
        if len(accounts) != 1:
            return None
        fallback_id = str(accounts[0].get("id") or accounts[0].get("label") or "")
        if not fallback_id:
            return None
        return await self.plugin.repository.get_account(owner_person_id, fallback_id)

    async def _missing_account_message(self, owner_person_id: str, account_id: str) -> str:
        """生成账号缺失提示。"""

        accounts = await self.plugin.repository.list_accounts(owner_person_id)
        if not accounts:
            return "番茄账号不存在或不属于当前用户。请先使用 /小说 bind <账号标签> <storage_state路径> [auto] 绑定。"
        labels = ", ".join(str(account.get("label") or account.get("id")) for account in accounts)
        if account_id == "default":
            return f"未找到默认番茄账号 default。当前账号有：{labels}。请指定账号标签。"
        return f"番茄账号 {account_id} 不存在或不属于当前用户。当前账号有：{labels}。"


class ArticleOrchestratorService(BaseService):
    """文章生成、续写、保存与发布编排服务。"""

    service_name = "article_orchestrator"
    service_description = "编排小说生成、续写、保存草稿、定时运行和番茄发布。"
    version = "1.0.0"
    dependencies = ["novel_writer:service:novel_generation"]

    def _config(self) -> ArticleManagerConfig:
        cfg = getattr(self.plugin, "config", None)
        return cfg if isinstance(cfg, ArticleManagerConfig) else ArticleManagerConfig()

    def _repo(self) -> ArticleRepository:
        return self.plugin.repository

    async def generate_chapter(
        self,
        *,
        owner_person_id: str,
        work_id: str,
        instruction: str,
        chapter_title: str = "",
        auto_publish: bool = False,
        account_id: str = "",
    ) -> JobResult:
        """为作品生成下一章，可选自动发布。"""

        work = await self._repo().get_work(owner_person_id, work_id)
        if work is None:
            return JobResult(ok=False, message="作品不存在或不属于当前用户。", work_id=work_id)
        generation_service = service_api.get_service(self._config().generation.novel_generation_service)
        if generation_service is None:
            return JobResult(ok=False, message="novel_writer 生成服务不可用。", work_id=work_id)
        chapter_index = await self._repo().next_chapter_index(owner_person_id, work_id)
        context = await self._build_project_context(owner_person_id, work)
        cfg = self._config()
        user_request = instruction.strip() or "请承接最新章节继续写下一章。"
        generation = await generation_service.generate_chapter(
            NovelGenerationRequest(
                user_request=user_request,
                mode="chapter",
                project_context=context,
                continuation_context=await self._build_continuation_context(owner_person_id, work_id),
                chapter_number=chapter_index,
                chapter_title=chapter_title,
                target_chars=cfg.generation.default_target_chars,
                min_chars=cfg.generation.default_min_chars,
                max_chars=cfg.generation.default_max_chars,
                system_requirements=self._build_system_requirements(),
                quality_requirements=self._build_quality_requirements(),
                request_name="article_manager.generate_chapter",
            )
        )
        if not generation.ok:
            return JobResult(ok=False, message=self._format_generation_error(generation), work_id=work_id)
        title = self._normalize_chapter_title(chapter_title or generation.title or f"第{chapter_index}章", work, chapter_index)
        chapter = await self._repo().add_chapter(
            owner_person_id=owner_person_id,
            work_id=work_id,
            title=title,
            body=generation.body,
            chapter_index=chapter_index,
            generation_prompt=instruction,
            status="draft",
        )
        if not auto_publish:
            return JobResult(ok=True, message="章节已生成并保存为草稿。", work_id=work_id, chapter_id=chapter.id)
        return await self.publish_chapter(
            owner_person_id=owner_person_id,
            chapter_id=chapter.id,
            account_id=account_id,
        )

    async def continue_work(
        self,
        *,
        owner_person_id: str,
        work_id: str,
        instruction: str = "",
        auto_publish: bool = False,
        account_id: str = "",
    ) -> JobResult:
        """续写作品下一章。"""

        return await self.generate_chapter(
            owner_person_id=owner_person_id,
            work_id=work_id,
            instruction=instruction or "请承接最新章节继续写下一章。",
            auto_publish=auto_publish,
            account_id=account_id,
        )

    async def publish_chapter(
        self,
        *,
        owner_person_id: str,
        chapter_id: str,
        account_id: str,
    ) -> JobResult:
        """发布指定章节到番茄。"""

        chapter = await self._repo().get_chapter(owner_person_id, chapter_id)
        if chapter is None:
            return JobResult(ok=False, message="章节不存在或不属于当前用户。", chapter_id=chapter_id)
        work = await self._repo().get_work(owner_person_id, chapter.work_id)
        if work is None:
            return JobResult(ok=False, message="章节所属作品不存在。", chapter_id=chapter_id)
        chapter = await self._ensure_publish_chapter_title(owner_person_id, chapter, work)
        title_error = self._validate_publish_chapter(chapter)
        if title_error:
            return JobResult(ok=False, message=title_error, work_id=work.id, chapter_id=chapter.id)
        account = await self._resolve_publish_account(owner_person_id, account_id)
        if account is None:
            return JobResult(ok=False, message=await self._missing_account_message(owner_person_id, account_id), chapter_id=chapter_id)
        fanqie = FanqiePlatformService(self.plugin)
        return await fanqie.publish_chapter(
            owner_person_id=owner_person_id,
            chapter=chapter,
            work=work,
            account=account,
        )

    async def _ensure_publish_chapter_title(
        self,
        owner_person_id: str,
        chapter: ArticleChapter,
        work: ArticleWork,
    ) -> ArticleChapter:
        """发布前自动补足过短章节标题。"""

        title = self._normalize_chapter_title(chapter.title, work, chapter.chapter_index)
        if title == chapter.title:
            return chapter
        await self._repo().update_chapter_title(
            owner_person_id=owner_person_id,
            chapter_id=chapter.id,
            title=title,
        )
        chapter.title = title
        return chapter

    @staticmethod
    def _normalize_chapter_title(title: str, work: ArticleWork, chapter_index: int) -> str:
        """确保章节标题满足番茄最低长度。"""

        cleaned = title.strip() or f"第{chapter_index}章"
        if len(cleaned) >= 5:
            return cleaned
        candidate = f"{work.title} 第{chapter_index}章"
        return candidate if len(candidate) >= 5 else f"第{chapter_index}章节正文"

    @staticmethod
    def _validate_publish_chapter(chapter: ArticleChapter) -> str:
        """校验章节是否满足番茄发布质量门禁。"""

        title = chapter.title.strip()
        body = chapter.body.strip()
        if len(title) < 5:
            return f"章节名必须大于等于 5 个字，当前章节名为 {len(title)} 个字。请重新生成或修改章节标题后再发布。"
        if len(body) <= 1000:
            return f"正文必须多于 1000 字，当前正文为 {len(body)} 字。请重新生成更长正文后再发布。"
        return ""

    async def _resolve_publish_account(self, owner_person_id: str, account_id: str) -> ArticleAccount | None:
        """解析发布账号，默认账号不存在时允许唯一账号兜底。"""

        account = await self._repo().get_account(owner_person_id, account_id)
        if account is not None or account_id != "default":
            return account
        accounts = await self._repo().list_accounts(owner_person_id)
        if len(accounts) != 1:
            return None
        fallback_id = str(accounts[0].get("id") or accounts[0].get("label") or "")
        if not fallback_id:
            return None
        return await self._repo().get_account(owner_person_id, fallback_id)

    async def _missing_account_message(self, owner_person_id: str, account_id: str) -> str:
        """生成账号缺失提示。"""

        accounts = await self._repo().list_accounts(owner_person_id)
        if not accounts:
            return "番茄账号不存在或不属于当前用户。请先使用 /小说 bind <账号标签> <storage_state路径> [auto] 绑定。"
        labels = ", ".join(str(account.get("label") or account.get("id")) for account in accounts)
        if account_id == "default":
            return f"未找到默认番茄账号 default。当前账号有：{labels}。请使用 /小说 publish <章节ID|作品ID|标题> <账号标签> 指定账号。"
        return f"番茄账号 {account_id} 不存在或不属于当前用户。当前账号有：{labels}。"

    async def run_schedule(self, schedule: ArticleSchedule) -> JobResult:
        """执行一次到期计划。"""

        result = await self.continue_work(
            owner_person_id=schedule.owner_person_id,
            work_id=schedule.work_id,
            instruction=schedule.instruction,
            auto_publish=bool(schedule.auto_publish),
            account_id=schedule.account_id,
        )
        cfg = self._config()
        await self._repo().complete_schedule_run(
            schedule,
            ok=result.ok,
            error=result.message,
            retry_backoff_seconds=cfg.scheduler.retry_backoff_seconds,
            max_retries=cfg.scheduler.max_retries,
        )
        return result

    @staticmethod
    def _build_system_requirements() -> str:
        """构建章节生成场景的系统级要求。"""

        return (
            "你正在为 article_manager 生成可直接保存的小说章节正文。"
            "只输出小说正文，不要输出章节外说明、保存提示、任务执行过程、标题说明、提纲、列表、解释、"
            "创作说明、AI 自述、系统提示复述或任何非小说正文内容。"
        )

    def _build_quality_requirements(self) -> str:
        """构建章节生成质量要求。"""

        cfg = self._config().generation
        return (
            f"正文不少于 {cfg.default_min_chars} 个中文字符，目标约 {cfg.default_target_chars} 个中文字符，"
            f"最多不超过 {cfg.default_max_chars} 个中文字符。"
            "本章需要承接上一章结尾并推进内容，不要只写片段。"
            "如果字数不足，请扩写场景、动作、对话、心理描写和情节推进，"
            "不要用总结、大纲或设定说明凑字数。"
        )

    @staticmethod
    def _format_generation_error(generation: Any) -> str:
        """格式化 novel_writer 生成失败原因。"""

        message = str(getattr(generation, "error", "") or "小说生成失败")
        report = getattr(generation, "quality_report", None)
        if report is None:
            return message
        issues = ", ".join(getattr(report, "issues", []) or [])
        char_count = getattr(report, "char_count", 0)
        details = getattr(report, "issue_details", {}) or {}
        detail_text = ""
        if details:
            detail_text = "；" + "，".join(f"{key}={value}" for key, value in details.items())
        if not issues:
            return f"{message}（字符数 {char_count}{detail_text}）"
        return f"{message}（原因：{issues}；字符数 {char_count}{detail_text}）"

    async def _build_project_context(self, owner_person_id: str, work: ArticleWork) -> str:
        """构建作品设定上下文。"""

        lines = [f"作品标题：{work.title}"]
        if work.synopsis:
            lines.append(f"简介：{work.synopsis}")
        if work.style_prompt:
            lines.append(f"风格：{work.style_prompt}")
        if work.worldbuilding:
            lines.append(f"世界观：{work.worldbuilding}")
        chapters = await self._repo().list_chapters(owner_person_id, work.id)
        if chapters:
            lines.append(f"已生成章节数：{len(chapters)}")
        return "\n".join(lines)

    async def _build_continuation_context(self, owner_person_id: str, work_id: str) -> str:
        """构建最近章节续写上下文。"""

        chapters = await self._repo().list_chapters(owner_person_id, work_id)
        recent = chapters[-max(1, self._config().generation.continuation_context_chapters) :]
        parts = []
        for chapter in recent:
            body = str(chapter.get("body") or "")
            parts.append(
                f"{chapter.get('title', '')}\n{body[-1200:]}"
            )
        return "\n\n".join(parts)
