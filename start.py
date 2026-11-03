"""One-click local bootstrap. Creates an isolated environment, then starts the app."""
from pathlib import Path
import hashlib
import os
import subprocess
import sys
import venv


def main():
    if sys.version_info < (3, 12):
        print('Install Python 3.12 or newer: https://www.python.org/downloads/')
        return 1
    root = Path(__file__).resolve().parent
    os.chdir(root)
    environment = root / '.venv'
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        print('Preparing local Python environment...', flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    signature = hashlib.sha256((root / 'requirements.txt').read_bytes()).hexdigest()
    marker = environment / 'kp-requirements.sha256'
    if not marker.exists() or marker.read_text(encoding='ascii') != signature:
        print('Installing PDF dependencies (Internet required on first launch)...', flush=True)
        code = subprocess.call([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'requirements.txt'])
        if code:
            print('Installation failed. Check Internet access and run again. No application data was changed.')
            return code
        marker.write_text(signature, encoding='ascii')
    try:
        return subprocess.call([str(python), 'app.py', '--open'])
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
