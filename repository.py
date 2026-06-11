"""article_manager 持久化仓储。"""

from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select, update

from src.app.plugin_system.api.storage_api import PluginDatabase

from .models import (
    MODELS,
    ArticleAccount,
    ArticleChapter,
    ArticleSchedule,
    ArticleWork,
    PublishRecord,
)


def now_ts() -> float:
    """返回当前 Unix 时间戳。"""

    return time.time()


def new_id(prefix: str) -> str:
    """生成短的业务 ID。"""

    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def content_hash(text: str) -> str:
    """计算正文内容哈希。"""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ArticleRepository:
    """article_manager 的 SQLite 仓储封装。"""

    def __init__(self, db_path: str = "data/plugins/article_manager/article_manager.db") -> None:
        """创建仓储。"""

        self.db = PluginDatabase(db_path, MODELS)
        self._initialized = False

    async def initialize(self) -> None:
        """初始化数据库。"""

        if not self._initialized:
            await self.db.initialize()
            self._initialized = True

    async def close(self) -> None:
        """关闭数据库连接。"""

        await self.db.close()
        self._initialized = False

    async def upsert_account(
        self,
        *,
        owner_person_id: str,
        platform: str,
        label: str,
        state_path: str,
        auto_publish_enabled: bool,
    ) -> ArticleAccount:
        """新增或更新用户平台账号。"""

        await self.initialize()
        ts = now_ts()
        async with self.db.session() as session:
            existing = await session.scalar(
                select(ArticleAccount).where(
                    ArticleAccount.owner_person_id == owner_person_id,
                    ArticleAccount.platform == platform,
                    ArticleAccount.label == label,
                )
            )
            if existing is not None:
                existing.state_path = state_path
                existing.auto_publish_enabled = int(auto_publish_enabled)
                existing.updated_at = ts
                await session.flush()
                return self._row_copy(existing)
            account = ArticleAccount(
                id=new_id("acct"),
                owner_person_id=owner_person_id,
                platform=platform,
                label=label,
                state_path=state_path,
                status="unknown",
                auto_publish_enabled=int(auto_publish_enabled),
                created_at=ts,
                updated_at=ts,
            )
            session.add(account)
            await session.flush()
            return self._row_copy(account)

    async def update_account_status(
        self,
        *,
        owner_person_id: str,
        account_id: str,
        status: str,
    ) -> bool:
        """更新账号状态。"""

        await self.initialize()
        async with self.db.session() as session:
            result = await session.execute(
                update(ArticleAccount)
                .where(
                    ArticleAccount.owner_person_id == owner_person_id,
                    ArticleAccount.id == account_id,
                )
                .values(status=status, last_validated_at=now_ts(), updated_at=now_ts())
            )
            return result.rowcount > 0

    async def get_account(
        self,
        owner_person_id: str,
        account_id: str,
    ) -> ArticleAccount | None:
        """按用户隔离获取账号。"""

        await self.initialize()
        async with self.db.session() as session:
            account = await session.scalar(
                select(ArticleAccount).where(
                    ArticleAccount.owner_person_id == owner_person_id,
                    or_(ArticleAccount.id == account_id, ArticleAccount.label == account_id),
                )
            )
            return self._row_copy(account) if account is not None else None

    async def list_accounts(self, owner_person_id: str) -> list[dict[str, Any]]:
        """列出用户账号。"""

        await self.initialize()
        async with self.db.session() as session:
            rows = await session.scalars(
                select(ArticleAccount).where(ArticleAccount.owner_person_id == owner_person_id)
            )
            return [self._row_dict(row) for row in rows]

    async def create_work(
        self,
        *,
        owner_person_id: str,
        title: str,
        synopsis: str = "",
        style_prompt: str = "",
        worldbuilding: str = "",
        platform: str = "fanqie",
        remote_book_id: str = "",
    ) -> ArticleWork:
        """创建受管理作品。"""

        await self.initialize()
        ts = now_ts()
        work = ArticleWork(
            id=new_id("work"),
            owner_person_id=owner_person_id,
            title=title.strip(),
            synopsis=synopsis.strip(),
            style_prompt=style_prompt.strip(),
            worldbuilding=worldbuilding.strip(),
            platform=platform,
            remote_book_id=remote_book_id.strip(),
            status="active",
            created_at=ts,
            updated_at=ts,
        )
        return await self.db.crud(ArticleWork).create(self._row_dict(work))

    async def get_work(self, owner_person_id: str, work_id: str) -> ArticleWork | None:
        """按用户隔离获取作品。"""

        await self.initialize()
        async with self.db.session() as session:
            work = await session.scalar(
                select(ArticleWork).where(
                    ArticleWork.owner_person_id == owner_person_id,
                    ArticleWork.id == work_id,
                )
            )
            return self._row_copy(work) if work is not None else None

    async def find_work_by_title(
        self,
        owner_person_id: str,
        title: str,
    ) -> ArticleWork | None:
        """按标题查找用户作品。"""

        await self.initialize()
        async with self.db.session() as session:
            work = await session.scalar(
                select(ArticleWork).where(
                    ArticleWork.owner_person_id == owner_person_id,
                    ArticleWork.title == title.strip(),
                )
            )
            return self._row_copy(work) if work is not None else None

    async def list_works(self, owner_person_id: str) -> list[dict[str, Any]]:
        """列出用户作品。"""

        await self.initialize()
        async with self.db.session() as session:
            rows = await session.scalars(
                select(ArticleWork).where(ArticleWork.owner_person_id == owner_person_id)
            )
            return [self._row_dict(row) for row in rows]

    async def update_work_remote_book_id(
        self,
        *,
        owner_person_id: str,
        work_id: str,
        remote_book_id: str,
    ) -> bool:
        """更新作品绑定的远端番茄作品 ID。"""

        await self.initialize()
        async with self.db.session() as session:
            result = await session.execute(
                update(ArticleWork)
                .where(
                    ArticleWork.owner_person_id == owner_person_id,
                    ArticleWork.id == work_id,
                )
                .values(remote_book_id=remote_book_id.strip(), updated_at=now_ts())
            )
            return result.rowcount > 0

    async def next_chapter_index(self, owner_person_id: str, work_id: str) -> int:
        """返回作品下一章序号。"""

        chapters = await self.list_chapters(owner_person_id, work_id)
        if not chapters:
            return 1
        return max(int(item["chapter_index"]) for item in chapters) + 1

    async def add_chapter(
        self,
        *,
        owner_person_id: str,
        work_id: str,
        title: str,
        body: str,
        chapter_index: int,
        generation_prompt: str = "",
        status: str = "draft",
    ) -> ArticleChapter:
        """新增章节草稿。"""

        await self.initialize()
        ts = now_ts()
        chapter = ArticleChapter(
            id=new_id("chap"),
            owner_person_id=owner_person_id,
            work_id=work_id,
            chapter_index=chapter_index,
            title=title.strip() or f"第{chapter_index}章",
            body=body,
            content_hash=content_hash(body),
            generation_prompt=generation_prompt,
            status=status,
            created_at=ts,
            updated_at=ts,
        )
        return await self.db.crud(ArticleChapter).create(self._row_dict(chapter))

    async def update_chapter_status(
        self,
        *,
        owner_person_id: str,
        chapter_id: str,
        status: str,
    ) -> bool:
        """更新章节状态。"""

        await self.initialize()
        async with self.db.session() as session:
            result = await session.execute(
                update(ArticleChapter)
                .where(
                    ArticleChapter.owner_person_id == owner_person_id,
                    ArticleChapter.id == chapter_id,
                )
                .values(status=status, updated_at=now_ts())
            )
            return result.rowcount > 0

    async def update_chapter_title(
        self,
        *,
        owner_person_id: str,
        chapter_id: str,
        title: str,
    ) -> bool:
        """更新章节标题。"""

        await self.initialize()
        async with self.db.session() as session:
            result = await session.execute(
                update(ArticleChapter)
                .where(
                    ArticleChapter.owner_person_id == owner_person_id,
                    ArticleChapter.id == chapter_id,
                )
                .values(title=title.strip(), updated_at=now_ts())
            )
            return result.rowcount > 0

    async def get_chapter(
        self,
        owner_person_id: str,
        chapter_id: str,
    ) -> ArticleChapter | None:
        """按用户隔离获取章节。"""

        await self.initialize()
        async with self.db.session() as session:
            chapter = await session.scalar(
                select(ArticleChapter).where(
                    ArticleChapter.owner_person_id == owner_person_id,
                    ArticleChapter.id == chapter_id,
                )
            )
            return self._row_copy(chapter) if chapter is not None else None

    async def list_chapters(
        self,
        owner_person_id: str,
        work_id: str,
    ) -> list[dict[str, Any]]:
        """列出作品章节。"""

        await self.initialize()
        async with self.db.session() as session:
            rows = await session.scalars(
                select(ArticleChapter).where(
                    ArticleChapter.owner_person_id == owner_person_id,
                    ArticleChapter.work_id == work_id,
                )
            )
            return sorted([self._row_dict(row) for row in rows], key=lambda item: int(item["chapter_index"]))

    async def create_schedule(
        self,
        *,
        owner_person_id: str,
        work_id: str,
        account_id: str,
        instruction: str,
        auto_publish: bool,
        interval_seconds: int,
        next_run_at: float,
    ) -> ArticleSchedule:
        """创建作品定时计划。"""

        await self.initialize()
        ts = now_ts()
        schedule = ArticleSchedule(
            id=new_id("sched"),
            owner_person_id=owner_person_id,
            work_id=work_id,
            account_id=account_id,
            instruction=instruction,
            auto_publish=int(auto_publish),
            interval_seconds=interval_seconds,
            next_run_at=next_run_at,
            status="scheduled",
            retry_count=0,
            last_error="",
            created_at=ts,
            updated_at=ts,
        )
        return await self.db.crud(ArticleSchedule).create(self._row_dict(schedule))

    async def due_schedules(self, limit: int) -> list[ArticleSchedule]:
        """返回到期计划。"""

        await self.initialize()
        async with self.db.session() as session:
            result = await session.scalars(
                select(ArticleSchedule)
                .where(
                    ArticleSchedule.status == "scheduled",
                    ArticleSchedule.next_run_at <= now_ts(),
                )
                .order_by(ArticleSchedule.next_run_at)
                .limit(limit)
            )
            return list(result)

    async def complete_schedule_run(
        self,
        schedule: ArticleSchedule,
        *,
        ok: bool,
        error: str = "",
        retry_backoff_seconds: int = 300,
        max_retries: int = 3,
    ) -> None:
        """更新计划下一次运行时间或错误状态。"""

        await self.initialize()
        ts = now_ts()
        values = {
            "updated_at": ts,
            "last_error": "" if ok else error,
        }
        if ok:
            values.update({
                "next_run_at": ts + int(schedule.interval_seconds),
                "retry_count": 0,
                "status": "scheduled",
            })
        else:
            retry_count = int(schedule.retry_count) + 1
            if retry_count >= max(1, int(max_retries)):
                values.update({
                    "retry_count": retry_count,
                    "status": "failed",
                })
            else:
                values.update({
                    "retry_count": retry_count,
                    "status": "scheduled",
                    "next_run_at": ts + max(60, int(retry_backoff_seconds)),
                })
        async with self.db.session() as session:
            await session.execute(
                update(ArticleSchedule)
                .where(ArticleSchedule.id == schedule.id)
                .values(**values)
            )

    async def create_publish_record(
        self,
        *,
        owner_person_id: str,
        chapter: ArticleChapter,
        account_id: str,
        platform: str,
        status: str,
        declared_ai_used: bool,
        platform_item_id: str = "",
        platform_url: str = "",
        error_message: str = "",
    ) -> PublishRecord:
        """写入或更新平台发布记录。"""

        await self.initialize()
        ts = now_ts()
        async with self.db.session() as session:
            existing = await session.scalar(
                select(PublishRecord).where(
                    PublishRecord.owner_person_id == owner_person_id,
                    PublishRecord.chapter_id == chapter.id,
                    PublishRecord.account_id == account_id,
                    PublishRecord.content_hash == chapter.content_hash,
                )
            )
            if existing is not None:
                existing.platform = platform
                existing.platform_item_id = platform_item_id
                existing.platform_url = platform_url
                existing.status = status
                existing.declared_ai_used = int(declared_ai_used)
                existing.error_message = error_message
                existing.updated_at = ts
                await session.flush()
                return self._row_copy(existing)

            record = PublishRecord(
                id=new_id("pub"),
                owner_person_id=owner_person_id,
                chapter_id=chapter.id,
                work_id=chapter.work_id,
                account_id=account_id,
                platform=platform,
                content_hash=chapter.content_hash,
                platform_item_id=platform_item_id,
                platform_url=platform_url,
                status=status,
                declared_ai_used=int(declared_ai_used),
                error_message=error_message,
                created_at=ts,
                updated_at=ts,
            )
            session.add(record)
            await session.flush()
            return self._row_copy(record)

    async def existing_publish_record(
        self,
        *,
        owner_person_id: str,
        chapter_id: str,
        account_id: str,
        content_hash_value: str,
    ) -> PublishRecord | None:
        """查找同一内容的既有发布记录。"""

        await self.initialize()
        async with self.db.session() as session:
            record = await session.scalar(
                select(PublishRecord).where(
                    PublishRecord.owner_person_id == owner_person_id,
                    PublishRecord.chapter_id == chapter_id,
                    PublishRecord.account_id == account_id,
                    PublishRecord.content_hash == content_hash_value,
                )
            )
            return self._row_copy(record) if record is not None else None

    async def list_publish_records(self, owner_person_id: str) -> list[dict[str, Any]]:
        """列出用户发布记录。"""

        await self.initialize()
        async with self.db.session() as session:
            rows = await session.scalars(
                select(PublishRecord).where(PublishRecord.owner_person_id == owner_person_id)
            )
            return [self._row_dict(row) for row in rows]

    @staticmethod
    def ensure_parent(path: str) -> None:
        """确保文件父目录存在。"""

        Path(path).parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _row_dict(row: Any) -> dict[str, Any]:
        """将 SQLAlchemy 行对象转为字典。"""

        return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    @staticmethod
    def _row_copy(row: Any) -> Any:
        """复制 SQLAlchemy 行对象，避免返回 session 绑定实例。"""

        return type(row)(**ArticleRepository._row_dict(row))
