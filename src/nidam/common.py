from __future__ import annotations

import asyncio
import functools
import hashlib
import io
import json
import os
import pathlib
import signal
import subprocess
import sys
import sysconfig
import typing
from collections import UserDict
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import typer
import typer.core

ERROR_STYLE = 'red'
SUCCESS_STYLE = 'green'

NIDAM_HOME = pathlib.Path(os.getenv('NIDAM_HOME', pathlib.Path.home() / '.nidam'))

REPO_DIR = NIDAM_HOME / 'repos'
TEMP_DIR = NIDAM_HOME / 'temp'
VENV_DIR = NIDAM_HOME / 'venv'

REPO_DIR.mkdir(exist_ok=True, parents=True)
TEMP_DIR.mkdir(exist_ok=True, parents=True)
VENV_DIR.mkdir(exist_ok=True, parents=True)

CONFIG_FILE = NIDAM_HOME / 'config.json'

CHECKED = 'Yes'

T = typing.TypeVar('T')


class ContextVar(typing.Generic[T]):
    def __init__(self, default: T):
        self._stack: list[T] = []
        self._default = default

    def get(self) -> T:
        if self._stack:
            return self._stack[-1]
        return self._default

    def set(self, value: T):
        self._stack.append(value)

    @contextmanager
    def patch(self, value: T):
        self._stack.append(value)
        try:
            yield
        finally:
            self._stack.pop()


VERBOSE_LEVEL = ContextVar(10)
INTERACTIVE = ContextVar(False)


def output(content, level=0, style=None, end=None):
    import questionary

    if level > VERBOSE_LEVEL.get():
        return

    if not isinstance(content, str):
        import pyaml

        out = io.StringIO()
        pyaml.pprint(content, dst=out, sort_dicts=False, sort_keys=False)
        questionary.print(out.getvalue(), style=style, end='' if end is None else end)
        out.close()

    if isinstance(content, str):
        questionary.print(content, style=style, end='\n' if end is None else end)


class Config(SimpleNamespace):
    repos: dict[str, str] = {'default': 'https://github.com/jileml/nidam-models@main'}
    default_repo: str = 'default'

    def tolist(self):
        return dict(repos=self.repos, default_repo=self.default_repo)


def load_config() -> Config:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return Config(**json.load(f))
        except json.JSONDecodeError:
            return Config()
    return Config()


def save_config(config: Config) -> None:
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config.tolist(), f, indent=2)


class EnvVars(UserDict[str, str]):
    """
    A dictionary-like object that sorted by key and only keeps the environment variables that have a value.
    """

    def __init__(self, data: typing.Optional[typing.Mapping[str, str]] = None):
        super().__init__(data or {})
        self.data = {k: v for k, v in sorted(self.data.items()) if v}

    def __hash__(self):  # type: ignore
        return hash(tuple(sorted(self.data.items())))


class RepoInfo(SimpleNamespace):
    name: str
    path: pathlib.Path
    url: str
    server: str
    owner: str
    repo: str
    branch: str

    def tolist(self):
        if VERBOSE_LEVEL.get() <= 0:
            return f'{self.name} ({self.url}@{self.branch})'
        if VERBOSE_LEVEL.get() <= 10:
            return dict(name=self.name, url=f'{self.url}@{self.branch}', path=str(self.path))
        if VERBOSE_LEVEL.get() <= 20:
            return dict(
                name=self.name,
                url=f'{self.url}@{self.branch}',
                path=str(self.path),
                server=self.server,
                owner=self.owner,
                repo=self.repo,
            )


class JileData(SimpleNamespace):
    repo: RepoInfo
    path: pathlib.Path
    alias: str = ''

    def __str__(self):
        if self.repo.name == 'default':
            return f'{self.tag}'
        else:
            return f'{self.repo.name}/{self.tag}'

    def __hash__(self):  # type: ignore
        return md5(str(self.path))

    @property
    def tag(self) -> str:
        if self.alias:
            return f'{self.path.parent.name}:{self.alias}'
        return f'{self.path.parent.name}:{self.path.name}'

    @property
    def jileml_tag(self) -> str:
        return f'{self.path.parent.name}:{self.path.name}'

    @property
    def name(self) -> str:
        return self.path.parent.name

    @property
    def version(self) -> str:
        return self.path.name

    @property
    def labels(self) -> dict[str, str]:
        return self.jile_yaml['labels']

    @property
    def envs(self) -> list[dict[str, str]]:
        return self.jile_yaml['envs']

    @functools.cached_property
    def jile_yaml(self) -> dict:
        import yaml

        jile_file = self.path / 'jile.yaml'
        return yaml.safe_load(jile_file.read_text())

    @functools.cached_property
    def platforms(self) -> list[str]:
        return self.jile_yaml['labels'].get('platforms', 'linux').split(',')

    @functools.cached_property
    def pretty_yaml(self) -> dict:
        def _pretty_routes(routes):
            return {
                route['route']: {
                    'input': {k: v['type'] for k, v in route['input']['properties'].items()},
                    'output': route['output']['type'],
                }
                for route in routes
            }

        if len(self.jile_yaml['services']) == 1:
            pretty_yaml = {
                'apis': _pretty_routes(self.jile_yaml['schema']['routes']),
                'resources': self.jile_yaml['services'][0]['config']['resources'],
                'envs': self.jile_yaml['envs'],
                'platforms': self.platforms,
            }
            return pretty_yaml
        return self.jile_yaml

    @functools.cached_property
    def pretty_gpu(self) -> str:
        from nidam.accelerator_spec import ACCELERATOR_SPECS

        try:
            resources = self.jile_yaml['services'][0]['config']['resources']
            if resources['gpu'] > 1:
                acc = ACCELERATOR_SPECS[resources['gpu_type']]
                return f'{acc.memory_size:.0f}Gx{resources["gpu"]}'
            elif resources['gpu'] > 0:
                acc = ACCELERATOR_SPECS[resources['gpu_type']]
                return f'{acc.memory_size:.0f}G'
        except KeyError:
            pass
        return ''

    def tolist(self):
        verbose = VERBOSE_LEVEL.get()
        if verbose <= 0:
            return str(self)
        if verbose <= 10:
            return dict(tag=self.tag, repo=self.repo.tolist(), path=str(self.path), model_card=self.pretty_yaml)
        if verbose <= 20:
            return dict(tag=self.tag, repo=self.repo.tolist(), path=str(self.path), jile_yaml=self.jile_yaml)


class VenvSpec(SimpleNamespace):
    python_version: str
    requirements_txt: str
    name_prefix = ''
    envs: EnvVars

    @functools.cached_property
    def normalized_requirements_txt(self) -> str:
        parameter_lines: list[str] = []
        dependency_lines: list[str] = []
        comment_lines: list[str] = []

        for line in self.requirements_txt.splitlines():
            if not line.strip():
                continue
            elif line.strip().startswith('#'):
                comment_lines.append(line.strip())
            elif line.strip().startswith('-'):
                parameter_lines.append(line.strip())
            else:
                dependency_lines.append(line.strip())

        parameter_lines.sort()
        dependency_lines.sort()
        return '\n'.join(parameter_lines + dependency_lines).strip()

    @functools.cached_property
    def normalized_envs(self) -> str:
        """
        sorted by name
        """
        return '\n'.join(f'{k}={v}' for k, v in sorted(self.envs.items(), key=lambda x: x[0]) if not v)

    def __hash__(self):  # type: ignore
        return md5(self.normalized_requirements_txt, str(hash(self.normalized_envs)))


class Accelerator(SimpleNamespace):
    model: str
    memory_size: float

    def __gt__(self, other):
        return self.memory_size > other.memory_size

    def __eq__(self, other):
        return self.memory_size == other.memory_size


class DeploymentTarget(SimpleNamespace):
    source: str = 'local'
    name: str = 'local'
    price: str = ''
    platform = 'linux'
    accelerators: list[Accelerator]

    def __hash__(self):  # type: ignore
        return hash(self.source)

    @property
    def accelerators_repr(self) -> str:
        accs = {a.model for a in self.accelerators}
        if len(accs) == 0:
            return 'null'
        if len(accs) == 1:
            a = self.accelerators[0]
            return f'{a.model} x{len(self.accelerators)}'
        return ', '.join((f'{a.model}' for a in self.accelerators))


def run_command(cmd, cwd=None, env=None, copy_env=True, venv=None, silent=False) -> subprocess.CompletedProcess:
    import shlex

    env = env or {}
    cmd = [str(c) for c in cmd]
    bin_dir = 'Scripts' if os.name == 'nt' else 'bin'
    if not silent:
        output('\n')
        if cwd:
            output(f'$ cd {cwd}', style='blue')
        if env:
            for k, v in env.items():
                output(f'$ export {k}={shlex.quote(v)}', style='blue')
        if venv:
            output(f'$ source {venv / "bin" / "activate"}', style='blue')
        output(f'$ {" ".join(cmd)}', style='blue')

    if venv:
        py = venv / bin_dir / f'python{sysconfig.get_config_var("EXE")}'
    else:
        py = sys.executable

    if copy_env:
        env = {**os.environ, **env}

    if cmd and cmd[0] == 'jileml':
        cmd = [py, '-m', 'jileml'] + cmd[1:]
    if cmd and cmd[0] == 'python':
        cmd = [py] + cmd[1:]

    try:
        if silent:
            return subprocess.run(  # type: ignore
                cmd, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
            )
        else:
            return subprocess.run(cmd, cwd=cwd, env=env, check=True)
    except Exception as e:
        if VERBOSE_LEVEL.get() >= 10:
            output(e, style='red')
        output('Command failed', style='red')
        raise typer.Exit(1)


async def stream_command_output(stream, style='gray'):
    async for line in stream:
        output(line.decode(), style=style, end='')


@asynccontextmanager
async def async_run_command(cmd, cwd=None, env=None, copy_env=True, venv=None, silent=True):
    import shlex

    env = env or {}
    cmd = [str(c) for c in cmd]

    if not silent:
        output('\n')
        if cwd:
            output(f'$ cd {cwd}', style='blue')
        if env:
            for k, v in env.items():
                output(f'$ export {k}={shlex.quote(v)}', style='blue')
        if venv:
            output(f'$ source {venv / "bin" / "activate"}', style='blue')
        output(f'$ {" ".join(cmd)}', style='blue')

    if venv:
        py = venv / 'bin' / 'python'
    else:
        py = sys.executable

    if copy_env:
        env = {**os.environ, **env}

    if cmd and cmd[0] == 'jileml':
        cmd = [py, '-m', 'jileml'] + cmd[1:]
    if cmd and cmd[0] == 'python':
        cmd = [py] + cmd[1:]

    proc = None
    try:
        proc = await asyncio.create_subprocess_shell(
            ' '.join(map(str, cmd)), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd, env=env
        )
        yield proc
    except subprocess.CalledProcessError:
        output('Command failed', style='red')
        raise typer.Exit(1)
    finally:
        if proc:
            proc.send_signal(signal.SIGINT)
            await proc.wait()


def md5(*strings: str) -> int:
    m = hashlib.md5()
    for s in strings:
        m.update(s.encode())
    return int(m.hexdigest(), 16)
