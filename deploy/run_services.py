"""Supervise the three existing loopback services; never expose their ports."""
import json
import pathlib
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICES = ('native_service.py', 'bai_service.py', 'geo_flow.py')
PORTS = (8770, 8771, 8772)


def check():
    for port in PORTS:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/index.html', timeout=2) as response:
            if response.status != 200 or b'Signal GEO' not in response.read():
                raise RuntimeError(f'Workbench on {port} is not ready')
    # Verify authenticated API behavior without any provider calls.
    for port, prefix in zip(PORTS, ('tools', 'bai', 'geo')):
        base = f'http://127.0.0.1:{port}/api/{prefix}/'
        request = urllib.request.Request(base + 'session', headers={'Sec-Fetch-Site': 'same-origin'})
        with urllib.request.urlopen(request, timeout=2) as response:
            token = json.load(response)['token']
        request = urllib.request.Request(base + ('health' if prefix == 'tools' else 'state'),
                                        headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(request, timeout=2) as response:
            if not isinstance(json.load(response), dict):
                raise RuntimeError(f'Invalid {prefix} response')


def main():
    children = []
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for name in SERVICES:
            children.append(subprocess.Popen([sys.executable, str(ROOT / 'tools' / name)], cwd=ROOT))
        while not stopping:
            if any(child.poll() is not None for child in children):
                return 1
            time.sleep(0.5)
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    if '--check' in sys.argv:
        check()
    else:
        sys.exit(main())
