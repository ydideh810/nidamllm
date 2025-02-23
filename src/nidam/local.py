import asyncio
import time
from typing import Optional

import httpx

from .common import JileData, EnvVars, async_run_command, output, run_command, stream_command_output
from nidam.venv import ensure_venv


def prep_env_vars(jile: JileData):
    import os

    env_vars = jile.envs
    for env_var in env_vars:
        if not env_var.get('value'):
            continue
        key = env_var['name']
        value = env_var['value']
        os.environ[key] = value


def _get_serve_cmd(jile: JileData, port: int = 3000) -> tuple[list[str], EnvVars, Optional[str]]:
    cmd = ['jileml', 'serve', jile.jileml_tag]
    if port != 3000:
        cmd += ['--port', str(port)]
    env = EnvVars({'JIILE_HOME': f'{jile.repo.path}/jileml'})
    return cmd, env, None


def serve(jile: JileData, port: int = 3000):
    prep_env_vars(jile)
    cmd, env, cwd = _get_serve_cmd(jile, port=port)
    venv = ensure_venv(jile, runtime_envs=env)
    output(f'Access the Chat UI at http://localhost:{port}/chat (or with you IP)')
    run_command(cmd, env=env, cwd=cwd, venv=venv)


async def _run_model(jile: JileData, port: int = 3000, timeout: int = 600):
    cmd, env, cwd = _get_serve_cmd(jile, port)
    venv = ensure_venv(jile, runtime_envs=env)
    async with async_run_command(cmd, env=env, cwd=cwd, venv=venv, silent=False) as server_proc:
        output(f'Model server started {server_proc.pid}')

        stdout_streamer = None
        stderr_streamer = None
        start_time = time.time()

        output('Model loading...', style='green')
        for _ in range(timeout):
            try:
                resp = httpx.get(f'http://localhost:{port}/readyz', timeout=3)
                if resp.status_code == 200:
                    break
            except httpx.RequestError:
                if time.time() - start_time > 30:
                    if not stdout_streamer:
                        stdout_streamer = asyncio.create_task(stream_command_output(server_proc.stdout, style='gray'))
                    if not stderr_streamer:
                        stderr_streamer = asyncio.create_task(
                            stream_command_output(server_proc.stderr, style='#BD2D0F')
                        )
                await asyncio.sleep(1)
        else:
            output('Model failed to load', style='red')
            server_proc.terminate()
            return

        if stdout_streamer:
            stdout_streamer.cancel()
        if stderr_streamer:
            stderr_streamer.cancel()

        output('Model is ready', style='green')
        messages: list[dict[str, str]] = []

        from openai import AsyncOpenAI

        client = AsyncOpenAI(base_url=f'http://localhost:{port}/v1', api_key='local')
        model_id = (await client.models.list()).data[0].id
        while True:
            try:
                message = input('user: ')
                if message == '':
                    output('empty message, please enter something', style='yellow')
                    continue
                messages.append(dict(role='user', content=message))
                output('assistant: ', end='', style='lightgreen')
                assistant_message = ''
                stream = await client.chat.completions.create(
                    model=model_id,
                    messages=messages,  # type: ignore
                    stream=True,
                )
                async for chunk in stream:
                    text = chunk.choices[0].delta.content or ''
                    assistant_message += text
                    output(text, end='', style='lightgreen')
                messages.append(dict(role='assistant', content=assistant_message))
                output('')
            except KeyboardInterrupt:
                break
        output('\nStopping model server...', style='green')
    output('Stopped model server', style='green')


def run(jile: JileData, port: int = 3000, timeout: int = 600):
    prep_env_vars(jile)
    asyncio.run(_run_model(jile, port=port, timeout=timeout))
