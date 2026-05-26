"""报告生成器 —— 支持 HTML、JSON、Markdown 等多种格式"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime


class ReportGenerator:
    """AegisTest 报告生成器

    支持格式：
    - HTML: 单页可视化报告（默认）
    - JSON: 结构化数据，方便 CI/CD 解析
    - Markdown: 轻量文本报告
    """

    def __init__(self, report_dir: str = "./reports"):
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        results: List[Any],
        run_id: str,
        agent_name: str,
        agent_version: str,
        output_path: Optional[str] = None,
        fmt: str = "html",
    ) -> str:
        """生成报告

        Args:
            results: ExecutionResult 列表
            run_id: 本次运行 ID
            agent_name: Agent 名称
            agent_version: Agent 版本
            output_path: 输出路径（默认自动生成）
            fmt: 格式，支持 html / json / markdown
        """
        if fmt == "html":
            return self._generate_html(results, run_id, agent_name, agent_version, output_path)
        elif fmt == "json":
            return self._generate_json(results, run_id, agent_name, agent_version, output_path)
        elif fmt == "markdown":
            return self._generate_markdown(results, run_id, agent_name, agent_version, output_path)
        else:
            raise ValueError(f"Unsupported report format: {fmt}")

    def _generate_html(
        self,
        results: List[Any],
        run_id: str,
        agent_name: str,
        agent_version: str,
        output_path: Optional[str] = None,
    ) -> str:
        """生成交互式 HTML 报告"""
        if output_path is None:
            output_path = self.report_dir / f"report_{run_id}.html"
        else:
            output_path = Path(output_path)

        passed = sum(1 for r in results if r.success)
        failed = len(results) - passed
        safety_issues = sum(len(r.safety_violations) for r in results)
        pass_rate = (passed / len(results) * 100) if results else 0

        # 失败分类统计
        failure_cats: Dict[str, int] = {}
        for r in results:
            if not r.success and r.failure_category:
                failure_cats[r.failure_category] = failure_cats.get(r.failure_category, 0) + 1

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AegisTest Report - {run_id}</title>
    <style>
        :root {{
            --success: #22c55e;
            --success-light: #dcfce7;
            --fail: #ef4444;
            --fail-light: #fef2f2;
            --warning: #f59e0b;
            --warning-light: #fffbeb;
            --info: #3b82f6;
            --info-light: #eff6ff;
            --neutral: #6b7280;
            --bg: #f8fafc;
            --card: #ffffff;
            --border: #e2e8f0;
            --text: #1e293b;
            --text-secondary: #64748b;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}

        /* Header */
        .header {{
            background: var(--card);
            border-radius: 12px;
            padding: 24px 28px;
            margin-bottom: 24px;
            border: 1px solid var(--border);
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }}
        .header h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 4px; }}
        .header-meta {{ color: var(--text-secondary); font-size: 0.875rem; }}
        .header-meta span {{ margin-right: 16px; }}

        /* Summary Cards */
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 24px;
        }}
        .summary-card {{
            background: var(--card);
            border-radius: 12px;
            padding: 20px;
            border: 1px solid var(--border);
            text-align: center;
            transition: transform 0.15s;
        }}
        .summary-card:hover {{ transform: translateY(-2px); }}
        .summary-card .number {{ font-size: 2rem; font-weight: 700; line-height: 1; margin-bottom: 6px; }}
        .summary-card .label {{ font-size: 0.8125rem; color: var(--text-secondary); font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }}
        .summary-card.total .number {{ color: var(--info); }}
        .summary-card.pass .number {{ color: var(--success); }}
        .summary-card.fail .number {{ color: var(--fail); }}
        .summary-card.safety .number {{ color: var(--warning); }}

        /* Pass Rate Bar */
        .pass-rate {{
            background: var(--card);
            border-radius: 12px;
            padding: 20px 28px;
            border: 1px solid var(--border);
            margin-bottom: 24px;
            display: flex;
            align-items: center;
            gap: 24px;
        }}
        .pass-rate-chart {{
            position: relative;
            width: 80px; height: 80px; flex-shrink: 0;
        }}
        .pass-rate-chart svg {{ transform: rotate(-90deg); }}
        .pass-rate-chart .pct {{
            position: absolute; top: 50%; left: 50%;
            transform: translate(-50%, -50%);
            font-size: 1.1rem; font-weight: 700; color: var(--text);
        }}
        .pass-rate-info {{ flex: 1; }}
        .pass-rate-info .title {{ font-size: 0.875rem; color: var(--text-secondary); margin-bottom: 4px; }}
        .pass-rate-bar {{
            height: 8px; background: var(--fail-light);
            border-radius: 4px; overflow: hidden; margin-bottom: 6px;
        }}
        .pass-rate-bar-fill {{
            height: 100%; background: linear-gradient(90deg, var(--success), #4ade80);
            border-radius: 4px; transition: width 0.5s ease;
        }}
        .pass-rate-info .detail {{ font-size: 0.8125rem; color: var(--text-secondary); }}

        /* Failure Distribution */
        .failure-dist {{
            background: var(--card);
            border-radius: 12px;
            padding: 20px 28px;
            border: 1px solid var(--border);
            margin-bottom: 24px;
        }}
        .failure-dist h2 {{ font-size: 1rem; font-weight: 600; margin-bottom: 12px; }}
        .failure-tags {{ display: flex; flex-wrap: wrap; gap: 8px; }}
        .failure-tag {{
            display: inline-flex; align-items: center; gap: 6px;
            padding: 6px 12px; border-radius: 20px; font-size: 0.8125rem; font-weight: 500;
            background: var(--fail-light); color: var(--fail); border: 1px solid #fecaca;
        }}
        .failure-tag .count {{
            background: var(--fail); color: white; border-radius: 10px;
            padding: 0 6px; font-size: 0.6875rem; font-weight: 700; line-height: 16px;
        }}

        /* Test List */
        .test-list {{
            background: var(--card);
            border-radius: 12px;
            border: 1px solid var(--border);
            overflow: hidden;
        }}
        .test-list-header {{
            display: grid;
            grid-template-columns: 48px 2fr 1fr 100px 80px 80px 100px;
            gap: 8px;
            padding: 12px 20px;
            background: #f1f5f9;
            font-size: 0.6875rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-secondary);
            border-bottom: 1px solid var(--border);
        }}

        /* Test Row */
        .test-row {{ border-bottom: 1px solid var(--border); }}
        .test-row:last-child {{ border-bottom: none; }}
        .test-summary {{
            display: grid;
            grid-template-columns: 48px 2fr 1fr 100px 80px 80px 100px;
            gap: 8px;
            padding: 14px 20px;
            align-items: center;
            cursor: pointer;
            transition: background 0.1s;
            user-select: none;
        }}
        .test-summary:hover {{ background: #f8fafc; }}
        .test-row.expanded .test-summary {{ background: #f8fafc; }}

        .status-icon {{
            width: 28px; height: 28px; border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-size: 0.875rem; font-weight: 700;
        }}
        .status-icon.pass {{ background: var(--success-light); color: var(--success); }}
        .status-icon.fail {{ background: var(--fail-light); color: var(--fail); }}

        .test-id {{ font-weight: 600; font-size: 0.9375rem; }}
        .test-category {{ font-size: 0.8125rem; color: var(--text-secondary); }}
        .test-metric {{ font-size: 0.8125rem; color: var(--text-secondary); text-align: center; }}
        .test-metric .value {{ font-weight: 600; color: var(--text); }}
        .safety-pill {{
            display: inline-block; padding: 2px 8px; border-radius: 10px;
            font-size: 0.6875rem; font-weight: 600;
            background: var(--warning-light); color: var(--warning);
        }}
        .expand-icon {{
            text-align: center; color: var(--text-secondary);
            transition: transform 0.2s; font-size: 0.75rem;
        }}
        .test-row.expanded .expand-icon {{ transform: rotate(180deg); }}

        /* Test Detail Panel */
        .test-detail {{
            display: none;
            padding: 0 20px 20px;
            animation: fadeIn 0.2s ease;
        }}
        .test-row.expanded .test-detail {{ display: block; }}
        @keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}

        .detail-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
            margin-bottom: 16px;
        }}
        .detail-card {{
            background: var(--bg); border-radius: 8px; padding: 14px 16px;
            border: 1px solid var(--border);
        }}
        .detail-card .label {{ font-size: 0.6875rem; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-secondary); font-weight: 600; margin-bottom: 4px; }}
        .detail-card .value {{ font-size: 0.9375rem; font-weight: 600; color: var(--text); }}
        .detail-card .value.error {{ color: var(--fail); }}
        .detail-card .value.ok {{ color: var(--success); }}

        /* Section Titles */
        .section-title {{
            font-size: 0.8125rem; font-weight: 600; text-transform: uppercase;
            letter-spacing: 0.5px; color: var(--text-secondary);
            margin: 20px 0 10px; padding-bottom: 6px;
            border-bottom: 1px solid var(--border);
        }}

        /* Code Blocks */
        pre {{
            background: #0f172a; color: #e2e8f0; padding: 16px;
            border-radius: 8px; overflow-x: auto; font-size: 0.8125rem;
            line-height: 1.6; white-space: pre-wrap; word-wrap: break-word;
            max-height: 400px; overflow-y: auto;
        }}
        code {{
            background: #f1f5f9; color: var(--text);
            padding: 1px 5px; border-radius: 4px; font-size: 0.8125rem;
            font-family: 'SF Mono', Monaco, monospace;
        }}
        pre code {{ background: none; padding: 0; }}

        /* Timeline */
        .timeline {{
            position: relative; padding-left: 24px;
        }}
        .timeline::before {{
            content: ''; position: absolute; left: 7px; top: 4px; bottom: 4px;
            width: 2px; background: var(--border); border-radius: 1px;
        }}
        .timeline-item {{
            position: relative; margin-bottom: 12px;
            padding: 10px 14px; background: var(--bg); border-radius: 8px;
            border: 1px solid var(--border);
        }}
        .timeline-item::before {{
            content: ''; position: absolute; left: -20px; top: 14px;
            width: 10px; height: 10px; border-radius: 50%;
            background: var(--neutral); border: 2px solid var(--card);
        }}
        .timeline-item.tool-call::before {{ background: var(--info); }}
        .timeline-item.tool-result::before {{ background: var(--success); }}
        .timeline-item.error::before {{ background: var(--fail); }}
        .timeline-item.thought::before {{ background: var(--warning); }}
        .timeline-header {{
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 6px;
        }}
        .timeline-type {{
            font-size: 0.6875rem; font-weight: 600; text-transform: uppercase;
            letter-spacing: 0.5px; padding: 2px 8px; border-radius: 4px;
        }}
        .timeline-type.tool-call {{ background: var(--info-light); color: var(--info); }}
        .timeline-type.tool-result {{ background: var(--success-light); color: var(--success); }}
        .timeline-type.error {{ background: var(--fail-light); color: var(--fail); }}
        .timeline-type.thought {{ background: var(--warning-light); color: var(--warning); }}
        .timeline-type.response {{ background: #f3e8ff; color: #9333ea; }}
        .timeline-step {{ font-size: 0.6875rem; color: var(--text-secondary); }}
        .timeline-content {{ font-size: 0.8125rem; color: var(--text); white-space: pre-wrap; word-wrap: break-word; }}
        .timeline-tool {{
            margin-top: 6px; padding: 8px; background: white;
            border-radius: 6px; border: 1px solid var(--border);
            font-size: 0.75rem;
        }}
        .timeline-tool-name {{ font-weight: 600; color: var(--info); margin-bottom: 2px; }}
        .timeline-tool-result {{
            margin-top: 4px; padding-top: 4px; border-top: 1px dashed var(--border);
            color: var(--text-secondary);
        }}

        /* Tool Table */
        .tool-table {{
            width: 100%; border-collapse: collapse; font-size: 0.8125rem;
        }}
        .tool-table th {{
            text-align: left; padding: 10px 12px; background: #f1f5f9;
            font-weight: 600; color: var(--text-secondary); font-size: 0.6875rem;
            text-transform: uppercase; letter-spacing: 0.5px;
            border-bottom: 1px solid var(--border);
        }}
        .tool-table td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }}
        .tool-table tr:last-child td {{ border-bottom: none; }}
        .tool-table .status {{
            display: inline-flex; align-items: center; gap: 4px;
            padding: 2px 8px; border-radius: 10px; font-size: 0.6875rem; font-weight: 600;
        }}
        .tool-table .status.success {{ background: var(--success-light); color: var(--success); }}
        .tool-table .status.fail {{ background: var(--fail-light); color: var(--fail); }}
        .tool-table .status::before {{
            content: ''; width: 6px; height: 6px; border-radius: 50%;
        }}
        .tool-table .status.success::before {{ background: var(--success); }}
        .tool-table .status.fail::before {{ background: var(--fail); }}
        .tool-table code {{ font-size: 0.75rem; }}

        /* File Operations */
        .file-ops {{
            display: flex; flex-wrap: wrap; gap: 8px;
        }}
        .file-op {{
            display: inline-flex; align-items: center; gap: 6px;
            padding: 6px 12px; border-radius: 6px; font-size: 0.8125rem;
            background: var(--bg); border: 1px solid var(--border);
        }}
        .file-op.read {{ border-left: 3px solid var(--info); }}
        .file-op.write {{ border-left: 3px solid var(--success); }}
        .file-op.edit {{ border-left: 3px solid var(--warning); }}
        .file-op.dir {{ border-left: 3px solid var(--neutral); }}

        /* Alert Boxes */
        .alert {{
            padding: 12px 16px; border-radius: 8px; margin: 12px 0;
            font-size: 0.875rem;
        }}
        .alert.fail {{ background: var(--fail-light); border: 1px solid #fecaca; color: #991b1b; }}
        .alert.warning {{ background: var(--warning-light); border: 1px solid #fde68a; color: #92400e; }}
        .alert strong {{ font-weight: 600; }}

        /* Responsive */
        @media (max-width: 768px) {{
            .summary-grid {{ grid-template-columns: repeat(2, 1fr); }}
            .test-list-header {{ display: none; }}
            .test-summary {{ grid-template-columns: 40px 1fr 40px; }}
            .test-summary > *:nth-child(3),
            .test-summary > *:nth-child(4),
            .test-summary > *:nth-child(5),
            .test-summary > *:nth-child(6) {{ display: none; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>🛡️ AegisTest Report</h1>
            <div class="header-meta">
                <span>📌 Run <code>{run_id}</code></span>
                <span>🤖 {agent_name} <code>v{agent_version}</code></span>
                <span>🕒 {datetime.now().strftime("%Y-%m-%d %H:%M")}</span>
            </div>
        </div>

        <!-- Summary Cards -->
        <div class="summary-grid">
            <div class="summary-card total">
                <div class="number">{len(results)}</div>
                <div class="label">Total</div>
            </div>
            <div class="summary-card pass">
                <div class="number">{passed}</div>
                <div class="label">Passed</div>
            </div>
            <div class="summary-card fail">
                <div class="number">{failed}</div>
                <div class="label">Failed</div>
            </div>
            <div class="summary-card safety">
                <div class="number">{safety_issues}</div>
                <div class="label">Safety</div>
            </div>
        </div>

        <!-- Pass Rate -->
        <div class="pass-rate">
            <div class="pass-rate-chart">
                <svg width="80" height="80" viewBox="0 0 80 80">
                    <circle cx="40" cy="40" r="36" fill="none" stroke="#fecaca" stroke-width="6"/>
                    <circle cx="40" cy="40" r="36" fill="none" stroke="#22c55e" stroke-width="6"
                        stroke-dasharray="{226.2 * pass_rate / 100:.1f} 226.2"
                        stroke-linecap="round"/>
                </svg>
                <div class="pct">{pass_rate:.0f}%</div>
            </div>
            <div class="pass-rate-info">
                <div class="title">Pass Rate</div>
                <div class="pass-rate-bar">
                    <div class="pass-rate-bar-fill" style="width: {pass_rate}%"></div>
                </div>
                <div class="detail">{passed} passed · {failed} failed · {len(results)} total</div>
            </div>
        </div>
"""

        # 失败分类
        if failure_cats:
            html += """        <div class="failure-dist">
            <h2>🔍 Failure Distribution</h2>
            <div class="failure-tags">
"""
            for cat, count in sorted(failure_cats.items(), key=lambda x: -x[1]):
                html += f"""                <span class="failure-tag">{cat}<span class="count">{count}</span></span>
"""
            html += """            </div>
        </div>
"""

        # 测试列表
        html += """        <div class="test-list">
            <div class="test-list-header">
                <div></div>
                <div>Test ID / Category</div>
                <div>Category</div>
                <div style="text-align:center">Latency</div>
                <div style="text-align:center">Steps</div>
                <div style="text-align:center">Tools</div>
                <div style="text-align:center"></div>
            </div>
"""

        for r in results:
            html += self._render_test_row(r)

        html += """        </div>
    </div>

    <script>
    document.querySelectorAll('.test-summary').forEach(row => {
        row.addEventListener('click', () => {
            const parent = row.closest('.test-row');
            const isExpanded = parent.classList.contains('expanded');
            // Close all others (optional - accordion style)
            // document.querySelectorAll('.test-row.expanded').forEach(el => el.classList.remove('expanded'));
            parent.classList.toggle('expanded', !isExpanded);
        });
    });
    </script>
</body>
</html>"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\ufeff")
            f.write(html)

        return str(output_path)

    def _render_test_row(self, r: Any) -> str:
        """渲染单个测试行（含展开详情）"""
        status_class = "pass" if r.success else "fail"
        status_icon = "✓" if r.success else "✕"

        # 从 execution_insights 提取指标
        insights = r.execution_insights or {}
        session = insights.get("session", {})
        tools = insights.get("tools", {})
        files = insights.get("files", {})
        failures = insights.get("failures", {})

        tool_count = tools.get("total_calls", 0)
        error_count = failures.get("error_count", 0)
        step_count = session.get("total_steps", r.steps_used or 0)
        latency = session.get("total_latency_ms", r.latency_ms or 0)

        # 安全违规提示
        safety_html = ""
        if r.safety_violations:
            safety_html = f'<span class="safety-pill">⚠ {len(r.safety_violations)}</span>'

        html = f"""        <div class="test-row">
            <div class="test-summary">
                <div class="status-icon {status_class}">{status_icon}</div>
                <div>
                    <div class="test-id">{r.test_id}</div>
                    <div class="test-category">{r.test_input[:60]}{"..." if len(str(r.test_input)) > 60 else ""}</div>
                </div>
                <div class="test-category">{r.failure_category or "-"}</div>
                <div class="test-metric"><span class="value">{latency:.0f}</span>ms</div>
                <div class="test-metric"><span class="value">{step_count}</span></div>
                <div class="test-metric">{safety_html or f'<span class="value">{tool_count}</span>'}</div>
                <div class="expand-icon">▼</div>
            </div>
            <div class="test-detail">
"""

        # === 详情面板 ===

        # 1. 指标卡片
        html += """                <div class="detail-grid">
"""
        html += f"""                    <div class="detail-card">
                        <div class="label">Status</div>
                        <div class="value {'ok' if r.success else 'error'}">{"PASS" if r.success else "FAIL"}</div>
                    </div>
                    <div class="detail-card">
                        <div class="label">Steps</div>
                        <div class="value">{step_count}</div>
                    </div>
                    <div class="detail-card">
                        <div class="label">Tool Calls</div>
                        <div class="value">{tool_count}</div>
                    </div>
                    <div class="detail-card">
                        <div class="label">Errors</div>
                        <div class="value {'error' if error_count > 0 else 'ok'}">{error_count}</div>
                    </div>
                    <div class="detail-card">
                        <div class="label">Turns</div>
                        <div class="value">{session.get('turn_count', 1)}</div>
                    </div>
                    <div class="detail-card">
                        <div class="label">Latency</div>
                        <div class="value">{latency:.0f}ms</div>
                    </div>
"""
        html += """                </div>
"""

        # 2. 失败原因 / 安全违规
        if not r.success and r.failure_reason:
            html += f"""                <div class="alert fail">
                    <strong>Failure:</strong> {r.failure_reason}
                    {f'<br><strong>Category:</strong> {r.failure_category}' if r.failure_category else ''}
                </div>
"""
        if r.safety_violations:
            for v in r.safety_violations:
                sev = v.get("severity", "warning")
                html += f"""                <div class="alert warning">
                    <strong>Safety ({sev.upper()}):</strong> {v.get('rule', '')} — {v.get('details', '')}
                </div>
"""

        # 3. Agent Output
        if r.agent_output:
            html += """                <div class="section-title">📝 Agent Output</div>
                <pre><code>"""
            html += self._escape_html(r.agent_output)
            html += """</code></pre>
"""

        # 4. 执行过程时间线（从 agent_result.steps）
        steps = []
        if r.agent_result and r.agent_result.steps:
            steps = r.agent_result.steps
        elif r.trace:
            # Fallback: 从 trace 重建
            for t in r.trace:
                step_type = t.get("type", "unknown")
                if step_type == "tool_call":
                    step_type = "tool_call"
                elif step_type == "tool_result":
                    step_type = "tool_result"
                elif step_type == "error":
                    step_type = "error"
                elif step_type == "thought":
                    step_type = "thought"
                else:
                    step_type = "response"
                steps.append(type('Step', (), {
                    'step_number': t.get('step_number', 0),
                    'step_type': step_type,
                    'content': t.get('content', ''),
                    'tool_name': t.get('tool'),
                    'tool_args': t.get('args'),
                    'tool_result': t.get('result'),
                    'latency_ms': t.get('latency_ms', 0),
                })())

        if steps:
            html += """                <div class="section-title">📋 Execution Timeline</div>
                <div class="timeline">
"""
            for step in steps:
                step_type = getattr(step, 'step_type', 'unknown')
                content = getattr(step, 'content', '') or ''
                tool_name = getattr(step, 'tool_name', None)
                tool_args = getattr(step, 'tool_args', None)
                tool_result = getattr(step, 'tool_result', None)
                step_num = getattr(step, 'step_number', 0)
                step_latency = getattr(step, 'latency_ms', 0)

                css_type = step_type
                if step_type in ("tool_call",):
                    css_type = "tool-call"
                elif step_type in ("tool_result",):
                    css_type = "tool-result"

                type_label = step_type.replace('_', ' ').upper()

                html += f"""                    <div class="timeline-item {css_type}">
                        <div class="timeline-header">
                            <span class="timeline-type {css_type}">{type_label}</span>
                            <span class="timeline-step">Step {step_num}{f' · {step_latency:.0f}ms' if step_latency else ''}</span>
                        </div>
                        <div class="timeline-content">{self._escape_html(content[:500])}{"..." if len(content) > 500 else ""}</div>
"""
                if tool_name:
                    html += f"""                        <div class="timeline-tool">
                            <div class="timeline-tool-name">🔧 {tool_name}</div>
"""
                    if tool_args:
                        args_str = json.dumps(tool_args, ensure_ascii=False, indent=2) if isinstance(tool_args, dict) else str(tool_args)
                        html += f"""                            <div><strong>Args:</strong> <code>{self._escape_html(args_str[:300])}{'...' if len(args_str) > 300 else ''}</code></div>
"""
                    if tool_result:
                        result_str = str(tool_result)
                        html += f"""                            <div class="timeline-tool-result"><strong>Result:</strong> {self._escape_html(result_str[:300])}{'...' if len(result_str) > 300 else ''}</div>
"""
                    html += """                        </div>
"""
                html += """                    </div>
"""
            html += """                </div>
"""

        # 5. 工具调用表格（从 execution_insights.tools.timeline）
        timeline = tools.get("timeline", [])
        if timeline:
            html += """                <div class="section-title">🛠️ Tool Calls</div>
                <table class="tool-table">
                    <tr>
                        <th>Step</th>
                        <th>Tool</th>
                        <th>Status</th>
                        <th>Arguments</th>
                    </tr>
"""
            for item in timeline:
                status = item.get("status", "unknown")
                status_class = "success" if status == "success" else "fail"
                status_text = status.upper()
                args_preview = item.get("args_preview", "")
                html += f"""                    <tr>
                        <td>{item.get('step', '-')}</td>
                        <td><code>{item.get('tool', '-')}</code></td>
                        <td><span class="status {status_class}">{status_text}</span></td>
                        <td><code>{self._escape_html(args_preview[:120])}{'...' if len(args_preview) > 120 else ''}</code></td>
                    </tr>
"""
            html += """                </table>
"""

        # 6. 文件操作
        has_files = files.get("read") or files.get("written") or files.get("edited") or files.get("directories_created")
        if has_files:
            html += """                <div class="section-title">📁 File Operations</div>
                <div class="file-ops">
"""
            for fpath in files.get("read", []):
                html += f"""                    <span class="file-op read">📖 {self._escape_html(fpath)}</span>
"""
            for fpath in files.get("written", []):
                html += f"""                    <span class="file-op write">✏️ {self._escape_html(fpath)}</span>
"""
            for fpath in files.get("edited", []):
                html += f"""                    <span class="file-op edit">🔧 {self._escape_html(fpath)}</span>
"""
            for dpath in files.get("directories_created", []):
                html += f"""                    <span class="file-op dir">📁 {self._escape_html(dpath)}</span>
"""
            html += """                </div>
"""

        # 7. 失败链
        if failures.get("error_count", 0) > 0:
            html += f"""                <div class="section-title">⚠️ Failure Chain</div>
                <div class="alert fail">
                    <strong>Total Errors:</strong> {failures.get('error_count')} |
                    <strong>Recovery Detected:</strong> {'✅ Yes' if failures.get('recovery_detected') else '❌ No'}
                </div>
"""
            for fc in failures.get("failure_chain", []):
                html += f"""                <p style="font-size:0.8125rem; margin:4px 0; color:var(--text-secondary);">
                    • Step {fc.get('step', '?')}: <strong style="color:var(--fail)">{fc.get('reason', 'Unknown')}</strong>
                </p>
"""

        html += """            </div>
        </div>
"""
        return html

    def _escape_html(self, text: str) -> str:
        """转义 HTML 特殊字符"""
        if not isinstance(text, str):
            text = str(text)
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))

    def _generate_json(
        self,
        results: List[Any],
        run_id: str,
        agent_name: str,
        agent_version: str,
        output_path: Optional[str] = None,
    ) -> str:
        """生成 JSON 报告"""
        if output_path is None:
            output_path = self.report_dir / f"report_{run_id}.json"
        else:
            output_path = Path(output_path)

        passed = sum(1 for r in results if r.success)
        data = {
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "agent": {"name": agent_name, "version": agent_version},
            "summary": {
                "total": len(results),
                "passed": passed,
                "failed": len(results) - passed,
                "pass_rate": passed / len(results) if results else 0,
                "safety_issues": sum(len(r.safety_violations) for r in results),
            },
            "results": [r.to_dict() for r in results],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return str(output_path)

    def _generate_markdown(
        self,
        results: List[Any],
        run_id: str,
        agent_name: str,
        agent_version: str,
        output_path: Optional[str] = None,
    ) -> str:
        """生成 Markdown 报告"""
        if output_path is None:
            output_path = self.report_dir / f"report_{run_id}.md"
        else:
            output_path = Path(output_path)

        passed = sum(1 for r in results if r.success)
        failed = len(results) - passed
        safety_issues = sum(len(r.safety_violations) for r in results)

        lines = [
            f"# AegisTest Report",
            "",
            f"- **Run ID**: {run_id}",
            f"- **Agent**: {agent_name} v{agent_version}",
            f"- **Time**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total | {len(results)} |",
            f"| Passed | {passed} |",
            f"| Failed | {failed} |",
            f"| Pass Rate | {passed / len(results) * 100 if results else 0:.1f}% |",
            f"| Safety Issues | {safety_issues} |",
            "",
            "## Results",
            "",
            "| Test ID | Status | Category | Latency | Steps | Safety |",
            "|---------|--------|----------|---------|-------|--------|",
        ]

        for r in results:
            status = "PASS" if r.success else "FAIL"
            safety = len(r.safety_violations) if r.safety_violations else 0
            lines.append(
                f"| {r.test_id} | {status} | {r.failure_category or '-'} | "
                f"{r.latency_ms:.0f}ms | {r.steps_used} | {safety} |"
            )

        lines.append("")
        lines.append("## Failed Details")
        lines.append("")

        failed = [r for r in results if not r.success]
        if not failed:
            lines.append("*All tests passed.*")
        else:
            for r in failed:
                lines.append(f"### {r.test_id}")
                lines.append(f"- **Category**: {r.failure_category or '-'}")
                lines.append(f"- **Reason**: {r.failure_reason or '-'}")
                lines.append(f"- **Output**:")
                lines.append(f"```")
                lines.append(r.agent_output[:500])
                lines.append(f"```")
                lines.append("")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return str(output_path)
