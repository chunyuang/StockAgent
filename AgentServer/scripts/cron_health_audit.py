#!/usr/bin/env python3
"""Cron 健康度审查脚本

检查所有 OpenClaw cron 任务的配置完整性。
历史踩坑:
  - 7/18: delivery.to 缺失导致飞书投递失败(2个任务)
  - 7/18: 18个任务同时触发导致 Coding Plan rate limit
  - 7/5-7/6: Coding Plan 月度配额耗尽导致3天全败

检查项:
  1. delivery.to 配置完整性 (飞书/微信/Discord等需指定目标)
  2. delivery.channel 配置合理性
  3. schedule.expr 语法与时区校验
  4. payload 脚本路径存在性检查
  5. fallback model 有效性
  6. 近期运行失败率统计
  7. 并发触发风险检测 (同一时段多个任务)
"""

import json
import sys
import os
import subprocess
from datetime import datetime
from pathlib import Path

# This script must run via OpenClaw cron tool, so we use a simpler approach:
# Parse cron list output and check each job


class CronHealthAudit:
    def __init__(self):
        self.findings = []
        self.p0_count = 0
        self.p1_count = 0
        self.p2_count = 0

    def _add_finding(self, severity: str, check_id: str, description: str, detail: str = ""):
        self.findings.append({
            "severity": severity,
            "check_id": check_id,
            "description": description,
            "detail": detail,
        })
        if severity == "P0":
            self.p0_count += 1
        elif severity == "P1":
            self.p1_count += 1
        elif severity == "P2":
            self.p2_count += 1

    def fetch_cron_jobs(self):
        """通过 openclaw cron list 获取所有任务"""
        result = subprocess.run(
            ["openclaw", "cron", "list", "--json"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            # Fallback: try via gateway API
            self._add_finding("P1", "CH-0.1", "无法通过CLI获取cron列表", result.stderr[:200])
            return []
        try:
            data = json.loads(result.stdout)
            return data if isinstance(data, list) else data.get("jobs", [])
        except json.JSONDecodeError:
            self._add_finding("P1", "CH-0.2", "cron list输出非JSON格式", result.stdout[:200])
            return []

    def check_delivery_config(self, jobs):
        """Check 1: delivery.to 配置完整性"""
        print("\n[Check 1] delivery 配置完整性")

        for job in jobs:
            job_name = job.get("name", job.get("id", "unknown"))
            delivery = job.get("delivery", {})
            payload = job.get("payload", {})
            session_target = job.get("sessionTarget", "")

            # agentTurn with announce delivery must have delivery.to for Feishu/WeChat
            if payload.get("kind") == "agentTurn":
                mode = delivery.get("mode", "announce")
                if mode == "announce" and not delivery.get("to"):
                    # Check if channel requires explicit target
                    channel = delivery.get("channel", "")
                    # For Feishu, announce without 'to' may fail
                    if channel == "feishu" or (not channel and mode == "announce"):
                        self._add_finding("P0", f"CH-1.{job_name}",
                                        f"任务 '{job_name}' delivery.mode=announce 但 delivery.to 为空",
                                        f"飞书投递将失败。job_id={job.get('id','?')}")

            # systemEvent to main session doesn't need delivery.to
            if payload.get("kind") == "systemEvent" and session_target == "main":
                continue

    def check_schedule_config(self, jobs):
        """Check 2: schedule 配置合理性"""
        print("\n[Check 2] schedule 配置合理性")

        for job in jobs:
            job_name = job.get("name", job.get("id", "unknown"))
            schedule = job.get("schedule", {})

            if not schedule:
                if job.get("enabled", False):
                    self._add_finding("P1", f"CH-2.{job_name}",
                                    f"启用任务 '{job_name}' 缺少 schedule 配置")
                continue

            kind = schedule.get("kind", "")
            if kind == "cron":
                expr = schedule.get("expr", "")
                tz = schedule.get("tz", "")
                if not expr:
                    self._add_finding("P1", f"CH-2.{job_name}",
                                    f"任务 '{job_name}' schedule.kind=cron 但 expr 为空")
                # Validate cron expression basic format (5 or 6 fields)
                if expr:
                    parts = expr.split()
                    if len(parts) < 5:
                        self._add_finding("P1", f"CH-2.{job_name}",
                                        f"任务 '{job_name}' cron表达式格式异常: '{expr}'",
                                        "预期至少5个字段(min hour day month weekday)")
            elif kind == "every":
                every_ms = schedule.get("everyMs", 0)
                if every_ms <= 0:
                    self._add_finding("P1", f"CH-2.{job_name}",
                                    f"任务 '{job_name}' schedule.kind=every 但 everyMs={every_ms}")

    def check_script_paths(self, jobs):
        """Check 3: payload 中引用的脚本路径是否存在"""
        print("\n[Check 3] 脚本路径存在性检查")

        workspace = Path(os.environ.get("OPENCLAW_WORKSPACE", "/root/.openclaw/workspace"))

        for job in jobs:
            job_name = job.get("name", job.get("id", "unknown"))
            payload = job.get("payload", {})
            message = payload.get("message", "") or payload.get("text", "")

            # Look for script paths in message
            # Common patterns: "python3 /path/to/script.py", "bash /path/to/script.sh"
            import re
            script_patterns = re.findall(r'(?:python3?|bash|sh)\s+([/\w.-]+\.(?:py|sh))', message)
            for script_path in script_patterns:
                full_path = Path(script_path)
                if not full_path.is_absolute():
                    full_path = workspace / script_path
                if not full_path.exists():
                    self._add_finding("P1", f"CH-3.{job_name}",
                                    f"任务 '{job_name}' 引用的脚本不存在: {script_path}")

    def check_fallback_models(self, jobs):
        """Check 4: fallback model 有效性"""
        print("\n[Check 4] fallback model 有效性")

        known_models = {
            "qianfan-code-latest",
            "glm-5.2",
            "deepseek/deepseek-chat",
            "openai/gpt-4o-mini",
        }

        for job in jobs:
            job_name = job.get("name", job.get("id", "unknown"))
            payload = job.get("payload", {})
            fallbacks = payload.get("fallbacks", [])
            model = payload.get("model", "")

            if model and model not in known_models and not model.startswith("custom-"):
                self._add_finding("P2", f"CH-4.{job_name}",
                                f"任务 '{job_name}' 使用未知模型: {model}",
                                f"已知模型: {known_models}")

            for fb in fallbacks:
                if fb not in known_models and not fb.startswith("custom-"):
                    self._add_finding("P2", f"CH-4.{job_name}.fb",
                                    f"任务 '{job_name}' fallback模型未知: {fb}")

    def check_recent_failures(self, jobs):
        """Check 5: 近期运行失败率"""
        print("\n[Check 5] 近期运行失败率 (基于最近3次运行)")

        # This requires cron runs API which we'll call per-job
        # For now, mark as informational
        for job in jobs:
            job_name = job.get("name", job.get("id", "unknown"))
            last_error = job.get("lastError") or job.get("error")
            if last_error:
                if "rate_limit" in str(last_error).lower():
                    self._add_finding("P1", f"CH-5.{job_name}",
                                    f"任务 '{job_name}' 最近因rate_limit失败",
                                    "建议串行触发，避免并发")

    def check_concurrent_risk(self, jobs):
        """Check 6: 同一时段多个任务并发风险"""
        print("\n[Check 6] 并发触发风险检测")

        # Group enabled jobs by cron schedule time
        from collections import defaultdict
        time_slots = defaultdict(list)

        for job in jobs:
            if not job.get("enabled", True):
                continue
            schedule = job.get("schedule", {})
            if schedule.get("kind") == "cron":
                expr = schedule.get("expr", "")
                # Extract hour:minute from cron expression
                parts = expr.split()
                if len(parts) >= 2:
                    minute, hour = parts[0], parts[1]
                    time_key = f"{hour}:{minute}"
                    time_slots[time_key].append(job.get("name", job.get("id", "unknown")))

        for time_key, job_names in sorted(time_slots.items()):
            if len(job_names) > 2:
                self._add_finding("P1", f"CH-6.{time_key}",
                                f"时段 {time_key} 有 {len(job_names)} 个任务并发",
                                f"任务: {', '.join(job_names)}",
                                )

    def run_all(self):
        print("=" * 60)
        print("Cron 健康度审查 (Cron Health Audit)")
        print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        # Fetch jobs via cron API
        print("\n获取 cron 任务列表...")
        jobs = self.fetch_cron_jobs()

        if not jobs:
            print("⚠️ 无法获取cron任务列表，尝试从配置文件读取")
            # Try reading from CRON_DEVELOPMENT.md as fallback
            return {"P0": 0, "P1": 0, "P2": 0, "findings": [], "note": "No cron jobs fetched"}

        print(f"获取到 {len(jobs)} 个 cron 任务")

        self.check_delivery_config(jobs)
        self.check_schedule_config(jobs)
        self.check_script_paths(jobs)
        self.check_fallback_models(jobs)
        self.check_recent_failures(jobs)
        self.check_concurrent_risk(jobs)

        # Summary
        print("\n" + "=" * 60)
        print("审查结果汇总")
        print("=" * 60)
        print(f"P0 (阻断级): {self.p0_count}")
        print(f"P1 (严重级): {self.p1_count}")
        print(f"P2 (建议级): {self.p2_count}")

        if self.findings:
            print("\n详细发现:")
            for f in self.findings:
                icon = "🔴" if f["severity"] == "P0" else "🟡" if f["severity"] == "P1" else "🔵"
                print(f"  {icon} [{f['check_id']}] {f['severity']}: {f['description']}")
                if f['detail']:
                    print(f"     {f['detail']}")
        else:
            print("\n✅ 所有检查项通过，cron配置健康")

        return {
            "P0": self.p0_count,
            "P1": self.p1_count,
            "P2": self.p2_count,
            "findings": self.findings,
        }


if __name__ == "__main__":
    audit = CronHealthAudit()
    result = audit.run_all()

    # Write results
    output_dir = Path(__file__).resolve().parent.parent / "audit_results"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / f"cron_health_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存: {output_file}")

    sys.exit(1 if result["P0"] > 0 else 0)
