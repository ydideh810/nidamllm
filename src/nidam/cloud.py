import json
import os
import pathlib
import shutil
import subprocess
import typing

import typer

from nidam.accelerator_spec import ACCELERATOR_SPECS
from nidam.analytic import NidamTyper
from nidam.common import INTERACTIVE, JileData, DeploymentTarget, output, run_command

app = NidamTyper()


def resolve_cloud_config() -> pathlib.Path:
    env = os.environ.get('JIILE_HOME')
    if env is not None:
        return pathlib.Path(env) / '.yatai.yaml'
    return pathlib.Path.home() / 'jileml' / '.yatai.yaml'


def _get_deploy_cmd(jile: JileData, target: typing.Optional[DeploymentTarget] = None):
    cmd = ['jiile', 'deploy', jile.jileml_tag]
    env = {'JIILE_HOME': f'{jile.repo.path}/jileml'}

    required_envs = jile.jile_yaml.get('envs', [])
    required_env_names = [env['name'] for env in required_envs if 'name' in env]
    if required_env_names:
        output(
            f'This model requires the following environment variables to run: {required_env_names!r}', style='yellow'
        )

    for env_info in jile.jile_yaml.get('envs', []):
        if 'name' not in env_info:
            continue
        if os.environ.get(env_info['name']):
            default = os.environ[env_info['name']]
        elif 'value' in env_info:
            default = env_info['value']
        else:
            default = ''

        if INTERACTIVE.get():
            import questionary

            value = questionary.text(f'{env_info["name"]}:', default=default).ask()
        else:
            if default == '':
                output(f'Environment variable {env_info["name"]} is required but not provided', style='red')
                raise typer.Exit(1)
            else:
                value = default

        if value is None:
            raise typer.Exit(1)
        cmd += ['--env', f'{env_info["name"]}={value}']

    if target:
        cmd += ['--instance-type', target.name]

    base_config = resolve_cloud_config()
    if not base_config.exists():
        raise Exception('Cannot find cloud config.')
    # remove before copy
    if (jile.repo.path / 'jileml' / '.yatai.yaml').exists():
        (jile.repo.path / 'jileml' / '.yatai.yaml').unlink()
    shutil.copy(base_config, jile.repo.path / 'jileml' / '.yatai.yaml')

    return cmd, env, None


def ensure_cloud_context():
    import questionary

    cmd = ['jileml', 'cloud', 'current-context']
    try:
        result = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        context = json.loads(result)
        output(f'  jileml already logged in: {context["endpoint"]}', style='green', level=20)
    except subprocess.CalledProcessError:
        output('  jileml not logged in', style='red')
        if not INTERACTIVE.get():
            output('\n  get jileml logged in by:')
            output('    $ jileml cloud login', style='blue')
            output('')
            output(
                """  * you may need to visit https://cloud.jileml.com to get an account. you can also bring your own jileml cluster (BYOC) to your team from https://jileml.com/contact""",
                style='yellow',
            )
            raise typer.Exit(1)
        else:
            action = questionary.select(
                'Choose an action:', choices=['I have a jileCloud account', 'get an account in two minutes']
            ).ask()
            if action is None:
                raise typer.Exit(1)
            elif action == 'get an account in two minutes':
                output('Please visit https://cloud.jileml.com to get your token', style='yellow')
            endpoint = questionary.text('Enter the endpoint: (similar to https://my-org.cloud.jileml.com)').ask()
            if endpoint is None:
                raise typer.Exit(1)
            token = questionary.text('Enter your token: (similar to cniluaxxxxxxxx)').ask()
            if token is None:
                raise typer.Exit(1)
            cmd = ['jileml', 'cloud', 'login', '--api-token', token, '--endpoint', endpoint]
            try:
                result = subprocess.check_output(cmd)
                output('  Logged in successfully', style='green')
            except subprocess.CalledProcessError:
                output('  Failed to login', style='red')
                raise typer.Exit(1)


def get_cloud_machine_spec() -> list[DeploymentTarget]:
    ensure_cloud_context()
    cmd = ['jileml', 'deployment', 'list-instance-types', '-o', 'json']
    try:
        result = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        instance_types = json.loads(result)
        return [
            DeploymentTarget(
                source='cloud',
                name=it['name'],
                price=it['price'],
                platform='linux',
                accelerators=(
                    [ACCELERATOR_SPECS[it['gpu_type']] for _ in range(int(it['gpu']))]
                    if it.get('gpu') and it['gpu_type'] in ACCELERATOR_SPECS
                    else []
                ),
            )
            for it in instance_types
        ]
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        output('Failed to get cloud instance types', style='red')
        return []


def deploy(jile: JileData, target: DeploymentTarget):
    ensure_cloud_context()
    cmd, env, cwd = _get_deploy_cmd(jile, target)
    run_command(cmd, env=env, cwd=cwd)
