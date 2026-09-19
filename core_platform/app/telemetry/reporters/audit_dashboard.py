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
Visual HTML Audit Dashboard Reporter.

Generates self-contained, interactive HTML reports for plant managers,
floor supervisors, and regulatory compliance audits (FDA 21 CFR Part 11 / ISO 22000).
"""

import html
import json
import os
from typing import List

from core_platform.app.telemetry.audit_schema import AuditRecord


class AuditDashboardReporter:
    """Generates visual, partitioned HTML audit inspection dashboards."""

    @staticmethod
    def generate_html_report(records: List[AuditRecord], output_path: str, partition_label: str = "Live") -> None:
        """Render self-contained HTML report from audit records.

        Args:
            records: List of AuditRecord objects in the partition.
            output_path: Target filesystem path to write the HTML file.
            partition_label: Label for the partition (e.g., date or partition number).
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        total_records = len(records)
        passed_records = sum(1 for r in records if r.layer_2_gate_status in ["APPROVED", "SIMULATED_SHADOW"])
        review_records = sum(1 for r in records if r.layer_2_gate_status == "DIVERTED_TO_REVIEW")
        violation_records = sum(1 for r in records if r.layer_0_status == "VIOLATION")

        rows_html = []
        for r in records:
            # Color-coded badge for Layer 2 status
            if r.layer_2_gate_status == "APPROVED":
                gate_badge = '<span class="badge badge-success">APPROVED</span>'
            elif r.layer_2_gate_status == "SIMULATED_SHADOW":
                gate_badge = '<span class="badge badge-info">SHADOW</span>'
            else:
                gate_badge = '<span class="badge badge-warning">REVIEW</span>'

            # Color-coded badge for Layer 0 status
            layer0_badge = (
                '<span class="badge badge-success">PASS</span>'
                if r.layer_0_status == "PASSED"
                else '<span class="badge badge-danger">VIOLATION</span>'
            )

            payload_str = html.escape(json.dumps(r.payload_summary, indent=2))
            hash_short = f"{r.record_hash[:10]}...{r.record_hash[-8:]}" if r.record_hash else "GENESIS"

            row = f"""
            <tr>
              <td><strong>#{r.sequence_number}</strong></td>
              <td><small>{html.escape(r.timestamp_utc)}</small></td>
              <td><code>{html.escape(r.kiosk_id)}</code></td>
              <td>{html.escape(r.operator_id)}</td>
              <td><strong>{html.escape(r.action_type)}</strong></td>
              <td>{layer0_badge}</td>
              <td><small>{html.escape(r.layer_1_model)} ({r.layer_1_confidence * 100:.0f}%)</small></td>
              <td>{gate_badge}</td>
              <td><details><summary>View Data</summary><pre>{payload_str}</pre></details></td>
              <td><code title="{html.escape(r.record_hash)}">{hash_short}</code></td>
            </tr>
            """
            rows_html.append(row)

        table_body = "\n".join(rows_html)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Release100 Compliance Audit Report — {html.escape(partition_label)}</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --border: #334155;
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
      padding: 24px;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
      padding-bottom: 16px;
      margin-bottom: 24px;
    }}
    .header h1 {{ margin: 0; font-size: 22px; color: #fff; }}
    .header p {{ margin: 4px 0 0 0; color: var(--text-muted); font-size: 13px; }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .stat-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }}
    .stat-val {{ font-size: 28px; font-weight: bold; margin-top: 4px; }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
    }}
    .badge-success {{ background: rgba(16, 185, 129, 0.2); color: var(--emerald); border: 1px solid var(--emerald); }}
    .badge-warning {{ background: rgba(245, 158, 11, 0.2); color: var(--amber); border: 1px solid var(--amber); }}
    .badge-danger {{ background: rgba(239, 68, 68, 0.2); color: var(--crimson); border: 1px solid var(--crimson); }}
    .badge-info {{ background: rgba(59, 130, 246, 0.2); color: var(--blue); border: 1px solid var(--blue); }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      font-size: 13px;
    }}
    th, td {{
      padding: 12px 14px;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }}
    th {{ background: #111827; color: var(--text-muted); font-weight: 600; }}
    tr:hover {{ background: rgba(255, 255, 255, 0.02); }}
    code {{ background: #0b1120; padding: 2px 6px; border-radius: 4px; font-size: 11px; color: #38bdf8; }}
    pre {{ background: #0b1120; padding: 8px; border-radius: 4px; font-size: 11px; max-width: 280px; overflow-x: auto; color: #a5f3fc; }}
  </style>
</head>
<body>
  <div class="header">
    <div>
      <h1>Release100 Regulatory Compliance Audit Ledger</h1>
      <p>FDA 21 CFR Part 11 / ISO 22000 Cryptographic Non-Repudiation Trail &bull; Partition: {html.escape(partition_label)}</p>
    </div>
    <div style="text-align: right;">
      <span class="badge badge-success">SHA-256 Chained</span>
    </div>
  </div>

  <div class="stats-grid">
    <div class="stat-card">
      <div style="color: var(--text-muted); font-size: 12px;">Total Transactions</div>
      <div class="stat-val">{total_records}</div>
    </div>
    <div class="stat-card">
      <div style="color: var(--emerald); font-size: 12px;">Approved / Shadow</div>
      <div class="stat-val" style="color: var(--emerald);">{passed_records}</div>
    </div>
    <div class="stat-card">
      <div style="color: var(--amber); font-size: 12px;">Diverted to Review</div>
      <div class="stat-val" style="color: var(--amber);">{review_records}</div>
    </div>
    <div class="stat-card">
      <div style="color: var(--crimson); font-size: 12px;">Layer 0 Violations</div>
      <div class="stat-val" style="color: var(--crimson);">{violation_records}</div>
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th>Seq</th>
        <th>Timestamp (UTC)</th>
        <th>Kiosk ID</th>
        <th>Operator</th>
        <th>Action</th>
        <th>Layer 0 Pre</th>
        <th>Layer 1 AI</th>
        <th>Layer 2 Gate</th>
        <th>Payload</th>
        <th>SHA-256 Hash</th>
      </tr>
    </thead>
    <tbody>
      {table_body}
    </tbody>
  </table>
</body>
</html>
"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
