"""发布平台适配器协议。"""

from __future__ import annotations

from typing import Protocol

from ..models import ArticleAccount
from ..schemas import FanqiePublishPayload, FanqieResult


class PublishPlatformAdapter(Protocol):
    """发布平台适配器协议。"""

    async def validate_account(self, account: ArticleAccount) -> FanqieResult:
        """校验平台账号登录态。"""

    async def publish_chapter(
        self,
        account: ArticleAccount,
        payload: FanqiePublishPayload,
    ) -> FanqieResult:
        """发布章节。"""

    async def delete_item(self, account: ArticleAccount, platform_item_id: str) -> FanqieResult:
        """删除或下架平台条目。"""

    async def view_item(self, account: ArticleAccount, platform_item_id: str) -> FanqieResult:
        """查看平台条目。"""
