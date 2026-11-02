"""Single provider registry; public metadata never contains credentials."""
import json, os, pathlib, re, urllib.parse

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
    routes = p['routes']
    if selected == 'auto':
        routes = sorted(routes, key=lambda r: (not r['free'], r['id'] != 'official'))
    else:
        routes = [r for r in routes if r['id'] == selected]
    for r in routes:
        key = env.get(r['env_key_var'], '').strip()
        model = env.get(r['env_model_var'], '').strip() or (env.get(p['env_model_var'], '').strip() if r['id'] == 'official' else '') or r['default_model']
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
                'route': r['id'], 'free': free, 'protocol': r['protocol']}
    # Official model overrides (including paid models) are the last auto choice.
    if selected == 'auto':
        return configuration(p, env, 'official')
    return None

def route_status(p, environ=None):
    return [{**r, 'configured': bool(configuration(p, environ, r['id'])),
             **{k:v for k,v in (configuration(p, environ, r['id']) or {}).items() if k != 'key'}}
            for r in p['routes']]

def model_is_free(route, model):
    if route['id'] == 'openrouter': return model.endswith(':free')
    if route['id'] == 'nvidia_nim': return True
    return route['free'] and model == route['default_model']
