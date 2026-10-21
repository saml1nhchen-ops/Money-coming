"""Summarize real runner records; missing cost stays unknown, never estimated."""
import json
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[2]
rows = [json.loads(p.read_text()) for p in (root / 'runtime/agent-execution').glob('*/summary.json')]
tasks = [r for r in rows if r.get('kind') == 'task' and r.get('engine_exit_code') == 0]
ids = {r['task_id'] for r in tasks}
attempts = Counter((r['task_id'], r['role']) for r in rows if r.get('kind') == 'task')
costs = [r.get('cost_usd') for r in rows]
reworked = {r['task_id'] for r in tasks if r.get('rework')}
print(json.dumps({
    'calibration_target': 10, 'completed_task_ids': sorted(ids), 'completed_count': len(ids),
    'runtime_checks_excluded': sum(r.get('kind') == 'runtime-check' for r in rows),
    'verified_execution_count': sum(r.get('actual_model_verified') is True for r in tasks),
    'retries': sum(max(0, n - 1) for n in attempts.values()),
    'explicitly_marked_reworked_tasks': len(reworked),
    'rework_rate': len(reworked) / len(ids) if ids else None,
    'rework_rate_note': 'Only explicit --rework flags; omissions are not proof of no rework',
    'actual_cost_usd': sum(costs) if costs and all(isinstance(v, (int, float)) for v in costs) else None,
    'cost_note': 'Unknown until trusted billed cost is supplied; token counts are not prices',
    'model_verified_note': 'Runtime-reported metadata match, not upstream model internals',
}, ensure_ascii=False, indent=2))
