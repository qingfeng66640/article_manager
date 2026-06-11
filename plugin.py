"""article_manager 插件入口。"""

from __future__ import annotations

import asyncio

from src.app.plugin_system.base import BasePlugin, register_plugin
from src.kernel.concurrency import get_task_manager
from src.kernel.logger import get_logger

from .action import ManageArticleAction
from .command import ArticleManagerCommand
from .config import ArticleManagerConfig
from .models import ArticleSchedule
from .repository import ArticleRepository
from .service import ArticleLibraryService, ArticleOrchestratorService, FanqiePlatformService
from .tools import ArticleStatusTool

logger = get_logger("article_manager")


@register_plugin
class ArticleManagerPlugin(BasePlugin):
    """文章管理与番茄发布插件。"""

    plugin_name = "article_manager"
    plugin_description = "小说的创建、管理、编写、审阅、发布。目前只支持番茄小说。"
    plugin_version = "1.0.0"

    configs = [ArticleManagerConfig]
    dependent_components: list[str] = ["novel_writer:service:novel_generation"]

    def __init__(self, config: ArticleManagerConfig | None = None) -> None:
        """初始化插件实例。"""

        super().__init__(config)
        self.repository = ArticleRepository()
        self._schedule_id: str | None = None
        self._register_task_id: str | None = None
        self._running_schedule_ids: set[str] = set()

    def get_components(self) -> list[type]:
        """返回插件组件类。"""

        cfg = self.config if isinstance(self.config, ArticleManagerConfig) else ArticleManagerConfig()
        if not cfg.general.enabled:
            return []
        return [
            ArticleLibraryService,
            ArticleOrchestratorService,
            FanqiePlatformService,
            ArticleManagerCommand,
            ManageArticleAction,
            ArticleStatusTool,
        ]

    async def on_plugin_loaded(self) -> None:
        """加载插件时初始化数据库并注册定时 tick。"""

        await self.repository.initialize()
        cfg = self.config if isinstance(self.config, ArticleManagerConfig) else ArticleManagerConfig()
        if not cfg.scheduler.enabled:
            return
        task = get_task_manager().create_task(
            self._register_schedule_when_ready(),
            name="article_manager_register_schedule",
            daemon=True,
        )
        self._register_task_id = task.task_id

    async def on_plugin_unloaded(self) -> None:
        """卸载插件时清理定时任务和数据库连接。"""

        from src.kernel.scheduler import get_unified_scheduler

        if self._schedule_id:
            try:
                await get_unified_scheduler().remove_schedule(self._schedule_id)
            except Exception as exc:
                logger.warning(f"移除 article_manager 定时任务失败: {exc}")
            self._schedule_id = None
        if self._register_task_id:
            try:
                get_task_manager().cancel_task(self._register_task_id)
            except Exception as exc:
                logger.warning(f"取消 article_manager 注册任务失败: {exc}")
            self._register_task_id = None
        self._running_schedule_ids.clear()
        await self.repository.close()

    async def _register_schedule_when_ready(self) -> None:
        """等待 scheduler 就绪后注册 recurring tick。"""

        from src.kernel.scheduler import TriggerType, get_unified_scheduler

        cfg = self.config if isinstance(self.config, ArticleManagerConfig) else ArticleManagerConfig()
        scheduler = get_unified_scheduler()
        for _attempt in range(600):
            try:
                schedule_id = await scheduler.create_schedule(
                    callback=self._tick_job,
                    trigger_type=TriggerType.TIME,
                    trigger_config={"interval_seconds": int(cfg.scheduler.tick_interval_seconds)},
                    is_recurring=True,
                    task_name="article_manager_tick",
                    force_overwrite=True,
                )
                self._schedule_id = schedule_id
                logger.info(f"article_manager 定时任务已注册: {schedule_id}")
                return
            except RuntimeError:
                await asyncio.sleep(0.5)
            except Exception as exc:
                logger.warning(f"注册 article_manager 定时任务失败: {exc}")
                await asyncio.sleep(2.0)
        logger.warning("等待 scheduler 就绪超时")

    async def _tick_job(self) -> None:
        """处理到期的文章生成/发布计划。"""

        cfg = self.config if isinstance(self.config, ArticleManagerConfig) else ArticleManagerConfig()
        schedules = await self.repository.due_schedules(cfg.scheduler.max_due_jobs_per_tick)
        if not schedules:
            return
        orchestrator = ArticleOrchestratorService(self)
        max_new_jobs = max(0, int(cfg.general.max_concurrent_jobs) - len(self._running_schedule_ids))
        for schedule in schedules:
            if max_new_jobs <= 0:
                return
            if schedule.id in self._running_schedule_ids:
                continue
            self._running_schedule_ids.add(schedule.id)
            max_new_jobs -= 1
            get_task_manager().create_task(
                self._run_schedule_job(orchestrator, schedule),
                name=f"article_manager_schedule_{schedule.id}",
                daemon=True,
            )

    async def _run_schedule_job(self, orchestrator: ArticleOrchestratorService, schedule: ArticleSchedule) -> None:
        """执行单个计划并在结束后释放运行标记。"""

        try:
            await orchestrator.run_schedule(schedule)
        except Exception as exc:
            logger.error(f"article_manager 定时任务执行失败: schedule={schedule.id}, error={exc}", exc_info=True)
        finally:
            self._running_schedule_ids.discard(schedule.id)
