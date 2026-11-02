"""Run explicitly to make one short API request per configured CN provider."""
import sys
import ai_api

PROVIDERS = ('hunyuan', 'deepseek', 'kimi', 'zhipu', 'minimax', 'qwen', 'doubao')


def main():
    failed = False
    for pid in PROVIDERS:
        p = ai_api.provider(pid)
        c = ai_api.registry.configuration(p)
        if c is None:
            print(f'{pid} route=- model=- FAIL unconfigured')
            failed = True
            continue
        prefix = f"{pid} route={c['route']} model={c['model']}"
        try:
            ai_api.safe_endpoint(p, c['base_url'])
            url, headers, body = ai_api.request_for(p, c, '请用一句简短的中文回答：天空通常是什么颜色？')
            result = ai_api.parse({**p, 'protocol': c['protocol']}, ai_api.http_json(url, headers, body))
            passed = result['complete'] and not result['answer_from_reasoning']
            answer = result['answer']
            for provider in ai_api.catalog():
                for route in provider['routes']:
                    key = ai_api.os.environ.get(route['env_key_var'], '').strip()
                    if key:
                        answer = answer.replace(key, '[REDACTED]')
            print(f"{prefix} {'PASS' if passed else 'FAIL'} {answer[:80]!r}")
            failed |= not passed
        except Exception:
            # Exceptions can contain request credentials; never print their contents.
            print(f'{prefix} FAIL request/response failed')
            failed = True
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
