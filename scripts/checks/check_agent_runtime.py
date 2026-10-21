"""Opt-in real invocation check. Stops on first failure/unverified metadata.

This can consume model tokens; it does not count toward ten business tasks.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
ROLES = {'sol-low': 'backend', 'sol-medium': 'important_acceptance',
         'sol-high': 'architect', 'luna-medium': 'acceptance', 'luna-high': 'simple_task'}
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--profile', choices=ROLES, default='sol-low')
parser.add_argument('--all', action='store_true')
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix='geo-model-check-') as tmp:
    brief = Path(tmp) / 'brief.md'
    brief.write_text('任务ID：runtime-check。目标：只回复OK。必要背景：运行器调用核验，不是业务任务。'
                     '相关文件：无。允许修改范围：无。接口约束：不调用工具，不启动子agent。'
                     '验收标准：由真实运行日志核对模型与深度。已知问题：不要自述模型冒充日志。')
    for profile in ROLES if args.all else [args.profile]:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/agents/run.py'),
            '--role', ROLES[profile], '--profile', profile, '--task-id', 'runtime-' + profile,
            '--brief', str(brief), '--kind', 'runtime-check'], cwd=ROOT)
        if result.returncode:
            print('Stopped: fix the engine or missing runtime metadata before further paid checks.')
            raise SystemExit(result.returncode)
