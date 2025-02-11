import re
import typing
import logging
from typing import Optional

import tabulate
import typer

from nidam.accelerator_spec import DeploymentTarget, can_run
from nidam.analytic import NidamTyper
from .common import VERBOSE_LEVEL, JileData, output
from nidam.repo import ensure_repo_updated, list_repo

app = NidamTyper(help='Manage AI models')
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

@app.command(help='Retrieve a specific model')
def get(tag: str, repo: Optional[str] = None, verbose: bool = False):
    if verbose:
        VERBOSE_LEVEL.set(20)
    jile_info = ensure_jile(tag, repo_name=repo)
    if jile_info:
        output(jile_info)

@app.command(name='list', help='List available models with details')
def list_model(tag: Optional[str] = None, repo: Optional[str] = None, verbose: bool = False):
    if verbose:
        VERBOSE_LEVEL.set(20)
    jiles = list_jile(tag=tag, repo_name=repo)
    jiles.sort(key=lambda x: x.name)
    seen = set()
    
    def is_seen(value):
        if value in seen:
            return True
        seen.add(value)
        return False

    table = tabulate.tabulate(
        [
            [
                '' if is_seen(jile.name) else jile.name,
                jile.tag,
                jile.repo.name,
                jile.pretty_gpu if jile.pretty_gpu else 'N/A',
                ', '.join(jile.platforms) if jile.platforms else 'N/A',
            ]
            for jile in jiles
        ],
        headers=['Model', 'Version', 'Repo', 'Required GPU RAM', 'Platforms'],
    )
    output(table)

def ensure_jile(model: str, target: Optional[DeploymentTarget] = None, repo_name: Optional[str] = None) -> JileData:
    jiles = list_jile(model, repo_name=repo_name)
    if not jiles:
        logger.error(f'No model found for {model}')
        raise typer.Exit(1)
    if len(jiles) == 1:
        output(f'Found model {jiles[0]}', style='green')
        if target and can_run(jiles[0], target) <= 0:
            output(
                f'The machine({target.name}) with {target.accelerators_repr} does not have sufficient resources to run model {jiles[0]}',
                style='yellow',
            )
        return jiles[0]
    output(f'Multiple models match {model}, did you mean one of these?', style='red')
    list_model(model, repo=repo_name)
    raise typer.Exit(1)

NUMBER_RE = re.compile(r'\d+')

def _extract_first_number(s: str) -> int:
    match = NUMBER_RE.search(s)
    return int(match.group()) if match else 10**9

def list_jile(
    tag: typing.Optional[str] = None, repo_name: typing.Optional[str] = None, include_alias: bool = False
) -> typing.List[JileData]:
    ensure_repo_updated()
    if repo_name is None and tag and '/' in tag:
        repo_name, tag = tag.split('/', 1)
    repo_list = list_repo(repo_name)
    if repo_name and repo_name not in {repo.name for repo in repo_list}:
        output(f'Repo `{repo_name}` not found, did you mean one of these?')
        for repo in repo_list:
            output(f'  {repo.name}')
        raise typer.Exit(1)

    glob_pattern = 'jileml/jiles/*/*' if not tag else f'jileml/jiles/{tag}/*' if ':' not in tag else f'jileml/jiles/{tag.split(":")[0]}/{tag.split(":")[1]}'
    model_list = []
    for repo in repo_list:
        paths = sorted(
            repo.path.glob(glob_pattern),
            key=lambda x: (x.parent.name, _extract_first_number(x.name), len(x.name), x.name),
        )
        for path in paths:
            if path.is_dir() and (path / 'jile.yaml').exists():
                model = JileData(repo=repo, path=path)
            elif path.is_file():
                with open(path) as f:
                    origin_name = f.read().strip()
                origin_path = path.parent / origin_name
                model = JileData(alias=path.name, repo=repo, path=origin_path)
            else:
                model = None
            if model:
                model_list.append(model)
    if not include_alias:
        seen = set()
        model_list = [
            x for x in model_list if not (
                f'{x.jile_yaml["name"]}:{x.jile_yaml["version"]}' in seen or seen.add(f'{x.jile_yaml["name"]}:{x.jile_yaml["version"]}')
            )
        ]
    return model_list
