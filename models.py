"""article_manager SQLite 数据模型。"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """article_manager 模型基类。"""


class ArticleAccount(Base):
    """用户隔离的平台账号绑定。"""

    __tablename__ = "article_accounts"
    __table_args__ = (UniqueConstraint("owner_person_id", "platform", "label"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_person_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    state_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    auto_publish_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_validated_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class ArticleWork(Base):
    """受管理的文章或小说作品。"""
    __tablename__ = "article_works"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_person_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    synopsis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    style_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    worldbuilding: Mapped[str] = mapped_column(Text, nullable=False, default="")
    platform: Mapped[str] = mapped_column(Text, nullable=False, default="fanqie")
    remote_book_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


class ArticleChapter(Base):
    """作品章节草稿与内容版本。"""
    __tablename__ = "article_chapters"
    __table_args__ = (UniqueConstraint("work_id", "chapter_index"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_person_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    work_id: Mapped[str] = mapped_column(Text, ForeignKey("article_works.id"), nullable=False, index=True)
    chapter_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    generation_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


class ArticleSchedule(Base):
    """作品定时生成或发布计划。"""
    __tablename__ = "article_schedules"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_person_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    work_id: Mapped[str] = mapped_column(Text, ForeignKey("article_works.id"), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instruction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    auto_publish: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=86400)
    next_run_at: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="scheduled")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


class ArticleJob(Base):
    """一次生成或发布任务运行记录。"""
    __tablename__ = "article_jobs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_person_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    schedule_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    work_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    chapter_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    error_code: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


class PublishRecord(Base):
    """平台发布结果账本。"""
    __tablename__ = "article_publish_records"
    __table_args__ = (UniqueConstraint("account_id", "chapter_id", "content_hash"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_person_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    chapter_id: Mapped[str] = mapped_column(Text, ForeignKey("article_chapters.id"), nullable=False, index=True)
    work_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(Text, nullable=False, default="fanqie")
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    platform_item_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    platform_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    declared_ai_used: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


MODELS = [
    ArticleAccount,
    ArticleWork,
    ArticleChapter,
    ArticleSchedule,
    ArticleJob,
    PublishRecord,
]
