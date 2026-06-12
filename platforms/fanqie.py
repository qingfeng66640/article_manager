"""番茄小说平台适配器。"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from ..config import ArticleManagerConfig
from ..models import ArticleAccount
from ..schemas import FanqieCreateWorkPayload, FanqiePublishPayload, FanqieResult


class FanqiePlatformAdapter:
    """隔离番茄 Playwright 自动化的适配器。"""

    _LOGIN_URL_MARKERS = ("login", "passport", "sso", "authorize")
    _LOGIN_TEXT_MARKERS = ("登录", "扫码", "验证码", "手机号", "注册")
    _DASHBOARD_TEXT_MARKERS = ("作品管理", "工作台", "发布作品", "新建作品", "草稿箱", "章节管理")
    _BOOK_MANAGE_URL = "https://fanqienovel.com/main/writer/book-manage"
    _EDITOR_SELECTORS = (".ql-editor", ".ProseMirror", '[contenteditable="true"]')
    _GUIDE_BUTTON_TEXTS = ("我知道了", "跳过", "完成", "下一步")

    def __init__(self, config: ArticleManagerConfig) -> None:
        """创建番茄适配器。"""

        self.config = config

    async def validate_account(self, account: ArticleAccount) -> FanqieResult:
        """校验账号本地登录态是否存在并可进入作者后台。"""

        if not Path(account.state_path).exists():
            return FanqieResult(
                ok=False,
                status="auth_required",
                message="番茄登录态不存在，请先手动登录并绑定账号。",
                needs_user_action=True,
            )
        if not self.config.fanqie.validate_login_with_browser:
            return FanqieResult(ok=True, status="valid", message="番茄登录态文件存在。")
        return await self._validate_browser_session(account)

    async def create_work(
        self,
        account: ArticleAccount,
        payload: FanqieCreateWorkPayload,
    ) -> FanqieResult:
        """在番茄作者后台创建作品。"""

        if self.config.fanqie.kill_switch:
            return FanqieResult(ok=False, status="blocked", message="番茄发布熔断开关已开启。")
        if not self.config.fanqie.enabled:
            return FanqieResult(ok=False, status="disabled", message="番茄适配器未启用。")
        auth = await self.validate_account(account)
        if not auth.ok:
            return auth
        try:
            async_playwright = self._load_async_playwright()
        except ModuleNotFoundError:
            return FanqieResult(
                ok=False,
                status="dependency_missing",
                message="未安装 playwright；请安装依赖后再启用真实番茄作品创建。",
                needs_user_action=True,
            )
        return await self._create_work_with_browser(async_playwright, account, payload)

    async def get_work_status(
        self,
        account: ArticleAccount,
        remote_book_id: str,
        work_title: str = "",
    ) -> FanqieResult:
        """查询番茄线上作品和章节状态。"""

        if self.config.fanqie.kill_switch:
            return FanqieResult(ok=False, status="blocked", message="番茄发布熔断开关已开启。")
        if not self.config.fanqie.enabled:
            return FanqieResult(ok=False, status="disabled", message="番茄适配器未启用。")
        if not remote_book_id.strip():
            return FanqieResult(ok=False, status="invalid", message="番茄作品 ID 不能为空。")
        auth = await self.validate_account(account)
        if not auth.ok:
            return auth
        try:
            async_playwright = self._load_async_playwright()
        except ModuleNotFoundError:
            return FanqieResult(
                ok=False,
                status="dependency_missing",
                message="未安装 playwright；请安装依赖后再查询番茄线上状态。",
                needs_user_action=True,
            )
        return await self._get_work_status_with_browser(async_playwright, account, remote_book_id, work_title)

    async def publish_chapter(
        self,
        account: ArticleAccount,
        payload: FanqiePublishPayload,
    ) -> FanqieResult:
        """发布章节到番茄。"""

        if self.config.fanqie.kill_switch:
            return FanqieResult(ok=False, status="blocked", message="番茄发布熔断开关已开启。")
        if not self.config.fanqie.enabled:
            return FanqieResult(ok=False, status="disabled", message="番茄适配器未启用。")
        auth = await self.validate_account(account)
        if not auth.ok:
            return auth
        try:
            async_playwright = self._load_async_playwright()
        except ModuleNotFoundError:
            return FanqieResult(
                ok=False,
                status="dependency_missing",
                message="未安装 playwright；请安装依赖后再启用真实番茄发布。",
                needs_user_action=True,
            )
        return await self._publish_with_browser(async_playwright, account, payload)


    async def delete_item(self, account: ArticleAccount, platform_item_id: str) -> FanqieResult:
        """删除或下架番茄条目。"""

        if not platform_item_id.strip():
            return FanqieResult(ok=False, status="invalid", message="platform_item_id 不能为空。")
        auth = await self.validate_account(account)
        if not auth.ok:
            return auth
        return FanqieResult(ok=False, status="unsupported", message="第一版暂不自动删除番茄远端章节。")

    async def view_item(self, account: ArticleAccount, platform_item_id: str) -> FanqieResult:
        """查看番茄条目。"""

        if not platform_item_id.strip():
            return FanqieResult(ok=False, status="invalid", message="platform_item_id 不能为空。")
        auth = await self.validate_account(account)
        if not auth.ok:
            return auth
        return FanqieResult(ok=True, status="unknown", message="番茄远端状态查询待接入真实浏览器流程。")

    async def _create_work_with_browser(
        self,
        async_playwright: Callable[..., Any],
        account: ArticleAccount,
        payload: FanqieCreateWorkPayload,
    ) -> FanqieResult:
        """使用浏览器自动化创建番茄作品。"""

        timeout_ms = max(1, int(self.config.fanqie.browser_timeout_seconds)) * 1000
        page: Any | None = None
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=bool(self.config.fanqie.headless))
                try:
                    context = await browser.new_context(storage_state=account.state_path)
                    try:
                        page = await context.new_page()
                        page.set_default_timeout(timeout_ms)
                        try:
                            await self._open_create_work_page(page, timeout_ms)
                            try:
                                await self._fill_work(page, payload)
                            except RuntimeError as fill_exc:
                                result = await self._created_shell_result(page, payload, fill_exc)
                                if result is not None:
                                    return result
                                raise
                            result = await self._submit_work(page, payload)
                        except Exception as exc:
                            artifact = await self._save_create_work_artifacts(page, payload, exc)
                            return FanqieResult(
                                ok=False,
                                status="create_failed",
                                message=f"番茄作品创建流程失败：{exc}{artifact}",
                                needs_user_action=True,
                            )
                        return result
                    finally:
                        await context.close()
                finally:
                    await browser.close()
        except Exception as exc:
            artifact = await self._save_create_work_artifacts(page, payload, exc)
            return FanqieResult(
                ok=False,
                status="create_failed",
                message=f"番茄作品创建流程失败：{exc}{artifact}",
                needs_user_action=True,
            )

    async def _get_work_status_with_browser(
        self,
        async_playwright: Callable[..., Any],
        account: ArticleAccount,
        remote_book_id: str,
        work_title: str,
    ) -> FanqieResult:
        """使用浏览器读取番茄章节管理页状态。"""

        timeout_ms = max(1, int(self.config.fanqie.browser_timeout_seconds)) * 1000
        page: Any | None = None
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=bool(self.config.fanqie.headless))
                try:
                    context = await browser.new_context(storage_state=account.state_path)
                    try:
                        page = await context.new_page()
                        page.set_default_timeout(timeout_ms)
                        await page.goto(self._BOOK_MANAGE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                        await self._wait_for_idle(page, timeout_ms)
                        await self._dismiss_guides(page)
                        target_page = await self._open_chapter_manager_by_remote_id(page, context, remote_book_id.strip())
                        if target_page is None:
                            raise RuntimeError(f"未能打开番茄章节管理页：{remote_book_id}")
                        await self._dismiss_guides(target_page)
                        details = await self._extract_work_status(target_page, remote_book_id.strip(), work_title)
                        return FanqieResult(
                            ok=True,
                            status="queried",
                            message="已获取番茄线上状态。",
                            remote_id=remote_book_id.strip(),
                            remote_url=str(getattr(target_page, "url", "")),
                            details=details,
                        )
                    finally:
                        await context.close()
                finally:
                    await browser.close()
        except Exception as exc:
            artifact = await self._save_status_artifacts(page, remote_book_id, work_title, exc)
            return FanqieResult(
                ok=False,
                status="query_failed",
                message=f"番茄线上状态查询失败：{exc}{artifact}",
                remote_id=remote_book_id.strip(),
                needs_user_action=True,
            )

    async def _publish_with_browser(
        self,
        async_playwright: Callable[..., Any],
        account: ArticleAccount,
        payload: FanqiePublishPayload,
    ) -> FanqieResult:
        """使用浏览器自动化发布章节。"""

        timeout_ms = max(1, int(self.config.fanqie.browser_timeout_seconds)) * 1000
        page: Any | None = None
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=bool(self.config.fanqie.headless))
                try:
                    context = await browser.new_context(storage_state=account.state_path)
                    try:
                        page = await context.new_page()
                        page.set_default_timeout(timeout_ms)
                        try:
                            page = await self._open_chapter_editor(page, context, payload, timeout_ms)
                            await self._fill_chapter(page, payload)
                            await self._submit_chapter(page, payload)
                        except Exception as exc:
                            artifact = await self._save_failure_artifacts(page, payload, exc)
                            return FanqieResult(
                                ok=False,
                                status="publish_failed",
                                message=f"番茄发布流程失败：{exc}{artifact}",
                                needs_user_action=True,
                            )
                        return FanqieResult(
                            ok=True,
                            status="published",
                            message=f"章节已提交到番茄发布流程：{payload.chapter_title}",
                            remote_id=payload.content_hash[:16],
                        )
                    finally:
                        await context.close()
                finally:
                    await browser.close()
        except Exception as exc:
            artifact = await self._save_failure_artifacts(page, payload, exc)
            return FanqieResult(
                ok=False,
                status="publish_failed",
                message=f"番茄发布流程失败：{exc}{artifact}",
                needs_user_action=True,
            )

    async def _open_create_work_page(self, page: Any, timeout_ms: int) -> None:
        """打开番茄作品创建页。"""

        await page.goto(self._BOOK_MANAGE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        await self._wait_for_idle(page, timeout_ms)
        await self._dismiss_guides(page)
        for text in ("创建新书", "新建作品", "发布作品", "创建作品"):
            button = page.get_by_role("button", name=text)
            if await button.count() == 0:
                button = page.get_by_text(text, exact=True)
            if await button.count() == 0:
                button = page.locator(".write-button").filter(has_text=text)
            if await button.count() > 0:
                await button.first.click()
                await page.wait_for_timeout(1000)
                await self._dismiss_guides(page)
                return
        raise RuntimeError("未找到番茄新建作品入口")

    async def _created_shell_result(
        self,
        page: Any,
        payload: FanqieCreateWorkPayload,
        exc: RuntimeError,
    ) -> FanqieResult | None:
        """识别番茄已创建默认作品壳但未进入表单的情况。"""

        content = await page.content()
        if "创建章节" not in content or "章节管理" not in content:
            return None
        remote_id = await self._extract_first_book_id(page)
        if not remote_id:
            return None
        return FanqieResult(
            ok=True,
            status="created_shell",
            message=f"番茄已创建默认作品壳，已绑定远端作品 ID：{remote_id}。作品名仍需在番茄后台人工改为：{payload.work_title}（{exc}）",
            remote_id=remote_id,
            remote_url=str(getattr(page, "url", "")),
            needs_user_action=True,
        )

    async def _extract_first_book_id(self, page: Any) -> str:
        """从作品管理页提取第一个作品 ID。"""

        links = page.locator('a[href*="chapter-manage"], a[href*="/publish/"]')
        count = min(await links.count(), 20)
        for index in range(count):
            href = await links.nth(index).get_attribute("href")
            if not href:
                continue
            match = re.search(r"/(?:chapter-manage/)?(\d{6,})", href)
            if match:
                return match.group(1)
        content = await page.content()
        match = re.search(r"(?:chapter-manage/|/writer/)(\d{6,})", content)
        return match.group(1) if match else ""

    async def _fill_work(self, page: Any, payload: FanqieCreateWorkPayload) -> None:
        """填写番茄作品基础信息。"""

        title_input = page.locator('input[placeholder*="作品名"], input[placeholder*="书名"], input[placeholder*="小说名"]').first
        if await title_input.count() == 0:
            title_input = page.locator('input[type="text"]').first
        if await title_input.count() == 0:
            raise RuntimeError("未找到作品名称输入框")
        await title_input.fill(payload.work_title, force=True)
        synopsis = payload.synopsis.strip()
        if synopsis:
            intro = page.locator('textarea[placeholder*="简介"], textarea[placeholder*="介绍"], textarea').first
            if await intro.count() > 0:
                await intro.fill(synopsis, force=True)

    async def _submit_work(self, page: Any, payload: FanqieCreateWorkPayload) -> FanqieResult:
        """提交番茄作品创建表单并提取远端标识。"""

        for text in ("创建", "提交", "保存", "下一步"):
            if await self._maybe_click_text(page, text):
                await self._dismiss_guides(page)
                await page.wait_for_timeout(1500)
                remote_id = await self._extract_remote_book_id(page, payload.work_title)
                return FanqieResult(
                    ok=True,
                    status="created",
                    message=f"番茄作品已创建或已提交创建流程：{payload.work_title}",
                    remote_id=remote_id or payload.work_title,
                    remote_url=str(getattr(page, "url", "")),
                )
        artifact = await self._save_create_work_artifacts(page, payload, RuntimeError("页面需要人工补充必填项"))
        return FanqieResult(
            ok=False,
            status="needs_user_action",
            message=f"番茄作品创建页需要人工补充必填项，请设置 fanqie.headless=false 后人工处理{artifact}",
            needs_user_action=True,
        )

    async def _extract_remote_book_id(self, page: Any, work_title: str) -> str:
        """从当前页面提取番茄作品远端标识。"""

        url = str(getattr(page, "url", ""))
        match = re.search(r"(?:book_id|bookId|book|id)[=/](\d+)", url)
        if match:
            return match.group(1)
        card = await self._find_book_card(page, work_title)
        if card is not None:
            try:
                text = await card.inner_text(timeout=1000)
            except Exception:
                return ""
            match = re.search(r"\b\d{6,}\b", text)
            if match:
                return match.group(0)
        return ""

    async def _save_create_work_artifacts(self, page: Any | None, payload: FanqieCreateWorkPayload, exc: Exception) -> str:
        """保存创建作品失败截图和 HTML。"""

        if page is None:
            return ""
        root = Path(self.config.fanqie.artifacts_root)
        safe_title = self._safe_filename(payload.work_title)
        stamp = int(time.time())
        base = root / safe_title / f"create_work_failed_{stamp}"
        try:
            base.parent.mkdir(parents=True, exist_ok=True)
            screenshot = base.with_suffix(".png")
            html = base.with_suffix(".html")
            await page.screenshot(path=str(screenshot), full_page=True)
            html.write_text(await page.content(), encoding="utf-8")
            return f"；已保存调试产物：{screenshot}，{html}"
        except Exception as artifact_exc:
            return f"；调试产物保存失败：{artifact_exc}"

    async def _open_chapter_editor(
        self,
        page: Any,
        context: Any,
        payload: FanqiePublishPayload,
        timeout_ms: int,
    ) -> Any:
        """进入指定作品的章节编辑页。"""

        await page.goto(self._BOOK_MANAGE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        await self._wait_for_idle(page, timeout_ms)
        await self._dismiss_guides(page)
        page = await self._open_book_chapter_manager(page, context, payload)
        await self._dismiss_guides(page)
        page = await self._open_or_create_chapter(page, context, payload)
        await self._dismiss_guides(page)
        return page

    async def _open_book_chapter_manager(self, page: Any, context: Any, payload: FanqiePublishPayload) -> Any:
        """从作品管理页进入章节管理。"""

        pages_before = len(context.pages)
        if payload.remote_book_id.strip():
            direct_page = await self._open_chapter_manager_by_remote_id(page, context, payload.remote_book_id.strip())
            if direct_page is not None:
                return direct_page
        card = await self._find_book_card(page, payload.work_title, payload.remote_book_id)
        if card is None:
            raise RuntimeError(f"未在番茄作品管理页找到作品：{payload.work_title}。请确认 article_manager 作品标题与番茄后台作品名一致，或在作品中配置 remote_book_id。")
        await card.hover()
        button = card.get_by_text("章节管理", exact=True)
        if await button.count() == 0:
            button = page.get_by_text("章节管理", exact=True)
        if await button.count() == 0:
            raise RuntimeError(f"找到作品 {payload.work_title}，但未找到章节管理入口")
        await button.first.click()
        await page.wait_for_timeout(1000)
        if len(context.pages) > pages_before:
            new_page = context.pages[-1]
            await self._wait_for_idle(new_page, max(1, int(self.config.fanqie.browser_timeout_seconds)) * 1000)
            return new_page
        return page

    async def _open_chapter_manager_by_remote_id(self, page: Any, context: Any, remote_book_id: str) -> Any | None:
        """优先使用远端作品 ID 进入章节管理。"""

        pages_before = len(context.pages)
        link = page.locator(f'a[href*="{remote_book_id}"][href*="chapter-manage"]').first
        if await link.count() > 0:
            await link.click()
            await page.wait_for_timeout(1000)
            if len(context.pages) > pages_before:
                new_page = context.pages[-1]
                await self._wait_for_idle(new_page, max(1, int(self.config.fanqie.browser_timeout_seconds)) * 1000)
                return new_page
            return page
        await page.goto(f"https://fanqienovel.com/main/writer/chapter-manage/{remote_book_id}", wait_until="domcontentloaded")
        await self._wait_for_idle(page, max(1, int(self.config.fanqie.browser_timeout_seconds)) * 1000)
        if "chapter-manage" in str(getattr(page, "url", "")) or await page.get_by_text("新建章节", exact=True).count() > 0:
            return page
        return None

    async def _find_book_card(self, page: Any, work_title: str, remote_book_id: str = "") -> Any | None:
        """查找作品卡片，支持精确文本、远端 ID 和归一化模糊匹配。"""

        selectors = (
            "div, li, section, article",
            '[class*="book"], [class*="card"], [class*="item"]',
        )
        refs = [work_title]
        if remote_book_id.strip():
            refs.append(remote_book_id.strip())
        for ref in refs:
            for selector in selectors:
                cards = page.locator(selector).filter(has_text=ref)
                if await cards.count() > 0:
                    return cards.first
        targets = [self._normalize_match_text(ref) for ref in refs if ref.strip()]
        for selector in selectors:
            cards = page.locator(selector)
            count = min(await cards.count(), 200)
            for index in range(count):
                card = cards.nth(index)
                try:
                    text = await card.inner_text(timeout=1000)
                except Exception:
                    continue
                normalized = self._normalize_match_text(text)
                if any(target and target in normalized for target in targets):
                    return card
        return None

    async def _open_or_create_chapter(self, page: Any, context: Any, payload: FanqiePublishPayload) -> Any:
        """打开已有草稿或创建新章节。"""

        chapter_pattern = re.compile(rf"第\s*{payload.chapter_index}\s*章")
        rows = page.locator("tr, li, .chapter-item").filter(has_text=chapter_pattern)
        if await rows.count() > 0:
            row = rows.first
            action = row.locator("td").last.locator("svg, i, a, span, button, img")
            if await action.count() > 0:
                await action.last.click()
            else:
                await row.click()
            await page.wait_for_timeout(1000)
            if len(context.pages) > 1:
                return context.pages[-1]
            return page
        button = page.get_by_role("button", name="新建章节")
        if await button.count() == 0:
            button = page.get_by_text("新建章节", exact=True)
        if await button.count() == 0:
            if payload.remote_book_id.strip():
                await page.goto(
                    f"https://fanqienovel.com/main/writer/{payload.remote_book_id.strip()}/publish/?enter_from=newchapter_1",
                    wait_until="domcontentloaded",
                )
                await self._wait_for_idle(page, max(1, int(self.config.fanqie.browser_timeout_seconds)) * 1000)
                return page
            raise RuntimeError("未找到新建章节入口")
        pages_before = len(context.pages)
        await button.first.click()
        await page.wait_for_timeout(1500)
        if len(context.pages) > pages_before:
            new_page = context.pages[-1]
            await self._wait_for_idle(new_page, max(1, int(self.config.fanqie.browser_timeout_seconds)) * 1000)
            return new_page
        if await page.locator('input[placeholder*="标题"], input[placeholder*="章节名"], textarea, [contenteditable="true"]').count() == 0 and payload.remote_book_id.strip():
            await page.goto(
                f"https://fanqienovel.com/main/writer/{payload.remote_book_id.strip()}/publish/?enter_from=newchapter_1",
                wait_until="domcontentloaded",
            )
            await self._wait_for_idle(page, max(1, int(self.config.fanqie.browser_timeout_seconds)) * 1000)
        return page

    async def _fill_chapter(self, page: Any, payload: FanqiePublishPayload) -> None:
        """填写章节序号、标题和正文。"""

        inputs = page.locator('input[type="text"]')
        if await inputs.count() > 0:
            await inputs.first.fill(str(payload.chapter_index), force=True)
        title_input = page.locator('input[placeholder*="标题"], input[placeholder*="章节名"]').first
        if await title_input.count() == 0 and await inputs.count() > 1:
            title_input = inputs.last
        if await title_input.count() == 0:
            raise RuntimeError("未找到章节标题输入框")
        await title_input.fill(payload.chapter_title, force=True)
        editor = await self._find_editor(page)
        await editor.click(force=True)
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await editor.evaluate(
            """(node, text) => {
                node.innerText = text;
                node.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
            }""",
            payload.chapter_body,
        )
        await page.keyboard.press("End")
        await page.keyboard.type(" ")
        await page.keyboard.press("Backspace")

    async def _submit_chapter(self, page: Any, payload: FanqiePublishPayload) -> None:
        """提交章节发布。"""

        await self._click_last_text(page, "下一步")
        await page.wait_for_timeout(1000)
        await self._ignore_typo_suggestions(page)
        await self._maybe_click_text(page, "提交")
        await self._handle_risk_dialog(page)
        await self._handle_check_confirm_dialog(page)
        await self._apply_ai_declaration(page, payload)
        confirm = await self._find_confirm_publish_button(page)
        if confirm is None:
            raise RuntimeError("未进入确认发布面板，或未找到确认发布按钮")
        await confirm.last.click()
        await page.wait_for_timeout(3000)

    async def _find_confirm_publish_button(self, page: Any) -> Any | None:
        """查找最终确认发布按钮。"""

        for text in ("确认发布", "确认提交", "立即发布"):
            button = page.get_by_role("button", name=text)
            if await button.count() > 0:
                return button
            button = page.get_by_text(text, exact=True)
            if await button.count() > 0:
                return button
        modal_primary = page.locator(".arco-modal .arco-btn-primary").filter(has_text="发布")
        if await modal_primary.count() > 0:
            return modal_primary
        return None

    async def _extract_work_status(self, page: Any, remote_book_id: str, work_title: str) -> dict[str, Any]:
        """从番茄章节管理页提取作品和章节状态。"""

        page_title = await self._extract_status_title(page, work_title)
        chapters = await self._extract_status_chapters(page)
        return {
            "remote_book_id": remote_book_id,
            "remote_url": str(getattr(page, "url", "")),
            "title": page_title,
            "chapter_count": len(chapters),
            "chapters": chapters,
        }

    async def _extract_status_title(self, page: Any, work_title: str) -> str:
        """提取远端作品标题。"""

        for selector in ('[class*="book"]', '[class*="title"]', "h1", "h2"):
            items = page.locator(selector)
            count = min(await items.count(), 20)
            for index in range(count):
                try:
                    text = (await items.nth(index).inner_text(timeout=500)).strip()
                except Exception:
                    continue
                if text and len(text) <= 80 and (work_title in text or "章" not in text):
                    return text
        return work_title.strip() or "未知作品"

    async def _extract_status_chapters(self, page: Any) -> list[dict[str, str]]:
        """提取章节行摘要。"""

        chapters: list[dict[str, str]] = []
        seen: set[str] = set()
        selectors = (
            "tr",
            ".chapter-item",
            '[class*="chapter-list"] [class*="item"]',
            '[class*="chapter"] [class*="item"]',
            '[class*="chapter"]',
            "li",
        )
        for selector in selectors:
            rows = page.locator(selector)
            count = min(await rows.count(), 120)
            for index in range(count):
                try:
                    text = " ".join((await rows.nth(index).inner_text(timeout=500)).split())
                except Exception:
                    continue
                if not self._looks_like_chapter_row(text) or text in seen:
                    continue
                seen.add(text)
                chapters.append({"title": self._extract_chapter_title(text), "status": self._extract_chapter_status(text), "text": text})
                if len(chapters) >= 20:
                    return chapters
        return chapters

    @staticmethod
    def _looks_like_chapter_row(text: str) -> bool:
        """判断文本是否像章节行。"""

        if len(text) < 2 or len(text) > 220:
            return False
        ignored = (
            "搜索章节",
            "暂无章节内容",
            "暂无数据",
            "暂无内容",
            "作品管理",
            "章节管理",
            "创建章节",
            "新建章节",
            "卷名",
            "章节标题",
            "请输入",
            "筛选",
            "排序",
        )
        if any(marker in text for marker in ignored):
            return False
        chapter_markers = ("第", "章", "章节", "卷")
        status_markers = FanqiePlatformAdapter._chapter_status_aliases()
        return any(marker in text for marker in chapter_markers) or any(marker in text for markers in status_markers.values() for marker in markers)

    @staticmethod
    def _extract_chapter_title(text: str) -> str:
        """从章节行文本中提取标题摘要。"""

        cleaned = " ".join(text.split())
        for markers in FanqiePlatformAdapter._chapter_status_aliases().values():
            for marker in markers:
                if marker in cleaned:
                    cleaned = cleaned.split(marker, 1)[0].strip()
        for marker in ("编辑", "查看", "删除", "数据", "预览", "更多"):
            if marker in cleaned:
                cleaned = cleaned.split(marker, 1)[0].strip()
        return cleaned[:80] or text[:80]

    @staticmethod
    def _extract_chapter_status(text: str) -> str:
        """从章节行文本中提取状态。"""

        for normalized, markers in FanqiePlatformAdapter._chapter_status_aliases().items():
            if any(marker in text for marker in markers):
                return normalized
        if any(marker in text for marker in ("查看", "数据", "评论", "收益")) and any(marker in text for marker in ("第", "章")):
            return "已发布"
        if "编辑" in text and any(marker in text for marker in ("第", "章")):
            return "草稿或待处理"
        return "未显示"

    @staticmethod
    def _chapter_status_aliases() -> dict[str, tuple[str, ...]]:
        """番茄章节状态文案归一化。"""

        return {
            "未通过": ("未通过", "审核未通过", "审核失败", "发布失败", "违规"),
            "审核中": ("审核中", "待审核", "审核审核中", "章节审核中", "正在审核", "审核"),
            "已发布": ("已发布", "已发表", "发布成功", "审核通过", "已上线", "已上架", "展示中"),
            "待发布": ("待发布", "定时发布", "待上线", "待发表"),
            "发布中": ("发布中", "提交中", "同步中"),
            "草稿": ("草稿", "存草稿", "草稿箱", "未发布"),
        }


    async def _dismiss_guides(self, page: Any) -> None:
        """关闭新手引导和遮罩。"""

        for _ in range(3):
            await page.keyboard.press("Escape")
            clicked = False
            for text in self._GUIDE_BUTTON_TEXTS:
                buttons = page.get_by_text(text, exact=True)
                for index in range(await buttons.count()):
                    button = buttons.nth(index)
                    box = await button.bounding_box()
                    if box is not None and box.get("y", 0) > 100:
                        await button.click(force=True)
                        clicked = True
                        await page.wait_for_timeout(300)
                        break
                if clicked:
                    break
            if not clicked:
                return

    async def _handle_risk_dialog(self, page: Any) -> None:
        """处理错别字和风险检测弹窗。"""

        await self._maybe_click_text(page, "提交")
        risk = page.get_by_text("内容风险检测")
        if await risk.count() > 0:
            cancel = page.get_by_text("取消", exact=True)
            if await cancel.count() > 0:
                await cancel.last.click()
                await page.wait_for_timeout(500)

    async def _ignore_typo_suggestions(self, page: Any) -> None:
        """忽略智能纠错建议，避免错字检查阻塞发布。"""

        for text in ("忽略全部", "全部忽略"):
            button = page.locator(".typo-detail-content-footer button").filter(has_text=text)
            if await button.count() == 0:
                button = page.locator(".serial-risk-article button").filter(has_text=text)
            if await button.count() > 0:
                await button.last.click()
                await page.wait_for_timeout(800)
                return

    async def _handle_check_confirm_dialog(self, page: Any) -> None:
        """处理番茄内容检测确认弹窗。"""

        modal = page.locator(".check-modal-confirm, .arco-modal").filter(has_text="检测")
        if await modal.count() == 0:
            return
        for text in ("全面检测", "仅基础检测", "全章检测", "继续发布", "确认", "继续"):
            button = modal.locator("button").filter(has_text=text)
            if await button.count() > 0:
                await button.last.click()
                await page.wait_for_timeout(1500)
                return

    async def _apply_ai_declaration(self, page: Any, payload: FanqiePublishPayload) -> None:
        """处理 AI 使用声明。"""

        if not self.config.ai_declaration.enabled:
            return
        label = "是" if payload.declare_ai_used else "否"
        options = page.get_by_text(label, exact=True)
        if await options.count() > 0:
            await options.last.click(force=True)

    @staticmethod
    async def _click_last_text(page: Any, text: str) -> None:
        """点击最后一个指定文本元素。"""

        locator = page.get_by_text(text, exact=True)
        if await locator.count() == 0:
            raise RuntimeError(f"未找到按钮：{text}")
        await locator.last.click()

    @staticmethod
    async def _maybe_click_text(page: Any, text: str) -> bool:
        """存在指定文本时点击。"""

        locator = page.get_by_text(text, exact=True)
        if await locator.count() == 0:
            return False
        await locator.last.click()
        await page.wait_for_timeout(500)
        return True

    async def _save_failure_artifacts(self, page: Any | None, payload: FanqiePublishPayload, exc: Exception) -> str:
        """保存失败截图和 HTML。"""

        if page is None:
            return ""
        root = Path(self.config.fanqie.artifacts_root)
        safe_title = self._safe_filename(payload.work_title)
        stamp = int(time.time())
        base = root / safe_title / f"publish_failed_{payload.chapter_index}_{stamp}"
        try:
            base.parent.mkdir(parents=True, exist_ok=True)
            screenshot = base.with_suffix(".png")
            html = base.with_suffix(".html")
            await page.screenshot(path=str(screenshot), full_page=True)
            html.write_text(await page.content(), encoding="utf-8")
            return f"；已保存调试产物：{screenshot}，{html}"
        except Exception as artifact_exc:
            return f"；调试产物保存失败：{artifact_exc}"

    async def _save_status_artifacts(self, page: Any | None, remote_book_id: str, work_title: str, exc: Exception) -> str:
        """保存状态查询失败截图和 HTML。"""

        if page is None:
            return ""
        root = Path(self.config.fanqie.artifacts_root)
        safe_title = self._safe_filename(work_title or remote_book_id or "status")
        stamp = int(time.time())
        base = root / safe_title / f"status_failed_{stamp}"
        try:
            base.parent.mkdir(parents=True, exist_ok=True)
            screenshot = base.with_suffix(".png")
            html = base.with_suffix(".html")
            await page.screenshot(path=str(screenshot), full_page=True)
            html.write_text(await page.content(), encoding="utf-8")
            return f"；已保存调试产物：{screenshot}，{html}"
        except Exception as artifact_exc:
            return f"；调试产物保存失败：{artifact_exc}"

    async def _validate_browser_session(self, account: ArticleAccount) -> FanqieResult:
        """使用 Playwright storage_state 打开番茄作者后台并判断登录态。"""

        try:
            async_playwright = self._load_async_playwright()
        except ModuleNotFoundError:
            return FanqieResult(
                ok=False,
                status="dependency_missing",
                message="未安装 playwright；无法打开番茄作者后台校验登录态。",
                needs_user_action=True,
            )

        timeout_ms = max(1, int(self.config.fanqie.browser_timeout_seconds)) * 1000
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=bool(self.config.fanqie.headless))
                try:
                    context = await browser.new_context(storage_state=account.state_path)
                    try:
                        page = await context.new_page()
                        page.set_default_timeout(timeout_ms)
                        await page.goto(
                            self.config.fanqie.writer_zone_url,
                            wait_until="domcontentloaded",
                            timeout=timeout_ms,
                        )
                        await self._wait_for_idle(page, timeout_ms)
                        return await self._classify_login_state(page)
                    finally:
                        await context.close()
                finally:
                    await browser.close()
        except Exception as exc:
            return self._browser_failure_result(exc)

    async def _classify_login_state(self, page: Any) -> FanqieResult:
        """根据页面地址和内容判断是否仍处于登录态。"""

        url = str(getattr(page, "url", ""))
        content = await page.content()
        if self._contains_any(content, self._DASHBOARD_TEXT_MARKERS):
            return FanqieResult(ok=True, status="valid", message="番茄作者后台登录态有效。")
        if self._contains_any(url.lower(), self._LOGIN_URL_MARKERS) or self._contains_any(content, self._LOGIN_TEXT_MARKERS):
            return FanqieResult(
                ok=False,
                status="auth_required",
                message="番茄登录态已失效，请手动登录作者后台并重新导入 storage_state。",
                needs_user_action=True,
            )
        return FanqieResult(
            ok=False,
            status="unknown",
            message="已打开番茄作者后台，但无法自动确认登录态；请人工检查浏览器状态。",
            needs_user_action=True,
        )

    @staticmethod
    async def _wait_for_idle(page: Any, timeout_ms: int) -> None:
        """等待页面空闲；超时不代表登录态无效。"""

        try:
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            return

    @staticmethod
    def _load_async_playwright() -> Callable[..., Any]:
        """动态加载 Playwright，保持番茄自动化为可选依赖。"""

        from playwright.async_api import async_playwright

        return async_playwright

    @staticmethod
    def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
        """判断文本是否包含任意标记。"""

        return any(marker in text for marker in markers)

    @staticmethod
    def _normalize_match_text(value: str) -> str:
        """归一化文本用于作品名匹配。"""

        return "".join(char for char in value.lower() if char.isalnum())

    @staticmethod
    def _safe_filename(value: str) -> str:
        """清理文件名。"""

        cleaned = "".join(char for char in value if char.isalnum() or char in {"_", "-"})
        return cleaned or "unknown"

    @staticmethod
    def _browser_failure_result(exc: Exception) -> FanqieResult:
        """将浏览器启动和 storage_state 读取异常转为安全结果。"""

        message = str(exc)
        lowered = message.lower()
        if "executable" in lowered or "playwright install" in lowered or "browser" in lowered:
            return FanqieResult(
                ok=False,
                status="dependency_missing",
                message="Playwright 浏览器未安装或不可用；请安装浏览器后再校验番茄登录态。",
                needs_user_action=True,
            )
        if "storage_state" in lowered or "storage state" in lowered:
            return FanqieResult(
                ok=False,
                status="auth_required",
                message="番茄 storage_state 无法使用，请重新手动登录并导入登录态。",
                needs_user_action=True,
            )
        return FanqieResult(
            ok=False,
            status="browser_error",
            message=f"番茄登录态校验浏览器流程失败：{message}",
            needs_user_action=True,
        )
