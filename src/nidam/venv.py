import functools
import os
import pathlib
import shutil
from typing import Optional

import typer
import yaml

from nidam.common import VENV_DIR, VERBOSE_LEVEL, JileData, EnvVars, VenvSpec, output, run_command


@functools.lru_cache
def _resolve_jile_venv_spec(jile: JileData, runtime_envs: Optional[EnvVars] = None) -> VenvSpec:
    lock_file = jile.path / 'env' / 'python' / 'requirements.lock.txt'
    if not lock_file.exists():
        lock_file = jile.path / 'env' / 'python' / 'requirements.txt'

    reqs = lock_file.read_text().strip()
    jilefile = jile.path / 'jile.yaml'
    data = yaml.safe_load(jilefile.read_text())
    jile_env_list = data.get('envs', [])
    python_version = data.get('image', {})['python_version']
    jile_envs = {e['name']: e.get('value') for e in jile_env_list}
    envs = {k: runtime_envs.get(k, v) for k, v in jile_envs.items()} if runtime_envs else {}

    return VenvSpec(
        python_version=python_version,
        requirements_txt=reqs,
        name_prefix=f'{jile.tag.replace(":", "_")}-1-',
        envs=EnvVars(envs),
    )


def _ensure_venv(venv_spec: VenvSpec) -> pathlib.Path:
    venv = VENV_DIR / str(hash(venv_spec))
    if venv.exists() and not (venv / 'DONE').exists():
        shutil.rmtree(venv, ignore_errors=True)
    if not venv.exists():
        output(f'Installing model dependencies({venv})...', style='green')

        venv_py = venv / 'Scripts' / 'python.exe' if os.name == 'nt' else venv / 'bin' / 'python'
        try:
            run_command(
                ['python', '-m', 'uv', 'venv', venv, '-p', venv_spec.python_version], silent=VERBOSE_LEVEL.get() < 10
            )
            run_command(
                ['python', '-m', 'uv', 'pip', 'install', '-p', str(venv_py), 'jileml'],
                silent=VERBOSE_LEVEL.get() < 10,
                env=venv_spec.envs,
            )
            with open(venv / 'requirements.txt', 'w') as f:
                f.write(venv_spec.normalized_requirements_txt)
            run_command(
                ['python', '-m', 'uv', 'pip', 'install', '-p', str(venv_py), '-r', venv / 'requirements.txt'],
                silent=VERBOSE_LEVEL.get() < 10,
                env=venv_spec.envs,
            )
            with open(venv / 'DONE', 'w') as f:
                f.write('DONE')
        except Exception as e:
            shutil.rmtree(venv, ignore_errors=True)
            if VERBOSE_LEVEL.get() >= 10:
                output(e, style='red')
            output(f'Failed to install dependencies to {venv}. Cleaned up.', style='red')
            raise typer.Exit(1)
        output(f'Successfully installed dependencies to {venv}.', style='green')
        return venv
    else:
        return venv


def ensure_venv(jile: JileData, runtime_envs: Optional[EnvVars] = None) -> pathlib.Path:
    venv_spec = _resolve_jile_venv_spec(jile, runtime_envs=EnvVars(runtime_envs))
    venv = _ensure_venv(venv_spec)
    assert venv is not None
    return venv


def check_venv(jile: JileData) -> bool:
    venv_spec = _resolve_jile_venv_spec(jile)
    venv = VENV_DIR / str(hash(venv_spec))
    if not venv.exists():
        return False
    if venv.exists() and not (venv / 'DONE').exists():
        return False
    return True
