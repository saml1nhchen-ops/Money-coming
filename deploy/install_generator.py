"""Install only the locked question generator without rewriting upstream locks."""
import json
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def install():
    record = next(r for r in json.loads((ROOT / 'tools/upstreams.lock.json').read_text())
                  if r['id'] == 'niubigeo')
    dest = ROOT / 'runtime/upstreams/niubigeo'
    if not (dest / '.git').exists():
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', str(dest)], check=True)
        subprocess.run(['git', '-C', str(dest), 'remote', 'add', 'origin',
                        'https://github.com/' + record['repository'] + '.git'], check=True)
    subprocess.run(['git', '-C', str(dest), 'fetch', '--depth=1', 'origin', record['commit']], check=True)
    subprocess.run(['git', '-C', str(dest), 'checkout', '--detach', record['commit']], check=True)
    actual = subprocess.check_output(['git', '-C', str(dest), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != record['commit']:
        raise RuntimeError('Upstream commit does not match lock')
    shutil.copyfile(ROOT / 'tools/niubigeo-pnpm-lock.yaml', dest / 'pnpm-lock.yaml')
    subprocess.run(['pnpm', 'install', '--frozen-lockfile', '--ignore-scripts',
                    '--store-dir', str(ROOT / 'runtime/pnpm-store')], cwd=dest, check=True)


if __name__ == '__main__':
    install()
