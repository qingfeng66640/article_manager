"""article_manager 插件内部数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class OwnerContext:
    """用户隔离上下文。"""

    owner_person_id: str
    platform: str
    user_id: str


@dataclass(slots=True)
class JobResult:
    """生成或发布编排结果。"""

    ok: bool
    message: str
    work_id: str = ""
    chapter_id: str = ""
    publish_record_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FanqiePublishPayload:
    """发送给番茄适配器的发布载荷。"""

    work_title: str
    chapter_title: str
    chapter_body: str
    chapter_index: int
    remote_book_id: str = ""
    declare_ai_used: bool = True
    content_hash: str = ""


@dataclass(slots=True)
class FanqieCreateWorkPayload:
    """发送给番茄适配器的作品创建载荷。"""

    work_title: str
    synopsis: str = ""
    remote_book_id: str = ""


@dataclass(slots=True)
class FanqieResult:
    """番茄平台操作结果。"""

    ok: bool
    status: str
    message: str
    remote_id: str = ""
    remote_url: str = ""
    needs_user_action: bool = False
    details: dict[str, Any] = field(default_factory=dict)
