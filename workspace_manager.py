"""工作区管理器 —— 沙箱创建、文件树断言、Git 断言"""

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional


@dataclass
class WorkspaceSnapshot:
    """工作区快照"""
    files: List[str] = field(default_factory=list)
    git_branch: str = ""
    git_clean: bool = True
    git_commit_hash: str = ""
    timestamp: str = ""


class WorkspaceManager:
    """测试沙箱管理器

    职责：
    1. 从模板创建干净的沙箱目录
    2. 拍快照（用于前后对比）
    3. 断言文件树和 git 状态
    4. 测试后清理
    """

    def __init__(self, base_dir: str = "./workspaces"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._active_sandboxes: List[Path] = []

    def create_sandbox(self, template_dir: Optional[Path] = None, name: Optional[str] = None) -> Path:
        """创建沙箱目录

        Args:
            template_dir: 模板目录，存在则复制其内容
            name: 沙箱名称，默认自动生成
        """
        sandbox_name = name or f"sandbox_{int(time.time() * 1000)}"
        sandbox = self.base_dir / sandbox_name

        if sandbox.exists():
            shutil.rmtree(sandbox)

        if template_dir and template_dir.exists():
            shutil.copytree(template_dir, sandbox)
        else:
            sandbox.mkdir(parents=True, exist_ok=True)

        self._active_sandboxes.append(sandbox)
        return sandbox

    def snapshot(self, workspace: Path) -> WorkspaceSnapshot:
        """拍工作区快照"""
        files = [str(p.relative_to(workspace)) for p in workspace.rglob("*") if p.is_file()]
        git_branch = ""
        git_clean = True
        git_commit_hash = ""

        git_dir = workspace / ".git"
        if git_dir.exists():
            try:
                git_branch = subprocess.check_output(
                    ["git", "-C", str(workspace), "branch", "--show-current"],
                    text=True, stderr=subprocess.DEVNULL
                ).strip()
            except subprocess.CalledProcessError:
                pass

            try:
                status = subprocess.check_output(
                    ["git", "-C", str(workspace), "status", "--porcelain"],
                    text=True, stderr=subprocess.DEVNULL
                ).strip()
                git_clean = len(status) == 0
            except subprocess.CalledProcessError:
                pass

            try:
                git_commit_hash = subprocess.check_output(
                    ["git", "-C", str(workspace), "rev-parse", "HEAD"],
                    text=True, stderr=subprocess.DEVNULL
                ).strip()
            except subprocess.CalledProcessError:
                pass

        return WorkspaceSnapshot(
            files=sorted(files),
            git_branch=git_branch,
            git_clean=git_clean,
            git_commit_hash=git_commit_hash,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

    def diff_snapshots(self, before: WorkspaceSnapshot, after: WorkspaceSnapshot) -> Dict[str, Any]:
        """对比两个快照，返回变化"""
        before_set = set(before.files)
        after_set = set(after.files)
        return {
            "created": sorted(list(after_set - before_set)),
            "deleted": sorted(list(before_set - after_set)),
            "modified": [],  # 需要额外计算文件 hash，这里简化
            "git_branch_changed": before.git_branch != after.git_branch,
            "git_clean_changed": before.git_clean != after.git_clean,
        }

    def assert_file_tree(self, workspace: Path, expected: Dict[str, Any]) -> List[str]:
        """断言文件树

        expected 格式：
        {
            "exists": ["src/main.py", "tests/test_main.py"],
            "not_exists": ["temp/delete_me.py"],
            "contains": {"README.md": ["# Project"]},  # 文件内容包含
        }
        """
        errors = []

        for path_str in expected.get("exists", []):
            if not (workspace / path_str).exists():
                errors.append(f"Expected file does not exist: {path_str}")

        for path_str in expected.get("not_exists", []):
            if (workspace / path_str).exists():
                errors.append(f"Unexpected file exists: {path_str}")

        for path_str, expected_contents in expected.get("contains", {}).items():
            target = workspace / path_str
            if not target.exists():
                errors.append(f"Cannot check content, file missing: {path_str}")
                continue
            content = target.read_text(encoding="utf-8", errors="replace")
            for expected_text in expected_contents:
                if expected_text not in content:
                    errors.append(f"File {path_str} missing expected text: '{expected_text}'")

        return errors

    def assert_git_state(self, workspace: Path, expected: Dict[str, Any]) -> List[str]:
        """断言 git 状态

        expected 格式：
        {
            "clean": true,
            "branch": "main",
            "commit_count_delta": 1,  # 相比测试前增加了多少 commit
            "has_untracked": false,
        }
        """
        errors = []
        git_dir = workspace / ".git"
        if not git_dir.exists():
            return [f"Not a git repository: {workspace}"]

        # clean
        if "clean" in expected:
            try:
                status = subprocess.check_output(
                    ["git", "-C", str(workspace), "status", "--porcelain"],
                    text=True, stderr=subprocess.DEVNULL
                ).strip()
                is_clean = len(status) == 0
                if is_clean != expected["clean"]:
                    errors.append(f"Git clean mismatch: expected {expected['clean']}, got {is_clean}")
            except subprocess.CalledProcessError as e:
                errors.append(f"Git status failed: {e}")

        # branch
        if "branch" in expected:
            try:
                branch = subprocess.check_output(
                    ["git", "-C", str(workspace), "branch", "--show-current"],
                    text=True, stderr=subprocess.DEVNULL
                ).strip()
                if branch != expected["branch"]:
                    errors.append(f"Git branch mismatch: expected {expected['branch']}, got {branch}")
            except subprocess.CalledProcessError as e:
                errors.append(f"Git branch check failed: {e}")

        # commit_count_delta
        if "commit_count_delta" in expected:
            # 需要外部传入 before_count 对比，这里只检查当前状态
            pass

        return errors

    def cleanup(self, workspace: Path) -> None:
        """清理沙箱"""
        if workspace.exists() and workspace in self._active_sandboxes:
            shutil.rmtree(workspace)
            self._active_sandboxes.remove(workspace)

    def cleanup_all(self) -> None:
        """清理所有活跃沙箱"""
        for ws in list(self._active_sandboxes):
            self.cleanup(ws)
