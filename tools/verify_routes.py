"""Opt-in tiny route probes; dry-run never loads credentials or contacts providers."""
import argparse
import json
import os
import re
import socket
import time
import urllib.error


def error_diagnostics(error):
    """Return only fixed categories and a numeric status, never exception text."""
    status = error.code if isinstance(error, urllib.error.HTTPError) else None
    # http_json deliberately replaces HTTPError with a safe ValueError summary.
    if status is None and isinstance(error, ValueError):
        match = re.match(r'^Provider HTTP (\d{3});', str(error))
        if match:
            status = int(match[1])
    if status is not None:
        category = {401: 'authentication', 403: 'permission_denied',
                    404: 'not_found', 429: 'rate_limited'}.get(status)
        return category or ('provider_error' if status >= 500 else 'http_error'), status
    if isinstance(error, (TimeoutError, socket.timeout)):
        return 'timeout', None
    if isinstance(error, (ConnectionError, urllib.error.URLError, socket.gaierror)):
        return 'connection_error', None
    if isinstance(error, ValueError) and str(error) == 'Provider connection failed or timed out':
        return 'connection_or_timeout', None
    if isinstance(error, json.JSONDecodeError):
        return 'invalid_json', None
    if isinstance(error, (KeyError, TypeError)):
        return 'invalid_response', None
    return 'request_failed', None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--families', nargs='+', default=['openai','gemini','deepseek','qwen','zhipu','kimi','doubao','minimax','hunyuan'])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.dry_run: os.environ['SIGNAL_LOAD_DOTENV'] = '0'
    import ai_api as api
    import route_ledger
    failed = False
    for family in args.families:
        p = api.provider(family)
        version = p.get('pool_model') or p['default_model']
        seen = set()
        specs = [r for r in p['routes'] if r.get('pool')]
        pooled = bool(specs)
        if not pooled:
            # Match the registry's default single-route selection without letting
            # host route/model/base overrides change what this probe verifies.
            defaults = [r for r in p['routes'] if r.get('default', True)]
            specs = sorted(defaults, key=lambda r: (r['id'] != 'tokenhub', not r['free'], r['id'] != 'official'))[:1]
        # Resolve only registry defaults; family/model/base overrides are not probes.
        env = {r['env_key_var']: ('dry-run' if args.dry_run else api.registry.credential(r['env_key_var'], os.environ)) for r in specs}
        if pooled:
            candidates = api.registry.route_pool(p, env)
        else:
            single = api.registry.configuration(p, env, specs[0]['id']) if specs else None
            candidates = [single] if single else []
        for spec in specs:
            c = next((r for r in candidates if r['route'] == spec['id']), None)
            if not c:
                identity=(spec.get('platform',spec['id']),spec['default_model'])
                if identity not in seen:
                    seen.add(identity)
                    print(f'{family} model_version={version} {identity[0]} {identity[1]} status=not_configured answer_nonempty=False input=0 output=0 reasoning=0 latency_ms=0')
                failed=True
                continue
            identity = (c.get('route_platform',c['route']),c['model'])
            if identity in seen: continue
            seen.add(identity)
            url, headers, body = api.request_for(p,c,'Reply with OK.')
            for field in ('max_tokens','max_completion_tokens','max_output_tokens'):
                if field in body: body[field] = 32
            if 'generationConfig' in body:
                budget=body['generationConfig'].get('thinkingConfig',{}).get('thinkingBudget',0)
                body['generationConfig']['maxOutputTokens'] = max(32, budget+128) if budget else 32
            if args.dry_run:
                print(json.dumps({'family':family,'model_version':version,'platform':identity[0],'model':identity[1],'body':body},ensure_ascii=False))
                continue
            started = time.monotonic(); status='ok'; nonempty=False; tokens={'input':0,'output':0,'reasoning':0}; diagnostics=''
            try:
                raw=api.http_json(url,headers,body)
                route_ledger.record(c,raw)
                parsed=api.parse({**p,'protocol':c.get('protocol',p['protocol'])},raw)
                nonempty=bool(parsed['answer']);tokens=route_ledger.usage_tokens(parsed['usage'])
            except Exception as error:
                status='failed';failed=True
                category, http_status = error_diagnostics(error)
                diagnostics=f' error_category={category} http_status={http_status if http_status is not None else "none"}'
            print(f'{family} model_version={version} {identity[0]} {identity[1]} status={status} answer_nonempty={nonempty} input={tokens["input"]} output={tokens["output"]} reasoning={tokens["reasoning"]} latency_ms={round((time.monotonic()-started)*1000)}{diagnostics}')
    return int(failed)

if __name__=='__main__': raise SystemExit(main())
