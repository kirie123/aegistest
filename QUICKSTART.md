# AegisTest + SessionLake 快速上手

## 1. 环境准备

```bash
# 进入项目目录
cd aegistest

# 确保 Python >= 3.10
python --version

# 无需安装依赖（零第三方依赖），直接运行即可
# 如果你想以包形式安装：
pip install -e .
```

## 2. 运行现有示例

### 示例 1：基础测试（原有功能）
```bash
cd aegistest
python examples/basic_example.py
```
输出：`reports/` 目录下生成 HTML/JSON/Markdown 报告

### 示例 2：SessionLake 完整功能测试
```bash
cd aegistest
python examples/test_session_lake.py
```
验证：7 个测试全部 PASS，覆盖存储、训练数据导出、DPO、自进化 review、Curator 维护

### 示例 3：查看自进化产物（Skill + Memory）
```bash
cd aegistest
python examples/show_skills.py
```
产物位置：
- Skill：`~/.aegistest_demo/skills/`
- Memory：`~/.aegistest_demo/memory.json`
- Session：`./sessions_showcase/`

### 示例 4：端到端演示（测试 + 数据导出 + 进化）
```bash
cd aegistest
python examples/evolution_example.py
```

## 3. 接入你自己的 Agent

### 最小改动：只加测试

```python
from aegistest import AegisTest, TestCase, TestSuite, TestCategory, TestPriority
from aegistest.core.agent_interface import AgentInterface, AgentRunResult, AgentStep

# 你的 Agent（已实现 AgentInterface）
class MyAgent(AgentInterface):
    @property
    def name(self): return "my-agent"
    @property
    def version(self): return "1.0"

    def run(self, user_input: str, **kwargs) -> AgentRunResult:
        # 调用你的真实 Agent 逻辑
        ...

    def run_stream(self, user_input: str, **kwargs):
        result = self.run(user_input, **kwargs)
        for step in result.steps:
            yield step

    # 关键：暴露消息历史（用于 SessionLake 持久化）
    def get_message_history(self):
        return self._messages

# 定义测试用例
suite = TestSuite(name="My Suite", description="")
suite.add(TestCase(
    id="test_001",
    input="你的测试输入",
    expected_output_contains=["期望包含的文本"],
    category=TestCategory.FUNCTIONAL,
    priority=TestPriority.HIGH,
    timeout=60,
))

# 只测试（不启用 SessionLake）
aegis = AegisTest(agent=MyAgent())
aegis.run_suite(suite)
aegis.generate_report(fmt="html")
```

### 进阶：测试 + 数据沉淀 + 自进化

```python
from aegistest import AegisTest, SessionLake, TestCase, TestSuite

# 1. 创建数据平台
lake = SessionLake(
    session_dir="./my_sessions",
    skill_dir="~/.my_agent/skills",
    memory_file="~/.my_agent/memory.json",
    enable_evolution=True,
)

# 2. 测试时自动记录 Session
aegis = AegisTest(agent=MyAgent(), session_lake=lake)
aegis.run_suite(suite)

# 3. 导出训练数据
lake.export_training_data(
    "train_data.json",
    output_format="chatml",
    require_success=True,
)

# 4. 运行进化维护
lake.run_evolution_maintenance()
```

### 生产环境直接使用（非测试场景）

```python
from aegistest import SessionLake
from aegistest.session.session_storage import SessionEntry

lake = SessionLake(
    session_dir="./prod_sessions",
    skill_dir="~/.my_agent/skills",
    enable_evolution=True,
)

# Agent 每次运行后写入
sid = "user-session-001"
lake.storage.start_session(sid, "run-001")
lake.storage.append_entries("default", sid, [
    SessionEntry(uuid="u1", type="user", content="用户输入", session_id=sid),
    SessionEntry(uuid="a1", type="assistant", content="Agent回复", parent_uuid="u1", session_id=sid),
])

# 触发 review
session_file = str(lake.storage.get_session_file("default", sid))
lake.review_session(session_file)
```

## 4. 查看产物

```bash
# Session 文件（JSONL，每行一个 entry）
cat ./sessions/default/<session_id>.jsonl

# Skill 目录
tree ~/.aegistest/skills/

# Memory 文件
cat ~/.aegistest/memory.json

# 训练数据
cat train_data.json | python -m json.tool
```

## 5. 常见问题

**Q: 中文显示乱码？**  
Windows PowerShell 默认 GBK 编码。不影响文件内容，只是终端显示问题。

**Q: 需要 GPU 或 LLM API？**  
不需要。自进化默认使用 rule-based review（零成本）。如需 LLM review，传入 `llm_client`。

**Q: 如何清理历史数据？**  
直接删除目录即可：
```bash
rm -rf ./sessions ~/.aegistest/skills ~/.aegistest/memory.json
```
