import importlib.metadata
import os
import platform
import random
import sys
from collections import defaultdict
from typing import Annotated, Optional

import questionary
import typer

from nidam.accelerator_spec import DeploymentTarget, can_run as original_can_run, get_local_machine_spec
from nidam.analytic import DO_NOT_TRACK, NidamTyper
from nidam.clean import app as clean_app
from nidam.cloud import deploy as cloud_deploy
from nidam.cloud import ensure_cloud_context, get_cloud_machine_spec
from nidam.common import CHECKED, INTERACTIVE, VERBOSE_LEVEL, JileData, output
from nidam.local import run as local_run
from nidam.local import serve as local_serve
from nidam.model import app as model_app
from nidam.model import ensure_jile, list_jile
from nidam.repo import app as repo_app

app = NidamTyper(
    help='`nidam hello` to get started. '
    'NIDAM is a CLI tool to manage and deploy open source LLMs and'
    ' get an OpenAI API compatible chat server in seconds.'
)

app.add_typer(repo_app, name='repo')
app.add_typer(model_app, name='model')
app.add_typer(clean_app, name='clean')

def can_run(model, target, gpu_type: Optional[str] = None, force_cpu: bool = False):
    if force_cpu:
        return target.cpu_support and target.cpu_accelerations.get("AVX2", False)
    
    if gpu_type:
        if gpu_type.lower() in target.accelerators_repr.lower():
            return True
        return False
    
    priority_gpus = ["H100", "A100", "RTX 40", "MI300", "M2", "M3"]
    for accel in target.accelerators:
        if any(gpu in accel.model for gpu in priority_gpus) and accel.memory_size >= model.required_memory:
            return True
    
    return original_can_run(model, target)

def _select_jile_name(models: list[JileData], target: DeploymentTarget):
    from tabulate import tabulate

    options = []
    model_infos = [(model.repo.name, model.name, can_run(model, target)) for model in models]
    model_name_groups = defaultdict(lambda: 0.0)
    for repo, name, score in model_infos:
        model_name_groups[repo, name] += score
    table_data = [(name, repo, CHECKED if score > 0 else '') for (repo, name), score in model_name_groups.items()]
    if not table_data:
        output('No model found', style='red')
        raise typer.Exit(1)
    table = tabulate(table_data, headers=['model', 'repo', 'locally runnable']).split('\n')
    headers = f'{table[0]}\n   {table[1]}'

    options.append(questionary.Separator(headers))
    for table_data, table_line in zip(table_data, table[2:]):
        options.append(questionary.Choice(table_line, value=table_data[:2]))
    selected = questionary.select('Select a model', options).ask()
    if selected is None:
        raise typer.Exit(1)
    return selected


def _select_jile_version(models, target, jile_name, repo):
    from tabulate import tabulate

    model_infos = [
        [model, can_run(model, target)] for model in models if model.name == jile_name and model.repo.name == repo
    ]

    table_data = [
        [model.tag, CHECKED if score > 0 else '']
        for model, score in model_infos
        if model.name == jile_name and model.repo.name == repo
    ]
    if not table_data:
        output(f'No model found for {jile_name} in {repo}', style='red')
        raise typer.Exit(1)
    table = tabulate(table_data, headers=['version', 'locally runnable']).split('\n')

    options = []
    options.append(questionary.Separator(f'{table[0]}\n   {table[1]}'))
    for table_data, table_line in zip(model_infos, table[2:]):
        options.append(questionary.Choice(table_line, value=table_data))
    selected = questionary.select('Select a version', options).ask()
    if selected is None:
        raise typer.Exit(1)
    return selected


def _select_target(jile, targets):
    from tabulate import tabulate

    options = []
    targets.sort(key=lambda x: can_run(jile, x), reverse=True)
    if not targets:
        output('No available instance type, check your jilecloud account', style='red')
        raise typer.Exit(1)

    table = tabulate(
        [
            [
                target.name,
                target.accelerators_repr,
                f'${target.price}',
                CHECKED if can_run(jile, target) else 'insufficient res.',
            ]
            for target in targets
        ],
        headers=['instance type', 'accelerator', 'price/hr', 'deployable'],
    ).split('\n')
    options.append(questionary.Separator(f'{table[0]}\n   {table[1]}'))

    for target, line in zip(targets, table[2:]):
        options.append(questionary.Choice(f'{line}', value=target))
    selected = questionary.select('Select an instance type', options).ask()
    if selected is None:
        raise typer.Exit(1)
    return selected


def _select_action(jile: JileData, score):
    if score > 0:
        options = [
            questionary.Separator('Available actions'),
            questionary.Choice('0. Run the model in terminal', value='run', shortcut_key='0'),
            questionary.Separator(f'  $ nidam run {jile}'),
            questionary.Separator(' '),
            questionary.Choice('1. Serve the model locally and get a chat server', value='serve', shortcut_key='1'),
            questionary.Separator(f'  $ nidam serve {jile}'),
            questionary.Separator(' '),
            questionary.Choice(
                '2. Deploy the model to jilecloud and get a scalable chat server', value='deploy', shortcut_key='2'
            ),
            questionary.Separator(f'  $ nidam deploy {jile}'),
        ]
    else:
        options = [
            questionary.Separator('Available actions'),
            questionary.Choice(
                '0. Run the model in terminal', value='run', disabled='insufficient res.', shortcut_key='0'
            ),
            questionary.Separator(f'  $ nidam run {jile}'),
            questionary.Separator(' '),
            questionary.Choice(
                '1. Serve the model locally and get a chat server',
                value='serve',
                disabled='insufficient res.',
                shortcut_key='1',
            ),
            questionary.Separator(f'  $ nidam serve {jile}'),
            questionary.Separator(' '),
            questionary.Choice(
                '2. Deploy the model to jilecloud and get a scalable chat server', value='deploy', shortcut_key='2'
            ),
            questionary.Separator(f'  $ nidam deploy {jile}'),
        ]
    action = questionary.select('Select an action', options).ask()
    if action is None:
        raise typer.Exit(1)
    if action == 'run':
        try:
            port = random.randint(30000, 40000)
            local_run(jile, port=port)
        finally:
            output('\nUse this command to run the action again:', style='green')
            output(f'  $ nidam run {jile}', style='blue')
    elif action == 'serve':
        try:
            local_serve(jile)
        finally:
            output('\nUse this command to run the action again:', style='green')
            output(f'  $ nidam serve {jile}', style='blue')
    elif action == 'deploy':
        ensure_cloud_context()
        targets = get_cloud_machine_spec()
        target = _select_target(jile, targets)
        try:
            cloud_deploy(jile, target)
        finally:
            output('\nUse this command to run the action again:', style='green')
            output(f'  $ nidam deploy {jile} --instance-type {target.name}', style='blue')


@app.command(help='get started interactively')
def hello():
    INTERACTIVE.set(True)
    target = get_local_machine_spec()
    output(f'  Detected Platform: {target.platform}', style='green')
    if target.accelerators:
        output('  Detected Accelerators: ', style='green')
        for a in target.accelerators:
            output(f'   - {a.model} {a.memory_size}GB', style='green')
    else:
        output('  Detected Accelerators: None', style='yellow')

    models = list_jile()
    if not models:
        output('No model found, you probably need to update the model repo:', style='red')
        output('  $ nidam repo update', style='blue')
        raise typer.Exit(1)

    jile_name, repo = _select_jile_name(models, target)
    jile, score = _select_jile_version(models, target, jile_name, repo)
    _select_action(jile, score)

@app.command(help='start an OpenAI API compatible chat server and chat in browser')
def serve(
    model: Annotated[str, typer.Argument()] = '', repo: Optional[str] = None, port: int = 3000, verbose: bool = False,
    gpu: Optional[str] = typer.Option(None, '--gpu', help='Manually specify GPU type'),
    force_cpu: bool = typer.Option(False, '--force-cpu', help='Force execution on CPU')
):
    if verbose:
        VERBOSE_LEVEL.set(20)
    target = get_local_machine_spec()
    jile = ensure_jile(model, target=target, repo_name=repo)
    if not can_run(jile, target, gpu, force_cpu):
        output('Selected model cannot run on the detected hardware.', style='red')
        raise typer.Exit(1)
    local_serve(jile, port=port)

@app.command(help='run the model and chat in terminal')
def run(
    model: Annotated[str, typer.Argument()] = '',
    repo: Optional[str] = None,
    port: Optional[int] = None,
    timeout: int = 600,
    verbose: bool = False,
    gpu: Optional[str] = typer.Option(None, '--gpu', help='Manually specify GPU type'),
    force_cpu: bool = typer.Option(False, '--force-cpu', help='Force execution on CPU')
):
    if verbose:
        VERBOSE_LEVEL.set(20)
    target = get_local_machine_spec()
    jile = ensure_jile(model, target=target, repo_name=repo)
    if not can_run(jile, target, gpu, force_cpu):
        output('Selected model cannot run on the detected hardware.', style='red')
        raise typer.Exit(1)
    if port is None:
        port = random.randint(30000, 40000)
    local_run(jile, port=port, timeout=timeout)

@app.command(help='deploy an production-ready OpenAI API compatible chat server to jilecloud ($100 free credit)')
def deploy(
    model: Annotated[str, typer.Argument()] = '',
    instance_type: Optional[str] = None,
    repo: Optional[str] = None,
    verbose: bool = False,
):
    if verbose:
        VERBOSE_LEVEL.set(20)
    jile = ensure_jile(model, repo_name=repo)
    if instance_type is not None:
        cloud_deploy(jile, DeploymentTarget(name=instance_type))
        return
    targets = get_cloud_machine_spec()
    targets = filter(lambda x: can_run(jile, x) > 0, targets)
    targets = sorted(targets, key=lambda x: can_run(jile, x), reverse=True)
    if not targets:
        output('No available instance type, check your jilecloud account', style='red')
        raise typer.Exit(1)
    target = targets[0]
    output(f'Recommended instance type: {target.name}', style='green')
    cloud_deploy(jile, target)


if __name__ == '__main__':
    app()
