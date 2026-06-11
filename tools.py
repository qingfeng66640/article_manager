"""article_manager 查询工具组件。"""

from __future__ import annotations

from typing import Annotated

from src.app.plugin_system.base import BaseTool

from .service import ArticleLibraryService


class ArticleStatusTool(BaseTool):
    """查询用户文章管理状态。"""

    tool_name = "article_status"
    tool_description = "查询当前用户的作品、番茄账号、章节和发布状态。"
    dependencies = ["article_manager:service:article_library"]

    async def execute(
        self,
        user_id: Annotated[str, "要查询的平台用户 ID。"],
        platform: Annotated[str, "平台名称；为空时使用当前触发消息平台。"] = "",
        query: Annotated[str, "查询类型：works/accounts/publish_records/all。"] = "all",
    ) -> tuple[bool, str | dict]:
        """执行文章状态查询。"""

        library = ArticleLibraryService(self.plugin)
        owner = library.resolve_owner(
            self._resolve_runtime_platform(platform),
            self._resolve_runtime_user_id(user_id),
        )
        query_type = query.strip().lower() or "all"
        result: dict[str, object] = {"owner_person_id": owner.owner_person_id}
        if query_type in {"works", "all"}:
            result["works"] = await library.list_works(owner.owner_person_id)
        if query_type in {"accounts", "all"}:
            result["accounts"] = await library.list_accounts(owner.owner_person_id)
        if query_type in {"publish_records", "all"}:
            result["publish_records"] = await library.list_publish_records(owner.owner_person_id)
        return True, result

    def _resolve_runtime_user_id(self, user_id: str) -> str:
        """优先使用真实触发消息发送者 ID，兜底使用模型传入 user_id。"""

        message_user_id = str(getattr(self.trigger_message, "sender_id", "") or "").strip()
        if message_user_id:
            return message_user_id
        return user_id.strip()

    def _resolve_runtime_platform(self, platform: str) -> str:
        """优先使用显式平台，其次使用当前触发消息平台。"""

        explicit_platform = platform.strip()
        if explicit_platform:
            return explicit_platform
        message_platform = str(getattr(self.trigger_message, "platform", "") or "").strip()
        return message_platform or "qq"
