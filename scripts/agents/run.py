"""Launch one scoped Codex task using the project's five execution layers.

No provider credentials, model names or prices are invented. Raw runtime logs
stay in ignored runtime/agent-execution. This gate covers its own launches only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import tomllib
import uuid

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / '.starwork/agent-policy.json'
STATE = ROOT / 'runtime/agent-execution'
IMPLEMENTERS = {'frontend', 'backend', 'simple_task', 'simple_bug', 'complex_bug', 'data_maintenance', 'data_repair'}


def resolve(role, profile=None):
    policy = json.loads(POLICY.read_text())
    selected = profile or policy['roles'][role]['profile']
    if selected != policy['roles'][role]['profile']:
        raise ValueError('Use the matching role when escalating; role/profile mismatch')
    config = tomllib.loads((ROOT / policy['profiles'][selected]).read_text())
    return selected, config


def database():
    STATE.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STATE / 'runs.sqlite', timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,pid INTEGER,profile TEXT,status TEXT,task TEXT,role TEXT)')
    return db


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def reserve(db, run_id, profile, task, role, coordinator_profile, coordinator_implementing=False):
    db.execute('BEGIN IMMEDIATE')
    for previous, pid in db.execute("SELECT id,pid FROM runs WHERE status='running'").fetchall():
        if not alive(pid):
            db.execute("UPDATE runs SET status='interrupted' WHERE id=?", (previous,))
    active = db.execute("SELECT profile,role FROM runs WHERE status='running'").fetchall()
    if len(active) >= 2:
        db.rollback()
        raise ValueError('Two workers already active; coordinating chat + workers must stay <= 3')
    if profile == 'sol-high' and (coordinator_profile == 'sol-high' or any(p[0] == 'sol-high' for p in active)):
        db.rollback()
        raise ValueError('Only one Sol-high may run, including the declared coordinating chat')
    implementers = sum(row[1] in IMPLEMENTERS for row in active) + int(coordinator_implementing)
    if role in IMPLEMENTERS and implementers >= 2:
        db.rollback()
        raise ValueError('Only two parallel implementers, including the coordinating chat when it edits')
    db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?)', (run_id, os.getpid(), profile, 'running', task, role))
    db.commit()


def observations(path):
    """Only runtime metadata counts; assistant prose/config echoes never count."""
    models, efforts, usage = set(), set(), {}
    for line in path.read_text(errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get('type')
        # These envelopes must be emitted by the runtime, not assistant text.
        if kind in ('session_meta', 'turn_context', 'session.started'):
            payload = event.get('payload', event)
            if isinstance(payload, dict):
                if isinstance(payload.get('model'), str):
                    models.add(payload['model'])
                effort = payload.get('reasoning_effort', payload.get('effort'))
                if isinstance(effort, str):
                    efforts.add(effort)
        if kind == 'turn.completed' and isinstance(event.get('usage'), dict):
            usage = {k: v for k, v in event['usage'].items()
                     if k in ('input_tokens', 'cached_input_tokens', 'output_tokens') and isinstance(v, (int, float))}
    return {'models': sorted(models), 'reasoning_efforts': sorted(efforts), 'usage': usage}


def main():
    policy = json.loads(POLICY.read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=policy['roles'], required=True)
    parser.add_argument('--profile', choices=policy['profiles'])
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--brief', type=Path, required=True)
    parser.add_argument('--coordinator-profile', choices=policy['profiles'], default='sol-low')
    parser.add_argument('--coordinator-implementing', action='store_true')
    parser.add_argument('--kind', choices=['task', 'runtime-check'], default='task')
    parser.add_argument('--rework', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    profile, config = resolve(args.role, args.profile)
    brief = args.brief.read_text()
    if len(brief) > 12000:
        parser.error('Brief exceeds 12,000 characters; provide a summary and paths')
    command = [shutil.which('codex') or 'codex', 'exec', '--ephemeral', '--json', '--strict-config',
               '-s', 'workspace-write', '-m', config['model'],
               '-c', 'model_reasoning_effort=' + json.dumps(config['model_reasoning_effort']),
               '-c', 'agents.enabled=false', '-']
    if args.dry_run:
        print(json.dumps({'role': args.role, 'profile': profile, 'command': command,
                          'actual_model_verified': False}, ensure_ascii=False))
        return 0
    run_id = str(uuid.uuid4())
    db = database()
    try:
        reserve(db, run_id, profile, args.task_id, args.role, args.coordinator_profile, args.coordinator_implementing)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    folder = STATE / run_id
    folder.mkdir()
    started = time.time()
    record = {'id': run_id, 'task_id': args.task_id, 'kind': args.kind, 'role': args.role,
              'profile': profile, 'requested_model': config['model'],
              'requested_effort': config['model_reasoning_effort'],
              'coordinator_profile_declared': args.coordinator_profile,
              'coordinator_implementing_declared': args.coordinator_implementing,
              'brief_sha256': hashlib.sha256(brief.encode()).hexdigest(),
              'rework': args.rework, 'cost_usd': None,
              'cost_note': 'Unknown: requires a provider bill or trusted runtime cost metadata'}
    exit_code, status = 1, 'failed'
    try:
        prompt = ('任务角色：' + args.role + '\n任务ID：' + args.task_id +
                  '\n只读必要背景，禁止再启动子agent。不要输出任何密钥。\n' + brief)
        with (folder / 'events.jsonl').open('w') as out, (folder / 'stderr.log').open('w') as err:
            result = subprocess.run(command, input=prompt, text=True, cwd=ROOT, stdout=out, stderr=err)
        observed = observations(folder / 'events.jsonl')
        verified = observed['models'] == [config['model']] and observed['reasoning_efforts'] == [config['model_reasoning_effort']]
        status = 'runtime_failed' if result.returncode else 'runtime_reported_match' if verified else 'unverified'
        record.update(observed=observed, engine_exit_code=result.returncode,
                      actual_model_verified=verified,
                      evidence_scope='Runtime metadata only; not proof of upstream provider internals')
        exit_code = result.returncode if result.returncode else 0 if verified else 3
    except (OSError, KeyboardInterrupt) as error:
        record.update(actual_model_verified=False, error_type=type(error).__name__)
    finally:
        record.update(status=status, started_at=started, duration_seconds=round(time.time() - started, 3))
        (folder / 'summary.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
        db.execute('UPDATE runs SET status=? WHERE id=?', (status, run_id))
        db.commit()
        db.close()
    print(json.dumps({'status': status, 'actual_model_verified': record.get('actual_model_verified'),
                      'evidence': str(folder / 'summary.json')}, ensure_ascii=False))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
