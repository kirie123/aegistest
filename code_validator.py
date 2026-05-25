"""代码验证器 —— 语法检查、测试执行、编译验证、代码风格"""

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional


@dataclass
class ValidationResult:
    """验证结果"""
    passed: bool
    checks: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    raw_output: str = ""


class CodeValidator:
    """代码级验证器

    支持：
    - 语法检查（Python / JavaScript / TypeScript / Rust / Go 等）
    - 单元测试执行
    - 编译验证
    - 代码风格检查
    """

    def validate_syntax(self, code: str, language: str = "python") -> ValidationResult:
        """验证代码语法"""
        errors = []
        passed = False

        if language == "python":
            import ast
            try:
                ast.parse(code)
                passed = True
            except SyntaxError as e:
                errors.append(f"Python syntax error: {e}")
        elif language in ("javascript", "typescript"):
            # 尝试用 node 的 --check 或临时写文件用 tsc
            passed = self._check_with_node(code, language)
            if not passed:
                errors.append(f"{language} syntax check failed")
        elif language == "json":
            try:
                json.loads(code)
                passed = True
            except json.JSONDecodeError as e:
                errors.append(f"JSON parse error: {e}")
        else:
            errors.append(f"Syntax validation for '{language}' not implemented")

        return ValidationResult(passed=passed, errors=errors)

    def validate_file_syntax(self, file_path: Path, language: Optional[str] = None) -> ValidationResult:
        """验证文件语法"""
        if not file_path.exists():
            return ValidationResult(passed=False, errors=[f"File not found: {file_path}"])

        lang = language or self._detect_language(file_path)
        code = file_path.read_text(encoding="utf-8", errors="replace")
        return self.validate_syntax(code, lang)

    def run_tests(self, test_dir: Path, command: Optional[str] = None) -> ValidationResult:
        """运行测试

        Args:
            test_dir: 测试所在目录
            command: 自定义测试命令，如 "pytest tests/ -v"
        """
        if command:
            cmd = command if isinstance(command, list) else command.split()
        else:
            # 自动检测
            if (test_dir / "pytest.ini").exists() or list(test_dir.glob("test_*.py")):
                cmd = [sys.executable, "-m", "pytest", str(test_dir), "-v"]
            elif (test_dir / "Cargo.toml").exists():
                cmd = ["cargo", "test"]
            elif (test_dir / "package.json").exists():
                cmd = ["npm", "test"]
            else:
                return ValidationResult(passed=False, errors=["Cannot auto-detect test runner"])

        try:
            result = subprocess.run(
                cmd,
                cwd=str(test_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
            passed = result.returncode == 0
            errors = []
            if not passed:
                errors.append(f"Tests failed with exit code {result.returncode}")
            return ValidationResult(
                passed=passed,
                errors=errors,
                raw_output=result.stdout + "\n" + result.stderr,
                checks={"returncode": result.returncode},
            )
        except subprocess.TimeoutExpired:
            return ValidationResult(passed=False, errors=["Test execution timed out"])
        except FileNotFoundError as e:
            return ValidationResult(passed=False, errors=[f"Test runner not found: {e}"])

    def check_compilation(self, source_dir: Path, build_cmd: str) -> ValidationResult:
        """检查编译"""
        cmd = build_cmd.split() if isinstance(build_cmd, str) else build_cmd
        try:
            result = subprocess.run(
                cmd,
                cwd=str(source_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
            passed = result.returncode == 0
            return ValidationResult(
                passed=passed,
                errors=[] if passed else [f"Compilation failed: {result.stderr[:500]}"],
                raw_output=result.stdout + "\n" + result.stderr,
            )
        except Exception as e:
            return ValidationResult(passed=False, errors=[str(e)])

    def lint(self, source_dir: Path, linter: str = "ruff", files: Optional[List[str]] = None) -> ValidationResult:
        """代码风格检查"""
        if linter == "ruff":
            cmd = ["ruff", "check", str(source_dir)]
        elif linter == "pylint":
            targets = files or [str(source_dir)]
            cmd = ["pylint"] + targets
        elif linter == "eslint":
            targets = files or [str(source_dir)]
            cmd = ["npx", "eslint"] + targets
        else:
            return ValidationResult(passed=False, errors=[f"Unsupported linter: {linter}"])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            passed = result.returncode == 0
            return ValidationResult(
                passed=passed,
                errors=[] if passed else [f"Lint issues found with {linter}"],
                raw_output=result.stdout + "\n" + result.stderr,
                checks={"linter": linter, "issue_count": result.returncode},
            )
        except FileNotFoundError:
            return ValidationResult(
                passed=False,
                errors=[f"{linter} not installed"],
                checks={"linter": linter},
            )

    def _detect_language(self, file_path: Path) -> str:
        """根据后缀检测语言"""
        suffix = file_path.suffix.lower()
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
        }
        return mapping.get(suffix, "unknown")

    def _check_with_node(self, code: str, language: str) -> bool:
        """用 Node.js 检查 JS/TS 语法"""
        suffix = ".ts" if language == "typescript" else ".js"
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8") as f:
                f.write(code)
                tmp_path = f.name

            if language == "typescript":
                result = subprocess.run(
                    ["npx", "tsc", "--noEmit", tmp_path],
                    capture_output=True,
                    timeout=30,
                )
            else:
                result = subprocess.run(
                    ["node", "--check", tmp_path],
                    capture_output=True,
                    timeout=30,
                )
            return result.returncode == 0
        except FileNotFoundError:
            return False
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def validate_project(self, project_dir: Path, assertions: Dict[str, Any]) -> ValidationResult:
        """批量验证项目

        assertions 格式：
        {
            "syntax_valid": true,
            "test_command": "pytest tests/",
            "test_should_pass": true,
            "build_cmd": "cargo build",
            "linter": "ruff"
        }
        """
        all_checks: Dict[str, Any] = {}
        all_errors: List[str] = []

        # 语法检查：扫描所有代码文件
        if assertions.get("syntax_valid", False):
            code_files = list(project_dir.rglob("*.py"))  # 可扩展其他语言
            for f in code_files:
                if ".venv" in str(f) or "node_modules" in str(f):
                    continue
                r = self.validate_file_syntax(f)
                if not r.passed:
                    all_errors.extend(r.errors)
            all_checks["syntax_valid"] = len(all_errors) == 0

        # 编译检查
        if "build_cmd" in assertions:
            r = self.check_compilation(project_dir, assertions["build_cmd"])
            all_checks["compilation"] = r.passed
            if not r.passed:
                all_errors.extend(r.errors)

        # 测试执行
        if "test_command" in assertions:
            r = self.run_tests(project_dir, assertions["test_command"])
            all_checks["tests"] = r.passed
            if assertions.get("test_should_pass", True) and not r.passed:
                all_errors.extend(r.errors)

        # 代码风格
        if "linter" in assertions:
            r = self.lint(project_dir, assertions["linter"])
            all_checks["lint"] = r.passed
            if not r.passed:
                all_errors.extend(r.errors)

        return ValidationResult(
            passed=len(all_errors) == 0,
            checks=all_checks,
            errors=all_errors,
        )
