"""article_manager 插件配置。"""

from __future__ import annotations

from typing import ClassVar

from src.app.plugin_system.base import BaseConfig, Field, SectionBase, config_section


class ArticleManagerConfig(BaseConfig):
    """文章管理与番茄发布插件配置。"""

    config_name: ClassVar[str] = "config"
    config_description: ClassVar[str] = "文章管理与番茄发布插件配置"

    @config_section("general")
    class GeneralSection(SectionBase):
        """插件通用配置。"""

        enabled: bool = Field(default=True, description="是否启用 article_manager 插件。")
        default_platform: str = Field(default="fanqie", description="默认发布平台，第一版仅支持 fanqie。")
        max_concurrent_jobs: int = Field(default=2, description="插件内部同时运行的最大任务数。")

    @config_section("generation")
    class GenerationSection(SectionBase):
        """内容生成配置。"""

        default_target_chars: int = Field(default=2200, description="默认章节目标中文字符数。")
        default_min_chars: int = Field(default=1800, description="默认章节最小中文字符数。")
        default_max_chars: int = Field(default=3200, description="默认章节最大中文字符数。")
        continuation_context_chapters: int = Field(default=3, description="续写时纳入上下文的最近章节数。")
        novel_generation_service: str = Field(
            default="novel_writer:service:novel_generation",
            description="调用的小说生成 Service 签名。",
        )

    @config_section("scheduler")
    class SchedulerSection(SectionBase):
        """定时任务配置。"""

        enabled: bool = Field(default=True, description="是否启用文章管理定时 tick。")
        tick_interval_seconds: int = Field(default=60, description="定时扫描间隔秒数。")
        max_due_jobs_per_tick: int = Field(default=3, description="每次 tick 最多处理的到期任务数。")
        retry_backoff_seconds: int = Field(default=300, description="任务失败后的默认重试间隔。")
        max_retries: int = Field(default=3, description="生成或发布任务最大自动重试次数。")

    @config_section("fanqie")
    class FanqieSection(SectionBase):
        """番茄平台配置。"""

        enabled: bool = Field(default=True, description="是否启用番茄平台适配器。")
        headless: bool = Field(default=True, description="是否以无头模式运行浏览器；默认后台运行。")
        browser_timeout_seconds: int = Field(default=60, description="番茄浏览器操作默认超时。")
        validate_login_with_browser: bool = Field(default=True, description="校验账号时是否打开作者后台确认登录态。")
        author_helper_url: str = Field(
            default="https://fanqienovel.com/author-helper",
            description="番茄作家专区入口。",
        )
        writer_zone_url: str = Field(
            default="https://fanqienovel.com/writer/zone/",
            description="番茄作者后台入口，用于登录态校验。",
        )
        session_root: str = Field(
            default="data/plugins/article_manager/sessions",
            description="Playwright 登录态保存根目录。",
        )
        artifacts_root: str = Field(
            default="data/plugins/article_manager/artifacts",
            description="番茄发布失败截图和调试产物根目录。",
        )
        auto_publish_enabled: bool = Field(default=True, description="是否允许已授权账号自动发布。")
        kill_switch: bool = Field(default=False, description="全局发布熔断开关；true 时禁止发布到番茄。")
        max_publishes_per_tick: int = Field(default=1, description="每次 tick 单账号最多发布章节数。")

    @config_section("ai_declaration")
    class AIDeclarationSection(SectionBase):
        """番茄 AI 使用声明配置。"""

        enabled: bool = Field(default=True, description="是否自动处理番茄 AI 使用声明控件。")
        declare_ai_used: bool = Field(default=True, description="自动发布时声明本章节是否使用 AI。")
        force_on_auto_publish: bool = Field(default=True, description="自动发布时强制应用上述 AI 声明配置。")

    @config_section("safety")
    class SafetySection(SectionBase):
        """安全门禁配置。"""

        allow_remote_delete: bool = Field(default=False, description="是否允许通过插件删除远端番茄章节。")
        require_confirm_for_delete: bool = Field(default=True, description="远端删除是否要求明确确认。")
        require_account_validation_before_publish: bool = Field(default=True, description="发布前是否必须校验账号登录态。")

    general: GeneralSection = Field(default_factory=GeneralSection)
    generation: GenerationSection = Field(default_factory=GenerationSection)
    scheduler: SchedulerSection = Field(default_factory=SchedulerSection)
    fanqie: FanqieSection = Field(default_factory=FanqieSection)
    ai_declaration: AIDeclarationSection = Field(default_factory=AIDeclarationSection)
    safety: SafetySection = Field(default_factory=SafetySection)
