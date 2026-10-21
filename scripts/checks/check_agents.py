"""Offline checks of routing, concurrency gates and metadata verification.

These are controlled checks, never evidence of an actual model invocation.
"""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[2]
policy = json.loads((ROOT / '.starwork/agent-policy.json').read_text())
expected = {'sol-low': ('gpt-6.1-sol', 'low'), 'sol-medium': ('gpt-6.1-sol', 'medium'),
            'sol-high': ('gpt-6.1-sol', 'high'), 'luna-medium': ('gpt-6-luna', 'medium'),
            'luna-high': ('gpt-6-luna', 'high')}
assert set(policy['profiles']) == set(expected)
assert len(policy['roles']) == 11 and 'controller' not in policy['roles']
registry = (ROOT / '_系统/协作/agent-lanes.md').read_text()
assert '## Lanes\n' in registry
for role in policy['roles']:
    assert '| ' + role + ' |' in registry
    assert (ROOT / '_系统/协作/lanes' / role / 'launch.md').is_file()
config = tomllib.loads((ROOT / '.codex/config.toml').read_text())
assert (config['model'], config['model_reasoning_effort']) == expected['sol-low']
assert config['agents']['max_concurrent_threads_per_session'] == 2
for name, pair in expected.items():
    layer = tomllib.loads((ROOT / policy['profiles'][name]).read_text())
    assert (layer['model'], layer['model_reasoning_effort']) == pair
for role, data in policy['roles'].items():
    assert config['agents'][role]['config_file'] == 'agents/' + data['profile'] + '.toml'
assert policy['roles']['backend']['profile'] == 'sol-low'
assert policy['roles']['architect']['profile'] == 'sol-high'
assert policy['roles']['important_acceptance']['profile'] == 'sol-medium'
spec = importlib.util.spec_from_file_location('agent_runner', ROOT / 'scripts/agents/run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
with tempfile.TemporaryDirectory() as tmp:
    runner.STATE = Path(tmp)
    db = runner.database()
    runner.reserve(db, 'one', 'sol-low', 'TEST', 'frontend', 'sol-low')
    runner.reserve(db, 'two', 'luna-high', 'TEST', 'simple_task', 'sol-low')
    try:
        runner.reserve(db, 'three', 'sol-low', 'TEST', 'backend', 'sol-low')
    except ValueError:
        pass
    else:
        raise AssertionError('Worker cap not enforced')
    db.execute('DELETE FROM runs'); db.commit()
    runner.reserve(db, 'frontend', 'sol-low', 'TEST', 'frontend', 'sol-low', True)
    try:
        runner.reserve(db, 'backend', 'sol-low', 'TEST', 'backend', 'sol-low', True)
    except ValueError:
        pass
    else:
        raise AssertionError('Coordinating chat implementation slot ignored')
    db.execute('DELETE FROM runs'); db.commit()
    runner.reserve(db, 'high-one', 'sol-high', 'TEST', 'architect', 'sol-low')
    for controller in ['sol-low', 'sol-high']:
        try:
            runner.reserve(db, 'high-two', 'sol-high', 'TEST', 'complex_bug', controller)
        except ValueError:
            pass
        else:
            raise AssertionError('Sol-high cap not enforced')
    db.execute('DELETE FROM runs'); db.commit()
    try:
        runner.reserve(db, 'root-high', 'sol-high', 'TEST', 'architect', 'sol-high')
    except ValueError:
        pass
    else:
        raise AssertionError('Coordinating chat Sol-high ignored')
    db.close()
    events = Path(tmp) / 'events.jsonl'
    events.write_text(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message',
                      'text': 'I am gpt-6.1-sol high'}}) + '\n')
    assert runner.observations(events)['models'] == []
    events.write_text(json.dumps({'type': 'turn_context', 'payload':
                      {'model': 'gpt-6-luna', 'effort': 'medium'}}) + '\n')
    assert runner.observations(events)['models'] == ['gpt-6-luna']
    assert runner.observations(events)['reasoning_efforts'] == ['medium']
try:
    runner.resolve('backend', 'sol-high')
except ValueError:
    pass
else:
    raise AssertionError('Role/profile mismatch accepted')
print('PASS: five layers, eleven specialist roles, worker/high caps, metadata/prose distinction and escalation mapping (offline controlled checks).')
