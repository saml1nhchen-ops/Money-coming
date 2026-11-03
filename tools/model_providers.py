"""Single provider registry; public metadata never contains credentials."""
import json, os, pathlib, re, urllib.parse
from route_pool import validate_pool_model
from repo_env import load_repo_env

load_repo_env()
LOAD_SECRETS = os.environ.get("SIGNAL_LOAD_DOTENV", "1") != "0"

CATALOG_PATH = pathlib.Path(__file__).resolve().parents[1] / 'dist/ai-providers.json'
ALIASES = {'claude': 'anthropic', 'glm': 'zhipu'}

def catalog():
    return json.loads(CATALOG_PATH.read_text('utf-8'))

def provider(pid):
    pid = ALIASES.get(pid, pid)
    for row in catalog():
        if row['id'] == pid:
            return row
    raise ValueError('Unknown API provider')

def configuration(p, environ=None, route=None):
    """Resolve once before a call; never retry on another route after an error."""
    env = os.environ if environ is None else environ
    selected = route if route is not None else (env.get(p['env_route_var'], '').strip() or 'auto')
    routes = [r for r in p['routes'] if not r.get('pool') or r['id']==selected]
    if selected == 'auto':
        routes = sorted([r for r in routes if r.get('default', True)], key=lambda r: (r['id'] != 'tokenhub', not r['free'], r['id'] != 'official'))
    else:
        routes = [r for r in routes if r['id'] == selected]
    for r in routes:
        key = credential(r['env_key_var'], env)
        model = env.get(r.get('env_model_var', ''), '').strip() or (env.get(p['env_model_var'], '').strip() if r['id'] == 'official' else '') or r['default_model']
        base = (env.get(p['env_base_url_var'], '').strip() if r['id'] == 'official' else '') or r['base_url']
        try:
            u = urllib.parse.urlsplit(base)
            valid = (u.scheme == 'https' and bool(u.hostname) and not u.username and not u.password
                     and not u.query and not u.fragment and u.port in (None, 443))
        except ValueError:
            valid = False
        if not key or len(key)>4096 or any(c in key for c in '\r\n') or not model or not valid or not re.fullmatch(r'[\w./:@+-]{1,200}', model):
            continue
        # An override must not silently turn a free route into a paid one.
        free = model_is_free(r, model)
        if selected == 'auto' and r['free'] and not free:
            continue
        return {'key': key, 'model': model, 'base_url': base.rstrip('/'), 'search': False,
                'route': r['id'], 'free': free, 'protocol': r['protocol'],
                'quota':r.get('quota',{}), 'fallback_only':r.get('fallback_only',False),
                'route_platform':r.get('platform',r['id']),
                **({'thinking_off':r['thinking_off']} if 'thinking_off' in r else {})}
    # Official model overrides (including paid models) are the last auto choice.
    if selected == 'auto':
        return configuration(p, env, 'official') if any(r['id']=='official' and r.get('default', True) for r in p['routes']) else None
    return None

def route_status(p, environ=None):
    return [{**r, 'configured': bool(configuration(p, environ, r['id'])),
             **{k:v for k,v in (configuration(p, environ, r['id']) or {}).items() if k != 'key'}}
            for r in p['routes']]

def model_is_free(route, model):
    if route['id'] == 'openrouter': return model.endswith(':free')
    if route['id'] == 'nvidia_nim': return True
    return route['free'] and model == route['default_model']


def credential(name, env):
    value = env.get(name, '')
    if not value and LOAD_SECRETS and env is os.environ and env.get('SIGNAL_LOAD_DOTENV', '1') != '0':
        try:
            with (pathlib.Path.home() / '.secrets' / name).open() as handle:
                value = handle.readline()
        except OSError:
            pass
    return value.splitlines()[0].strip() if value else ''


def route_pool(p, environ=None):
    env = os.environ if environ is None else environ
    defaults = [r for r in p['routes'] if r.get('pool')]
    override = env.get('SIGNAL_' + p['id'].upper() + '_ROUTES', '').strip()
    if override:
        try:
            specs = json.loads(override) if override.startswith('[') else override.split(',')
            if not isinstance(specs, list): raise ValueError()
            routes = []
            for spec in specs:
                if isinstance(spec, str):
                    platform, model = spec.strip().split(':', 1)
                    validate_pool_model(p['id'], p.get('pool_model'), model)
                    match = next(r for r in defaults if r['platform'] == platform and r['default_model'] == model)
                    routes.append(dict(match))
                else:
                    platform = spec['platform']
                    template = next(r for r in defaults if r['platform'] == platform)
                    routes.append({**template, **spec, 'default_model': spec.get('model', spec.get('default_model', template['default_model']))})
        except (ValueError, KeyError, StopIteration, TypeError):
            raise ValueError('Invalid route pool for ' + p['id'] + '; expected model ' + str(p.get('pool_model'))) from None
    else:
        routes = defaults
    result = []
    for r in routes:
        model = r['default_model']
        validate_pool_model(p['id'], p.get('pool_model'), model)
        key = credential(r['env_key_var'], env)
        if not key: continue
        if not re.fullmatch(r'[\w./:@+-]{1,200}', model): raise ValueError('Invalid route model')
        u = urllib.parse.urlsplit(r['base_url'])
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.port not in (None,443):
            raise ValueError('Invalid route base URL')
        name = 'SIGNAL_' + re.sub(r'[^A-Z0-9]', '_', p['id'].upper()+'_'+r['platform'].upper()+'_'+model.upper()) + '_CONCURRENCY'
        cap = r.get('concurrency', 4)
        for var in ('SIGNAL_GEO_PROVIDER_CONCURRENCY', 'SIGNAL_ROUTE_CONCURRENCY'):
            try: cap = max(1, min(128, int(env.get(var, cap))))
            except ValueError: pass
        if r['platform']=='zhipu' and model=='glm-4.7-flash':cap=min(cap,1)
        try: cap=max(1,min(128,int(env.get(name,cap))))
        except ValueError:pass
        result.append({'pool': True, 'model_version': p['pool_model'], 'route': r['id'], 'route_platform': r['platform'], 'model': model,
                       'base_url': r['base_url'].rstrip('/'), 'key': key, 'search': False,
                       'protocol': r['protocol'], 'free': model_is_free(r, model),
                       'thinking_off': r['thinking_off'], 'concurrency': cap,
                       'quota':r.get('quota',{}), 'fallback_only':r.get('fallback_only',False)})
    return result
