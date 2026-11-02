"""Process-wide route admission and transient failover; no credentials in state."""
import os
import queue
import re
import threading
import time
import urllib.error

CONDITION = threading.Condition()
STATE = {}
CURSOR = {}


def setting(name, default, minimum):
    try: return max(minimum, float(os.getenv(name, str(default))))
    except ValueError: return default


def identity(family, route):
    return (family, route['route_platform'], route['base_url'], route['model'])


def transient(error):
    if isinstance(error, (TimeoutError, ConnectionError, urllib.error.URLError)):
        return True
    return bool(re.search(r'HTTP (429|5\d\d)|connection failed|timed out', str(error)))


def bounded_request(request, route, timeout, release):
    # Daemon workers let the caller fail over even during DNS or a stalled read.
    # Retain admission until the underlying request actually exits.
    result = queue.Queue(maxsize=1)
    def run():
        try:
            result.put((True, request(route)))
        except BaseException as error:
            result.put((False, error))
        finally:
            release()
    threading.Thread(target=run, daemon=True).start()
    try:
        ok, value = result.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError('Route attempt timed out') from None
    if not ok:
        raise value
    return value


def invoke(family, routes, request, sample, *, timeout=None, deadline=None):
    remaining = list(routes)
    attempts = sample.setdefault('attempts', [])
    sample['failovers'] = 0
    while remaining:
        with CONDITION:
            while True:
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    raise TimeoutError('Call deadline exceeded')
                states = [(r, STATE.setdefault(identity(family, r), {'busy': 0, 'failures': 0, 'until': 0})) for r in remaining]
                healthy = [(r, s) for r, s in states if s['until'] <= now]
                candidates = healthy or states
                available = [(r, s) for r, s in candidates if s['busy'] < r['concurrency']]
                if available:
                    cursor = CURSOR.get(family, 0)
                    r, state = min(available, key=lambda pair: (pair[1]['busy'], (routes.index(pair[0])-cursor) % len(routes)))
                    CURSOR[family] = (routes.index(r)+1) % len(routes)
                    state['busy'] += 1
                    break
                CONDITION.wait(min(.1, max(0, deadline-now)) if deadline is not None else .1)
        attempt = {'route_platform': r['route_platform'], 'route_model': r['model']}
        attempts.append(attempt)
        sample.update(route_platform=r['route_platform'], route_model=r['model'], failovers=len(attempts)-1)
        started = time.monotonic()
        failed = False
        def release(state=state):
            with CONDITION:
                state['busy'] -= 1
                CONDITION.notify_all()
        try:
            if timeout is None:
                raw = request(r)
            else:
                budget = min(timeout, deadline-time.monotonic()) if deadline is not None else timeout
                if budget <= 0:
                    release()
                    raise TimeoutError('Call deadline exceeded')
                raw = bounded_request(request, r, budget, release)
            attempt['status'] = 'answered'
            return r, raw
        except Exception as error:
            failed = transient(error)
            # Store categories only: exception text may contain provider secrets.
            match = re.search(r'HTTP (\d{3})', str(error))
            attempt.update(status='failed', error='transient' if failed else 'request_failed')
            if match: attempt['http_status'] = int(match[1])
            remaining.remove(r)
            if not failed or not remaining: raise
        finally:
            attempt['latency_ms'] = round((time.monotonic()-started)*1000)
            with CONDITION:
                if timeout is None: state['busy'] -= 1
                state['failures'] = state['failures']+1 if failed else 0
                if not failed: state['until'] = 0
                if state['failures'] >= setting('SIGNAL_ROUTE_FAILURE_THRESHOLD', 3, 1):
                    state['until'] = time.monotonic()+setting('SIGNAL_ROUTE_COOLDOWN', 60, 0)
                CONDITION.notify_all()
