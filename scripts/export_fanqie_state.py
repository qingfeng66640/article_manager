"""导出番茄作者后台 Playwright 登录态。

运行方式：
    python plugins/article_manager/scripts/export_fanqie_state.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

LOGIN_URL = "https://fanqienovel.com/writer/zone/"
DEFAULT_STATE_PATH = Path("data/plugins/article_manager/sessions/fanqie_storage_state.json")


async def main() -> None:
    """打开浏览器登录番茄作者后台并保存 storage_state。"""

    state_path = DEFAULT_STATE_PATH.resolve()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(LOGIN_URL)
        print("请在打开的浏览器中完成番茄作者后台登录。")
        print("登录后请确认已经能看到作者后台，而不是仍停留在登录页或验证页。")
        input("确认登录完成后，回到终端按 Enter 保存登录态...")
        await context.storage_state(path=str(state_path))
        await browser.close()
    print(f"登录态已保存到: {state_path}")
    print("绑定命令示例：")
    print(f"/小说 bind qf {state_path} auto")


if __name__ == "__main__":
    asyncio.run(main())
