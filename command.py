"""article_manager 命令组件。"""

from __future__ import annotations

import asyncio
import shlex
from typing import Any

from src.app.plugin_system.api import send_api, service_api
from src.app.plugin_system.base import BaseCommand, cmd_route
from src.app.plugin_system.types import PermissionLevel
from src.kernel.concurrency import get_task_manager
from src.kernel.logger import get_logger

from .service import ArticleLibraryService, ArticleOrchestratorService, FanqiePlatformService
from .schemas import OwnerContext

logger = get_logger("article_manager.command")

_HELP = """\
/article 或 /小说 用法：
  /小说 help                                       — 查看帮助
  /小说 status                                     — 查询当前账号、作品、发布记录
  /小说 works                                      — 列出作品
  /小说 accounts                                   — 列出番茄账号
  /小说 records                                    — 列出发布记录
  /小说 remote-status <作品ID或标题> [账号标签]    — 查看番茄线上作品/章节状态

作品与账号：
  /小说 bind <账号标签> <storage_state路径> [auto] — 绑定番茄登录态，带 auto 才允许自动发布
  /小说 create <作品标题> [简介]                   — 创建本地作品
  /小说 remote-create <作品ID或标题> [账号标签]    — 在番茄创建作品并自动绑定本地作品
  /小说 link <作品ID或标题> <番茄作品ID>           — 手动绑定本地作品到番茄后台作品

章节：
  /小说 generate <作品ID或标题> <生成要求>         — 生成草稿
  /小说 continue <作品ID或标题> [续写要求]         — 续写草稿
  /小说 preview <作品ID或标题> [latest|all|章节ID] — 用合并转发预览数据库中的小说章节正文
  /小说 publish <章节ID|作品ID|标题> [账号标签]    — 发布已有章节；传作品时发布最新章节
  /小说 genpub <作品ID或标题> <要求> [账号标签]    — 续写并尝试发布
  /小说 schedule <作品ID或标题> <间隔秒> <首次延迟秒> <auto|draft> <账号标签> <续写要求>

别名：/文章、/article；preview 也可用「预览」「查看正文」。
提示：路径或标题包含空格时请加引号。"""


class ArticleManagerCommand(BaseCommand):
    """文章/小说作品、章节和番茄账号管理命令。"""

    command_name = "article"
    command_description = "文章/小说作品、章节和番茄账号管理命令"
    permission_level = PermissionLevel.USER
    dependencies = [
        "article_manager:service:article_library",
        "article_manager:service:article_orchestrator",
    ]

    @classmethod
    def match(cls, parts: list[str]) -> int:
        """支持英文和中文命令别名。"""

        if not parts:
            return 0
        if parts[0] in {"article", "小说", "文章"}:
            return 1
        return 0

    async def execute(self, message_text: str) -> tuple[bool, str]:
        """执行文章管理命令并把结果发送回当前聊天流。"""

        stripped = message_text.strip()
        if self._is_background_command(stripped):
            await self._start_background_command(stripped)
            return True, "文章任务已开始执行，完成后会发送结果。"
        result = await self._execute_command(message_text)
        await self._reply(result[1])
        return result

    async def _execute_command(self, message_text: str) -> tuple[bool, str]:
        """执行文章管理命令，保留 Windows 路径反斜杠。"""

        stripped = message_text.strip()
        if stripped.startswith(self.command_prefix):
            return False, "命令文本格式错误：只接受去掉前缀后的子路由文本"
        if not stripped:
            return True, _HELP
        try:
            parts = [self._clean_arg(part) for part in shlex.split(stripped, posix=False)]
        except ValueError as exc:
            return False, f"参数解析错误: {exc}"
        if not parts:
            return True, _HELP
        if parts[0] in {self.command_name, "小说", "文章"}:
            return False, "命令文本格式错误：只接受去掉 command_name 后的子路由文本"
        command = parts[0].lower()
        args = parts[1:]
        if command in {"help", "帮助"}:
            return await self.handle_help()
        if command in {"status", "状态"}:
            return await self.handle_status()
        if command in {"works", "作品"}:
            return await self.handle_works()
        if command in {"accounts", "账号"}:
            return await self.handle_accounts()
        if command in {"records", "发布记录"}:
            return await self.handle_records()
        if command in {"create", "新建", "创建"}:
            return await self._handle_create(args)
        if command in {"bind", "绑定"}:
            return await self._handle_bind(args)
        if command in {"link", "绑定作品", "关联作品"}:
            return await self._handle_link(args)
        if command in {"remote-create", "远端创建", "创建番茄作品"}:
            return await self._handle_remote_create(args)
        if command in {"remote-status", "线上状态", "番茄状态"}:
            return await self._handle_remote_status(args)
        if command in {"preview", "预览", "查看正文"}:
            return await self._handle_preview(args)
        if command in {"generate", "生成"}:
            return await self._handle_generate(args, auto_publish=False)
        if command in {"continue", "续写"}:
            return await self._handle_continue(args, auto_publish=False)
        if command in {"genpub", "生成发布", "续写发布"}:
            return await self._handle_continue(args, auto_publish=True)
        if command in {"publish", "发布"}:
            return await self._handle_publish(args)
        if command in {"schedule", "定时"}:
            return await self._handle_schedule(args)
        return False, f"未知命令：{parts[0]}\n输入 /小说 help 查看用法"

    @cmd_route("help")
    async def handle_help(self) -> tuple[bool, str]:
        """显示帮助。"""

        return True, _HELP

    @cmd_route("status")
    async def handle_status(self) -> tuple[bool, str]:
        """查询当前文章管理状态。"""

        owner = self._owner()
        library = ArticleLibraryService(self.plugin)
        works = await library.list_works(owner.owner_person_id)
        accounts = await library.list_accounts(owner.owner_person_id)
        records = await library.list_publish_records(owner.owner_person_id)
        return True, (
            f"article_manager 当前状态：\n"
            f"  用户：{owner.platform}:{owner.user_id}\n"
            f"  作品：{len(works)} 个\n"
            f"  番茄账号：{len(accounts)} 个\n"
            f"  发布记录：{len(records)} 条"
        )

    @cmd_route("works")
    async def handle_works(self) -> tuple[bool, str]:
        """列出当前用户作品。"""

        owner = self._owner()
        works = await ArticleLibraryService(self.plugin).list_works(owner.owner_person_id)
        if not works:
            return True, "当前没有作品。使用 /小说 create <作品标题> [简介] 创建。"
        lines = ["作品列表："]
        for work in works:
            lines.append(f"  {work.get('id')} — {work.get('title')}（{work.get('status', 'unknown')}）")
        return True, "\n".join(lines)

    @cmd_route("accounts")
    async def handle_accounts(self) -> tuple[bool, str]:
        """列出当前用户番茄账号。"""

        owner = self._owner()
        accounts = await ArticleLibraryService(self.plugin).list_accounts(owner.owner_person_id)
        if not accounts:
            return True, "当前没有绑定番茄账号。使用 /小说 bind <标签> <storage_state路径> [auto] 绑定。"
        lines = ["番茄账号："]
        for account in accounts:
            auto = "auto" if account.get("auto_publish_enabled") else "manual"
            lines.append(f"  {account.get('id')} / {account.get('label')} — {account.get('status')} / {auto}")
        return True, "\n".join(lines)

    @cmd_route("records")
    async def handle_records(self) -> tuple[bool, str]:
        """列出当前用户发布记录。"""

        owner = self._owner()
        records = await ArticleLibraryService(self.plugin).list_publish_records(owner.owner_person_id)
        if not records:
            return True, "当前没有发布记录。"
        lines = ["发布记录："]
        for record in records[-10:]:
            lines.append(
                f"  {record.get('id')} — {record.get('chapter_id')} / {record.get('account_id')} / {record.get('status')}"
            )
        return True, "\n".join(lines)

    async def _handle_create(self, args: list[str]) -> tuple[bool, str]:
        if not args:
            return False, "用法：/小说 create <作品标题> [简介]"
        owner = self._owner()
        work = await ArticleLibraryService(self.plugin).create_work(
            owner_person_id=owner.owner_person_id,
            title=args[0],
            synopsis=" ".join(args[1:]),
        )
        return True, f"已创建作品：{work['title']}（{work['id']}）"

    async def _handle_link(self, args: list[str]) -> tuple[bool, str]:
        if len(args) < 2:
            return False, "用法：/小说 link <作品ID或标题> <番茄作品ID>"
        owner = self._owner()
        work_id = await self._resolve_work_id(owner.owner_person_id, args[0])
        if not work_id:
            return False, "未找到该作品。请先用 /小说 works 查看作品。"
        ok = await ArticleLibraryService(self.plugin).link_remote_book(
            owner_person_id=owner.owner_person_id,
            work_id=work_id,
            remote_book_id=args[1],
        )
        if not ok:
            return False, "绑定失败：作品不存在或不属于当前用户。"
        return True, f"已绑定作品 {work_id} 到番茄作品 ID：{args[1]}"

    async def _handle_bind(self, args: list[str]) -> tuple[bool, str]:
        if len(args) < 2:
            return False, "用法：/小说 bind <账号标签> <storage_state路径> [auto]"
        owner = self._owner()
        auto_publish = len(args) >= 3 and args[2].lower() in {"auto", "true", "yes", "允许自动发布"}
        account = await ArticleLibraryService(self.plugin).bind_fanqie_account(
            owner_person_id=owner.owner_person_id,
            label=args[0],
            state_file=args[1],
            auto_publish_enabled=auto_publish,
        )
        status = "已允许自动发布" if account.get("auto_publish_enabled") else "未启用自动发布"
        return True, f"已绑定番茄账号：{account['label']}（{status}）"

    async def _handle_remote_create(self, args: list[str]) -> tuple[bool, str]:
        if not args:
            return False, "用法：/小说 remote-create <作品ID或标题> [账号标签]"
        owner = self._owner()
        work_id = await self._resolve_work_id(owner.owner_person_id, args[0])
        if not work_id:
            return False, "未找到该作品。请先用 /小说 works 查看作品，或 /小说 create <标题> 创建。"
        account_id = args[1] if len(args) >= 2 else "default"
        result = await ArticleLibraryService(self.plugin).create_remote_fanqie_work(
            owner_person_id=owner.owner_person_id,
            work_id=work_id,
            account_id=account_id,
        )
        return result.ok, self._format_job_result(result)

    async def _handle_remote_status(self, args: list[str]) -> tuple[bool, str]:
        if not args:
            return False, "用法：/小说 remote-status <作品ID或标题> [账号标签]"
        owner = self._owner()
        work_id = await self._resolve_work_id(owner.owner_person_id, args[0])
        if not work_id:
            return False, "未找到该作品。请先用 /小说 works 查看作品，或 /小说 create <标题> 创建。"
        detail = await ArticleLibraryService(self.plugin).get_work_detail(
            owner_person_id=owner.owner_person_id,
            work_id=work_id,
        )
        if detail is None:
            return False, "作品不存在或不属于当前用户。"
        work = await self.plugin.repository.get_work(owner.owner_person_id, work_id)
        if work is None:
            return False, "作品不存在或不属于当前用户。"
        account_id = args[1] if len(args) >= 2 else "default"
        result = await FanqiePlatformService(self.plugin).get_work_status(
            owner_person_id=owner.owner_person_id,
            work=work,
            account_id=account_id,
        )
        if not result.ok:
            return False, self._format_job_result(result)
        return True, self._format_remote_status_result(detail.get("work") or {}, result)

    async def _handle_preview(self, args: list[str]) -> tuple[bool, str]:
        if not args:
            return False, "用法：/小说 preview <作品ID或标题> [章节ID|latest|all]"
        owner = self._owner()
        work_id = await self._resolve_work_id(owner.owner_person_id, args[0])
        if not work_id:
            return False, "未找到该作品。请先用 /小说 works 查看作品，或 /小说 create <标题> 创建。"
        result = await ArticleLibraryService(self.plugin).preview_work(
            owner_person_id=owner.owner_person_id,
            work_id=work_id,
        )
        if not result.ok:
            return False, self._format_job_result(result)
        work = result.details.get("work") or {}
        chapters = self._select_preview_chapters(result.details.get("chapters") or [], args[1] if len(args) >= 2 else "latest")
        if not chapters:
            return False, "未找到可预览章节。范围可传 latest、all 或 chapter_id。"
        nodes = self._build_preview_nodes(work, chapters)
        service = service_api.get_service("forward_msg:service:forward_msg_protocol")
        if service is None or not hasattr(service, "send_forward_message"):
            return False, "forward_msg 服务不可用，无法发送小说预览。"
        forward_result = await service.send_forward_message(nodes, self.stream_id)
        ok, message = forward_result if isinstance(forward_result, tuple) else (False, "forward_msg 返回值异常")
        if not ok:
            return False, str(message)
        return True, f"小说预览已发送：{work.get('title', work_id)}（{len(chapters)} 章）"

    async def _handle_generate(self, args: list[str], *, auto_publish: bool) -> tuple[bool, str]:
        if len(args) < 2:
            return False, "用法：/小说 generate <作品ID或标题> <生成要求>"
        owner = self._owner()
        work_id = await self._resolve_work_id(owner.owner_person_id, args[0])
        if not work_id:
            return False, "未找到该作品。请先用 /小说 works 查看作品，或 /小说 create <标题> 创建。"
        result = await ArticleOrchestratorService(self.plugin).generate_chapter(
            owner_person_id=owner.owner_person_id,
            work_id=work_id,
            instruction=" ".join(args[1:]),
            auto_publish=auto_publish,
            account_id="default",
        )
        return result.ok, self._format_job_result(result)

    async def _handle_continue(self, args: list[str], *, auto_publish: bool) -> tuple[bool, str]:
        if len(args) < 1:
            return False, "用法：/小说 continue <作品ID或标题> [续写要求]"
        owner = self._owner()
        work_id = await self._resolve_work_id(owner.owner_person_id, args[0])
        if not work_id:
            return False, "未找到该作品。请先用 /小说 works 查看作品，或 /小说 create <标题> 创建。"
        account_id = "default"
        instruction_args = args[1:]
        if auto_publish and len(args) >= 3:
            account_id = args[-1]
            instruction_args = args[1:-1]
        result = await ArticleOrchestratorService(self.plugin).continue_work(
            owner_person_id=owner.owner_person_id,
            work_id=work_id,
            instruction=" ".join(instruction_args),
            auto_publish=auto_publish,
            account_id=account_id,
        )
        return result.ok, self._format_job_result(result)

    async def _handle_publish(self, args: list[str]) -> tuple[bool, str]:
        if not args:
            return False, "用法：/小说 publish <章节ID|作品ID|作品标题> [账号标签]"
        owner = self._owner()
        account_id = args[1] if len(args) >= 2 else "default"
        orchestrator = ArticleOrchestratorService(self.plugin)
        result = await orchestrator.publish_chapter(
            owner_person_id=owner.owner_person_id,
            chapter_id=args[0],
            account_id=account_id,
        )
        if result.ok or result.message != "章节不存在或不属于当前用户。":
            return result.ok, self._format_job_result(result)
        chapter_id = await self._resolve_latest_chapter_id(owner.owner_person_id, args[0])
        if not chapter_id:
            work_id = await self._resolve_work_id(owner.owner_person_id, args[0])
            if work_id:
                return False, "作品已找到，但还没有可发布章节。请先用 /小说 continue <作品ID或标题> <续写要求> 生成章节。"
            return False, "未找到章节或作品。发布已有章节请传 chapter_id；发布作品最新章节请传作品标题或 work_id。"
        result = await orchestrator.publish_chapter(
            owner_person_id=owner.owner_person_id,
            chapter_id=chapter_id,
            account_id=account_id,
        )
        return result.ok, self._format_job_result(result)

    async def _handle_schedule(self, args: list[str]) -> tuple[bool, str]:
        if len(args) < 6:
            return False, "用法：/小说 schedule <作品ID或标题> <间隔秒> <首次延迟秒> <auto|draft> <账号标签> <续写要求>"
        owner = self._owner()
        work_id = await self._resolve_work_id(owner.owner_person_id, args[0])
        if not work_id:
            return False, "未找到该作品。请先用 /小说 works 查看作品，或 /小说 create <标题> 创建。"
        schedule = await ArticleLibraryService(self.plugin).create_schedule(
            owner_person_id=owner.owner_person_id,
            work_id=work_id,
            account_id=args[4],
            instruction=" ".join(args[5:]),
            auto_publish=args[3].lower() == "auto",
            interval_seconds=int(args[1]),
            first_run_delay_seconds=int(args[2]),
        )
        return True, f"已创建定时续写计划：{schedule['id']}"

    async def _reply(self, text: str) -> None:
        """发送命令执行结果。"""

        if text:
            await send_api.send_text(text, stream_id=self.stream_id)

    def _is_background_command(self, stripped: str) -> bool:
        """判断是否为需要后台执行的长耗时命令。"""

        try:
            parts = [self._clean_arg(part) for part in shlex.split(stripped, posix=False)]
        except ValueError:
            return False
        return bool(parts) and parts[0].lower() in {
            "remote-create",
            "远端创建",
            "创建番茄作品",
            "remote-status",
            "线上状态",
            "番茄状态",
            "generate",
            "生成",
            "continue",
            "续写",
            "genpub",
            "生成发布",
            "续写发布",
            "publish",
            "发布",
        }

    async def _start_background_command(self, stripped: str) -> None:
        """启动长耗时命令并立即返回。"""

        await self._reply("文章任务已开始执行，完成后会发送结果。生成、发布或重试可能需要数分钟。")
        get_task_manager().create_task(
            self._run_background_command(stripped),
            name="article_manager_command_job",
            daemon=True,
        )

    async def _run_background_command(self, stripped: str) -> None:
        """后台执行长耗时命令并发送结果。"""

        notifier = get_task_manager().create_task(
            self._notify_background_running(),
            name="article_manager_command_progress",
            daemon=True,
        )
        try:
            result = await self._execute_command(stripped)
        except asyncio.CancelledError:
            await self._reply("文章任务已取消：Bot 正在关闭、插件被卸载，或后台任务被系统中断。")
            raise
        except Exception as exc:
            logger.error(f"article_manager 命令后台任务异常: {exc}", exc_info=True)
            await self._reply(f"文章任务执行异常：{exc}")
        else:
            await self._reply(result[1] or "文章任务已结束，但没有返回详细结果。")
        finally:
            get_task_manager().cancel_task(notifier.task_id)

    async def _notify_background_running(self) -> None:
        """长任务未结束时发送进度提示。"""

        await asyncio.sleep(60)
        await self._reply("文章任务仍在生成、发布或重试中，请继续等待最终结果。")

    def _owner(self) -> OwnerContext:
        library = ArticleLibraryService(self.plugin)
        user_id = self._resolve_runtime_user_id()
        if not user_id:
            raise ValueError("无法识别触发用户 ID")
        return library.resolve_owner(self._resolve_runtime_platform(), user_id)

    def _resolve_runtime_platform(self) -> str:
        platform = str(getattr(self._message, "platform", "") or "").strip()
        return platform or "qq"

    def _resolve_runtime_user_id(self) -> str:
        return str(getattr(self._message, "sender_id", "") or "").strip()

    async def _resolve_work_id(self, owner_person_id: str, work_ref: str) -> str:
        library = ArticleLibraryService(self.plugin)
        detail = await library.get_work_detail(owner_person_id=owner_person_id, work_id=work_ref)
        if detail is not None:
            return work_ref
        for work in await library.list_works(owner_person_id):
            if str(work.get("title")) == work_ref:
                return str(work.get("id"))
        return ""

    async def _resolve_latest_chapter_id(self, owner_person_id: str, work_ref: str) -> str:
        """按作品 ID 或标题获取最新章节 ID。"""

        work_id = await self._resolve_work_id(owner_person_id, work_ref)
        if not work_id:
            return ""
        detail = await ArticleLibraryService(self.plugin).get_work_detail(
            owner_person_id=owner_person_id,
            work_id=work_id,
        )
        if detail is None:
            return ""
        chapters = detail.get("chapters") or []
        if not chapters:
            return ""
        latest = max(chapters, key=lambda item: int(item.get("chapter_index") or 0))
        return str(latest.get("id") or "")

    def _select_preview_chapters(self, chapters: list[dict[str, Any]], scope: str) -> list[dict[str, Any]]:
        """按范围选择需要预览的章节。"""

        if not chapters:
            return []
        normalized = scope.strip().lower() or "latest"
        if normalized == "all":
            return chapters
        if normalized in {"latest", "最新"}:
            return [max(chapters, key=lambda item: int(item.get("chapter_index") or 0))]
        for chapter in chapters:
            if str(chapter.get("id") or "") == scope:
                return [chapter]
        return []

    def _build_preview_nodes(self, work: dict[str, Any], chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """构建小说预览合并转发节点。"""

        title = str(work.get("title") or "未命名作品")
        synopsis = str(work.get("synopsis") or "").strip()
        summary = f"作品：{title}\n章节数：{len(chapters)}"
        if synopsis:
            summary += f"\n简介：{synopsis}"
        texts = [summary]
        for chapter in chapters:
            chapter_title = str(chapter.get("title") or f"第{chapter.get('chapter_index', '?')}章")
            body = str(chapter.get("body") or "")
            header = f"{chapter_title}\n章节ID：{chapter.get('id', '')}\n\n"
            texts.extend(self._split_preview_text(f"{header}{body}", 1800))
        user_id = self._resolve_bot_user_id()
        nickname = self._resolve_bot_nickname()
        return [
            {
                "type": "node",
                "data": {
                    "user_id": user_id,
                    "nickname": nickname,
                    "message_seq": 0,
                    "content": [{"type": "text", "data": {"text": text}}],
                },
            }
            for text in texts
        ]

    @staticmethod
    def _split_preview_text(text: str, max_chars: int) -> list[str]:
        """按长度拆分预览正文，优先按自然段切分。"""

        stripped = text.strip()
        if not stripped:
            return []
        chunks: list[str] = []
        current = ""
        for paragraph in stripped.split("\n\n"):
            piece = paragraph.strip()
            if not piece:
                continue
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
                current = ""
            while len(piece) > max_chars:
                chunks.append(piece[:max_chars])
                piece = piece[max_chars:]
            current = piece
        if current:
            chunks.append(current)
        return chunks

    def _resolve_bot_user_id(self) -> str:
        """解析合并转发节点展示用户 ID。"""

        for attr in ("self_id", "bot_id"):
            value = str(getattr(self._message, attr, "") or "").strip()
            if value:
                return value
        return "0"

    def _resolve_bot_nickname(self) -> str:
        """解析合并转发节点展示昵称。"""

        nickname = str(getattr(self, "bot_nickname", "") or "").strip()
        return nickname or "小说预览"

    @staticmethod
    def _format_remote_status_result(work: dict[str, Any], result: Any) -> str:
        """格式化番茄线上状态查询结果。"""

        data = result.details.get("details") or {}
        chapters = data.get("chapters") or []
        lines = [
            "番茄线上状态：",
            f"  本地作品：{work.get('title', result.work_id)}",
            f"  番茄作品ID：{data.get('remote_book_id') or result.details.get('remote_id', '')}",
            f"  远端标题：{data.get('title', '')}",
            f"  后台地址：{data.get('remote_url') or result.details.get('remote_url', '')}",
            f"  识别章节：{data.get('chapter_count', len(chapters))} 条",
        ]
        for chapter in chapters[:8]:
            lines.append(f"  - {chapter.get('title', '')}：{chapter.get('status') or '未显示'}")
        if len(chapters) > 8:
            lines.append(f"  ... 另有 {len(chapters) - 8} 条章节记录")
        return "\n".join(lines)

    @staticmethod
    def _format_job_result(result: Any) -> str:
        refs = []
        if getattr(result, "work_id", ""):
            refs.append(f"作品 {result.work_id}")
        if getattr(result, "chapter_id", ""):
            refs.append(f"章节 {result.chapter_id}")
        if getattr(result, "publish_record_id", ""):
            refs.append(f"发布记录 {result.publish_record_id}")
        suffix = f"（{'，'.join(refs)}）" if refs else ""
        prefix = "完成" if result.ok else "失败"
        return f"文章任务{prefix}{suffix}：{result.message}"

    @staticmethod
    def _clean_arg(value: str) -> str:
        return value.strip().strip('"').strip("'").strip("“").strip("”")
