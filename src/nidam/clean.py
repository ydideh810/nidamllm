import os
import pathlib
import shutil
import logging
import concurrent.futures
from typing import List

import questionary

from nidam.analytic import NidamTyper
from nidam.common import CONFIG_FILE, REPO_DIR, VENV_DIR, VERBOSE_LEVEL, output

app = NidamTyper(help='Clean up and release disk space used by Nidam')

HUGGINGFACE_CACHE = pathlib.Path.home() / '.cache' / 'huggingface' / 'hub'

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def _du(path: pathlib.Path) -> int:
    seen_paths = set()
    used_space = 0

    try:
        for f in path.rglob('*'):
            if not f.exists():
                continue
            if os.name == 'nt':  # Windows system
                used_space += f.stat().st_size
            else:
                stat = f.stat()
                if stat.st_ino not in seen_paths:
                    seen_paths.add(stat.st_ino)
                    used_space += stat.st_size
    except Exception as e:
        logging.warning(f"Error calculating disk usage for {path}: {e}")
    
    return used_space

def _remove_path(path: pathlib.Path, description: str, dry_run: bool = False):
    if not path.exists():
        logging.info(f"{description} does not exist, skipping.")
        return
    
    used_space = _du(path)
    if dry_run:
        output(f"[Dry Run] {description} would be removed (~{used_space / 1024 / 1024:.2f}MB)", style='yellow')
        return
    
    sure = questionary.confirm(f"This will remove {description} (~{used_space / 1024 / 1024:.2f}MB). Are you sure?").ask()
    if sure:
        shutil.rmtree(path, ignore_errors=True)
        output(f"{description} has been removed (~{used_space / 1024 / 1024:.2f}MB freed)", style='green')

@app.command(help='Clean up all the cached models from Hugging Face')
def model_cache(verbose: bool = False, dry_run: bool = False):
    if verbose:
        VERBOSE_LEVEL.set(20)
    _remove_path(HUGGINGFACE_CACHE, 'Hugging Face model cache', dry_run)

@app.command(help='Clean up all the virtual environments created by Nidam')
def venvs(verbose: bool = False, dry_run: bool = False):
    if verbose:
        VERBOSE_LEVEL.set(20)
    _remove_path(VENV_DIR, 'virtual environments', dry_run)

@app.command(help='Clean up all the repositories cloned by Nidam')
def repos(verbose: bool = False, dry_run: bool = False):
    if verbose:
        VERBOSE_LEVEL.set(20)
    _remove_path(REPO_DIR, 'cloned repositories', dry_run)

@app.command(help='Reset configurations to default')
def configs(verbose: bool = False, dry_run: bool = False):
    if verbose:
        VERBOSE_LEVEL.set(20)
    _remove_path(CONFIG_FILE, 'configuration files', dry_run)

@app.command(name='all', help='Clean up all above and bring Nidam to a fresh start')
def all_cache(verbose: bool = False, dry_run: bool = False):
    if verbose:
        VERBOSE_LEVEL.set(20)
    
    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.map(lambda f: f(verbose, dry_run), [repos, venvs, model_cache, configs])
