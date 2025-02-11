from __future__ import annotations

import functools
import os
import re
import time
import typing
import json
import platform
import requests
import psutil
from abc import ABC

import attr
import click
import typer
import typer.core

DO_NOT_TRACK = 'NIDAM_DO_NOT_TRACK'
ANALYTICS_ENDPOINT = 'https://analytics.server.com/track'
LOG_FILE = 'analytics_log.json'

class EventMeta(ABC):
    @property
    def event_name(self):
        # camel case to snake case
        event_name = re.sub(r'(?<!^)(?=[A-Z])', '_', self.__class__.__name__).lower()
        # remove "_event" suffix
        suffix_to_remove = '_event'
        if event_name.endswith(suffix_to_remove):
            event_name = event_name[: -len(suffix_to_remove)]
        return event_name

@attr.define
class CliEvent(EventMeta):
    cmd_group: str
    cmd_name: str
    duration_in_ms: float = attr.field(default=0)
    error_type: typing.Optional[str] = attr.field(default=None)
    return_code: typing.Optional[int] = attr.field(default=None)
    cpu_usage: float = attr.field(default=0)
    memory_usage: float = attr.field(default=0)
    system_info: dict = attr.field(default={})

@attr.define
class NidamCliEvent(CliEvent):
    pass

class OrderedCommands(typer.core.TyperGroup):
    def list_commands(self, _: click.Context) -> typing.Iterable[str]:  # type: ignore
        return list(self.commands)

class NidamTyper(typer.Typer):
    def __init__(self, *args: typing.Any, **kwargs: typing.Any):
        no_args_is_help = kwargs.pop('no_args_is_help', True)
        context_settings = kwargs.pop('context_settings', {})
        if 'help_option_names' not in context_settings:
            context_settings['help_option_names'] = ('-h', '--help')
        if 'max_content_width' not in context_settings:
            context_settings['max_content_width'] = int(os.environ.get('COLUMNS', str(120)))
        klass = kwargs.pop('cls', OrderedCommands)

        super().__init__(
            *args, cls=klass, no_args_is_help=no_args_is_help, context_settings=context_settings, **kwargs
        )

    if typing.TYPE_CHECKING:
        command = typer.Typer.command
    else:
        def command(self, *args: typing.Any, **kwargs: typing.Any):
            def decorator(f):
                @functools.wraps(f)
                @click.pass_context
                def wrapped(ctx: click.Context, *args, **kwargs):
                    from jileml._internal.utils.analytics import track

                    do_not_track = os.environ.get(DO_NOT_TRACK, str(False)).lower() == 'true'

                    command_name = ctx.info_name
                    if ctx.parent.parent is not None:
                        command_group = ctx.parent.info_name
                    elif ctx.parent.info_name == ctx.find_root().info_name:
                        command_group = 'nidam'

                    if do_not_track:
                        return f(*args, **kwargs)
                    
                    system_info = {
                        "os": platform.system(),
                        "os_version": platform.version(),
                        "python_version": platform.python_version(),
                    }
                    
                    start_time = time.time_ns()
                    try:
                        cpu_usage_before = psutil.cpu_percent(interval=None)
                        memory_usage_before = psutil.virtual_memory().percent
                        return_value = f(*args, **kwargs)
                        duration_in_ns = time.time_ns() - start_time
                        
                        cpu_usage_after = psutil.cpu_percent(interval=None)
                        memory_usage_after = psutil.virtual_memory().percent
                        
                        event_data = NidamCliEvent(
                            cmd_group=command_group,
                            cmd_name=command_name,
                            duration_in_ms=duration_in_ns / 1e6,
                            cpu_usage=(cpu_usage_before + cpu_usage_after) / 2,
                            memory_usage=(memory_usage_before + memory_usage_after) / 2,
                            system_info=system_info
                        )
                        
                        track(event_data)
                        
                        with open(LOG_FILE, "a") as log_file:
                            json.dump(attr.asdict(event_data), log_file)
                            log_file.write("\n")
                        
                        requests.post(ANALYTICS_ENDPOINT, json=attr.asdict(event_data))
                        return return_value
                    except BaseException as e:
                        duration_in_ns = time.time_ns() - start_time
                        event_data = NidamCliEvent(
                            cmd_group=command_group,
                            cmd_name=command_name,
                            duration_in_ms=duration_in_ns / 1e6,
                            error_type=type(e).__name__,
                            return_code=(2 if isinstance(e, KeyboardInterrupt) else 1),
                            system_info=system_info
                        )
                        
                        track(event_data)
                        
                        with open(LOG_FILE, "a") as log_file:
                            json.dump(attr.asdict(event_data), log_file)
                            log_file.write("\n")
                        
                        requests.post(ANALYTICS_ENDPOINT, json=attr.asdict(event_data))
                        raise
                
                return typer.Typer.command(self, *args, **kwargs)(wrapped)
            
            return decorator
