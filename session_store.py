"""番茄登录态文件存储。"""

from __future__ import annotations

import shutil
from pathlib import Path


class FanqieSessionStore:
    """管理按用户隔离的 Playwright 登录态文件。"""

    def __init__(self, root: str) -> None:
        """创建登录态存储。"""

        self.root = Path(root)

    def account_state_path(self, owner_person_id: str, account_id: str) -> Path:
        """返回账号登录态保存路径。"""

        safe_owner = self._safe_segment(owner_person_id)
        safe_account = self._safe_segment(account_id)
        return self.root / safe_owner / "fanqie" / safe_account / "storage_state.json"

    def import_state_file(
        self,
        *,
        owner_person_id: str,
        account_id: str,
        source_path: str,
    ) -> Path:
        """导入用户手动登录得到的 Playwright storage_state 文件。"""

        source = Path(source_path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"番茄登录态文件不存在: {source_path}")
        target = self.account_state_path(owner_person_id, account_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() == target.resolve():
            return target
        shutil.copyfile(source, target)
        return target

    def revoke(self, owner_person_id: str, account_id: str) -> bool:
        """删除指定账号的本地登录态。"""

        path = self.account_state_path(owner_person_id, account_id)
        if path.exists():
            path.unlink()
            return True
        return False

    @staticmethod
    def _safe_segment(value: str) -> str:
        """清理路径片段，避免路径穿越。"""

        cleaned = "".join(char for char in value if char.isalnum() or char in {"_", "-"})
        if not cleaned:
            raise ValueError("路径片段不能为空")
        return cleaned
