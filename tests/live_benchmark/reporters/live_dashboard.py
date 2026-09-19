# Copyright 2026 Mahendra GURAV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
High-Fidelity Live Benchmark Dashboard Reporter.

Adheres strictly to GEES v1.0 (Pillar 2, Engine B).
Renders interactive HTML reports and machine-readable JSON summaries
recording safety pass rates, functional pass rates, and latencies.
"""

import html
import json
import os
from pathlib import Path
from typing import Any, Dict, List


class LiveBenchmarkDashboardReporter:
    """Generates dual-format reports (HTML & JSON) for live benchmarks."""

    @staticmethod
    def write_json_summary(summary: Dict[str, Any], output_path: str) -> None:
        """Write benchmark results summary to JSON file.

        Args:
            summary: Summary dictionary containing KPIs and scenario results.
            output_path: Target filesystem path for the JSON file.
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

    @staticmethod
    def generate_html_report(
        scenario_results: List[Dict[str, Any]],
        summary: Dict[str, Any],
        output_path: str,
    ) -> None:
        """Render self-contained HTML benchmark inspection dashboard.

        Args:
            scenario_results: List of scenario evaluation result dictionaries.
            summary: Summary statistics dictionary.
            output_path: Target path for the HTML file.
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        total = summary.get("total_scenarios", 0)
        passed = summary.get("passed_scenarios", 0)
        failed = summary.get("failed_scenarios", 0)
        functional_rate = summary.get("functional_pass_rate_pct", 0.0)
        safety_rate = summary.get("safety_pass_rate_pct", 0.0)
        quality_gate_passed = summary.get("quality_gate_passed", False)
        duration_sec = summary.get("duration_seconds", 0.0)

        # Quality gate badge
        qg_badge = (
            '<span class="badge badge-success" style="font-size: 14px; padding: 6px 14px;">QUALITY GATE PASSED (100% SAFETY)</span>'
            if quality_gate_passed
            else '<span class="badge badge-danger" style="font-size: 14px; padding: 6px 14px;">QUALITY GATE FAILED</span>'
        )

        rows_html = []
        for r in scenario_results:
            is_pass = r.get("passed", False)
            status_badge = (
                '<span class="badge badge-success">PASSED</span>'
                if is_pass
                else '<span class="badge badge-danger">FAILED</span>'
            )
            is_safety = r.get("is_safety_critical", False)
            safety_badge = (
                '<span class="badge badge-danger">HARD SAFETY</span>'
                if is_safety
                else '<span class="badge badge-info">FUNCTIONAL</span>'
            )

            latency_ms = r.get("latency_ms", 0.0)
            failure_reason = r.get("failure_reason", "")
            reason_html = f"<div style='color: #ef4444; font-size: 11px;'>{html.escape(failure_reason)}</div>" if failure_reason else ""

            row = f"""
            <tr>
              <td><strong>{html.escape(r.get('id', ''))}</strong></td>
              <td>
                <div style="font-weight: 600;">{html.escape(r.get('name', ''))}</div>
                <div style="color: var(--text-muted); font-size: 11px;">{html.escape(r.get('description', ''))}</div>
                {reason_html}
              </td>
              <td>{safety_badge}</td>
              <td><code>{latency_ms:.1f} ms</code></td>
              <td>{status_badge}</td>
            </tr>
            """
            rows_html.append(row)

        table_rows = "\n".join(rows_html)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Release100 Live Benchmark Dashboard</title>
  <style>
    :root {{
      --bg: #0b0f19;
      --card-bg: #111827;
      --card-border: #1f2937;
      --text: #f9fafb;
      --text-muted: #9ca3af;
      --emerald: #10b981;
      --amber: #f59e0b;
      --crimson: #ef4444;
      --blue: #3b82f6;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 32px;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 24px;
      margin-bottom: 32px;
    }}
    .header h1 {{ margin: 0; font-size: 24px; font-weight: 700; }}
    .header p {{ margin: 6px 0 0 0; color: var(--text-muted); font-size: 14px; }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 32px;
    }}
    .stat-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 20px;
    }}
    .stat-label {{ color: var(--text-muted); font-size: 13px; font-weight: 500; }}
    .stat-val {{ font-size: 32px; font-weight: 800; margin-top: 6px; }}
    .badge {{
      display: inline-block;
      padding: 3px 10px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.5px;
    }}
    .badge-success {{ background: rgba(16, 185, 129, 0.15); color: var(--emerald); border: 1px solid var(--emerald); }}
    .badge-warning {{ background: rgba(245, 158, 11, 0.15); color: var(--amber); border: 1px solid var(--amber); }}
    .badge-danger {{ background: rgba(239, 68, 68, 0.15); color: var(--crimson); border: 1px solid var(--crimson); }}
    .badge-info {{ background: rgba(59, 130, 246, 0.15); color: var(--blue); border: 1px solid var(--blue); }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      overflow: hidden;
      font-size: 13px;
    }}
    th, td {{
      padding: 14px 18px;
      text-align: left;
      border-bottom: 1px solid var(--card-border);
    }}
    th {{ background: #030712; color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px; }}
    tr:hover {{ background: rgba(255, 255, 255, 0.02); }}
    code {{ background: #030712; padding: 3px 8px; border-radius: 4px; font-size: 12px; color: #38bdf8; }}
  </style>
</head>
<body>
  <div class="header">
    <div>
      <h1>Release100 High-Fidelity Live Benchmark Dashboard</h1>
      <p>Dual-Engine Verification Regime (GEES v1.0 Pillar 2) &bull; Execution Duration: {duration_sec:.2f}s</p>
    </div>
    <div>
      {qg_badge}
    </div>
  </div>

  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">Hard Safety Pass Rate</div>
      <div class="stat-val" style="color: {'var(--emerald)' if safety_rate == 100.0 else 'var(--crimson)'};">{safety_rate:.1f}%</div>
      <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">Mandatory: 100.0%</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Functional Pass Rate</div>
      <div class="stat-val" style="color: {'var(--emerald)' if functional_rate >= 80.0 else 'var(--amber)'};">{functional_rate:.1f}%</div>
      <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">Standard: &ge; 80.0%</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Total Scenarios Evaluated</div>
      <div class="stat-val">{total}</div>
      <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">{passed} Passed &bull; {failed} Failed</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Total Benchmark Runtime</div>
      <div class="stat-val" style="color: var(--blue);">{duration_sec:.2f}s</div>
      <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">Sub-second evaluation</div>
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th>Scenario ID</th>
        <th>Scenario Name & Description</th>
        <th>Classification</th>
        <th>Latency</th>
        <th>Verdict</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>
</body>
</html>
"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
