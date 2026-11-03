"""Local quota accounting. Contains platform/model identities and token counts only."""
import argparse
import datetime
import json
import os
import pathlib
import tempfile
import threading

LOCK = threading.RLock()
DEFAULT_PATH = pathlib.Path(__file__).resolve().parents[1]/'runtime/route-ledger.json'
KNOWN = {'tokenhub/deepseek-v4-flash-202605':63832, 'tokenhub/glm-5.3-flash':70403,
         'tokenhub/kimi-k3.1-pro':13021, 'bailian/qwen3.8-flash':84385}


def path():
    value = os.getenv('SIGNAL_ROUTE_LEDGER', '')
    return None if value.lower() == 'off' else pathlib.Path(value) if value else DEFAULT_PATH


def key(route):
    return route.get('route_platform', route.get('route', 'official'))+'/'+route['model']


def read():
    target = path()
    if target is None: return {}
    try: return json.loads(target.read_text('utf-8'))
    except FileNotFoundError: return {}


def update(identity, tokens, *, seed=False):
    target = path()
    if target is None: return
    with LOCK:
        data = read()
        row = data.setdefault(identity, {'tokens':0})
        row['tokens'] = max(row['tokens'], tokens) if seed else row['tokens']+tokens
        if seed: row.update(partial=True, note='Known usage lower bound')
        target.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, delete=False, encoding='utf-8') as handle:
                name = handle.name
                json.dump(data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, target)
        finally:
            if name and os.path.exists(name): os.unlink(name)


def usage_tokens(usage):
    usage = usage or {}
    inp = usage.get('input_tokens', usage.get('prompt_tokens', usage.get('promptTokenCount', 0))) or 0
    out = usage.get('output_tokens', usage.get('completion_tokens', usage.get('candidatesTokenCount', 0))) or 0
    details = usage.get('output_tokens_details') or usage.get('completion_tokens_details') or {}
    reasoning = details.get('reasoning_tokens', usage.get('reasoning_tokens', usage.get('thoughtsTokenCount', 0))) or 0
    # OpenAI detail counts are already included in output. Gemini thoughts are separate.
    separate = reasoning if not details and ('thoughtsTokenCount' in usage or 'reasoning_tokens' in usage) else 0
    return {'input':inp, 'output':out, 'reasoning':reasoning, 'total':inp+out+separate}


def record(route, raw):
    tokens = usage_tokens(raw.get('usage') or raw.get('usageMetadata'))['total']
    if tokens: update(key(route), tokens)


def fraction(route, today=None):
    quota = route.get('quota', {})
    overrides = json.loads(os.getenv('SIGNAL_ROUTE_QUOTAS', '{}'))
    quota = overrides.get(key(route), quota)
    if quota.get('unlimited'): return 1.0
    if quota.get('expires') and datetime.date.fromisoformat(quota['expires']) < (today or datetime.date.today()): return 0.0
    cap = quota.get('free_tokens')
    if cap is not None:
        with LOCK: used = read().get(key(route), {}).get('tokens', 0)
        return max(0.0, min(1.0, (cap-used)/cap)) if cap > 0 else 0.0
    if route.get('free') and quota.get('kind') != 'usd_credit': return 1.0
    try: return max(0.0, min(1.0, float(os.getenv('SIGNAL_ROUTE_PAID_WEIGHT', '.25'))))
    except ValueError: return .25


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('show')
    seed = sub.add_parser('seed'); seed.add_argument('--known', action='store_true', required=True)
    args = parser.parse_args()
    if args.command == 'seed':
        for identity, tokens in KNOWN.items(): update(identity, tokens, seed=True)
    print(json.dumps(read(), indent=2))

if __name__ == '__main__': main()
