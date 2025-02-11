from __future__ import annotations

import functools
import math
import re
import typing
import subprocess
import json
import requests
from types import SimpleNamespace
import psutil

from nidam.common import JileData, DeploymentTarget, output

class Accelerator(SimpleNamespace):
    model: str
    memory_size: float
    brand: str

    def __gt__(self, other):
        return self.memory_size > other.memory_size

    def __eq__(self, other):
        return self.memory_size == other.memory_size

    def __repr__(self):
        return f'{self.brand} {self.model} ({self.memory_size}GB)'

class Resource(SimpleNamespace):
    cpu: int = 0
    memory: float
    gpu: int = 0
    gpu_type: str = ''

    def __hash__(self):  # type: ignore
        return hash((self.cpu, self.memory, self.gpu, self.gpu_type))

    def __bool__(self):
        return any(value is not None for value in self.__dict__.values())

# Expand GPU Support
ACCELERATOR_SPEC_DICT = {
    # NVIDIA GPUs
    'nvidia-gtx-1650': {'model': 'GTX 1650', 'memory_size': 4.0},
    'nvidia-gtx-1060': {'model': 'GTX 1060', 'memory_size': 6.0},
    'nvidia-gtx-1080-ti': {'model': 'GTX 1080 Ti', 'memory_size': 11.0},
    'nvidia-rtx-3060': {'model': 'RTX 3060', 'memory_size': 12.0},
    'nvidia-rtx-3060-ti': {'model': 'RTX 3060 Ti', 'memory_size': 8.0},
    'nvidia-rtx-3070-ti': {'model': 'RTX 3070 Ti', 'memory_size': 8.0},
    'nvidia-rtx-3080': {'model': 'RTX 3080', 'memory_size': 10.0},
    'nvidia-rtx-3080-ti': {'model': 'RTX 3080 Ti', 'memory_size': 12.0},
    'nvidia-rtx-3090': {'model': 'RTX 3090', 'memory_size': 24.0},
    'nvidia-rtx-4070-ti': {'model': 'RTX 4070 Ti', 'memory_size': 12.0},
    'nvidia-tesla-p4': {'model': 'P4', 'memory_size': 8.0},
    'nvidia-tesla-p100': {'model': 'P100', 'memory_size': 16.0},
    'nvidia-tesla-k80': {'model': 'K80', 'memory_size': 12.0},
    'nvidia-tesla-t4': {'model': 'T4', 'memory_size': 16.0},
    'nvidia-tesla-v100': {'model': 'V100', 'memory_size': 16.0},
    'nvidia-l4': {'model': 'L4', 'memory_size': 24.0},
    'nvidia-tesla-l4': {'model': 'L4', 'memory_size': 24.0},
    'nvidia-tesla-a10g': {'model': 'A10G', 'memory_size': 24.0},
    'nvidia-a100-80g': {'model': 'A100', 'memory_size': 80.0},
    'nvidia-a100-80gb': {'model': 'A100', 'memory_size': 80.0},
    'nvidia-tesla-a100': {'model': 'A100', 'memory_size': 40.0},
    # AMD GPUs
    'amd-radeon-rx-6800': {'model': 'Radeon RX 6800', 'memory_size': 16.0, 'brand': 'AMD'},
    'amd-radeon-rx-6900': {'model': 'Radeon RX 6900 XT', 'memory_size': 16.0, 'brand': 'AMD'},
    # Intel GPUs
    'intel-arc-a770': {'model': 'Intel Arc A770', 'memory_size': 16.0, 'brand': 'Intel'},
    'intel-xe-integrated': {'model': 'Intel Xe Integrated', 'memory_size': 4.0, 'brand': 'Intel'}
}

ACCELERATOR_SPECS = {key: Accelerator(**value) for key, value in ACCELERATOR_SPEC_DICT.items()}

def get_amd_gpus():
    try:
        result = subprocess.run(['rocm-smi'], capture_output=True, text=True)
        lines = result.stdout.split("\n")
        gpus = []
        for line in lines:
            match = re.search(r'GPU (\d+): (.*?) \(Memory: (\d+)MB\)', line)
            if match:
                model = match.group(2)
                memory_size = int(match.group(3)) / 1024  # Convert MB to GB
                gpus.append(Accelerator(model=model, memory_size=memory_size, brand='AMD'))
        return gpus
    except:
        return []

def get_intel_gpus():
    try:
        result = subprocess.run(['intel_gpu_top', '-J'], capture_output=True, text=True)
        data = json.loads(result.stdout)
        gpus = []
        for gpu in data['devices']:
            model = gpu['name']
            memory_size = gpu.get('memory_size', 4096) / 1024  # Assume 4GB if unknown
            gpus.append(Accelerator(model=model, memory_size=memory_size, brand='Intel'))
        return gpus
    except:
        return []

def get_local_machine_spec():
    platform = 'windows' if psutil.WINDOWS else 'linux' if psutil.LINUX else None
    if platform is None:
        raise NotImplementedError('Unsupported platform')

    accelerators = []
    try:
        from pynvml import nvmlInit, nvmlDeviceGetCount, nvmlDeviceGetHandleByIndex, nvmlDeviceGetMemoryInfo, nvmlDeviceGetName, nvmlShutdown
        nvmlInit()
        for i in range(nvmlDeviceGetCount()):
            handle = nvmlDeviceGetHandleByIndex(i)
            name = nvmlDeviceGetName(handle).decode()
            memory_info = nvmlDeviceGetMemoryInfo(handle)
            accelerators.append(Accelerator(model=name, memory_size=memory_info.total / 1024**3, brand='NVIDIA'))
        nvmlShutdown()
    except:
        pass
    accelerators += get_amd_gpus() + get_intel_gpus()
    return DeploymentTarget(accelerators=accelerators, source='local', platform=platform)

def can_run(jile: typing.Union[Resource, JileData], target: typing.Optional[DeploymentTarget] = None) -> float:
    if target is None:
        target = get_local_machine_spec()
    
    resource_spec = Resource(**(jile.jile_yaml['services'][0]['config'].get('resources', {})))
    labels = jile.jile_yaml.get('labels', {})
    platforms = labels.get('platforms', 'linux').split(',')
    
    if target.platform not in platforms:
        return 0.0
    
    if not resource_spec:
        return 0.5  # No resource constraints
    
    if resource_spec.gpu > 0:
        required_gpu = ACCELERATOR_SPECS.get(resource_spec.gpu_type)
        if not required_gpu:
            return 0.0
        
        compatible_gpus = [ac for ac in target.accelerators if ac.brand == required_gpu.brand and ac.memory_size >= required_gpu.memory_size]
        if resource_spec.gpu > len(compatible_gpus):
            return 0.0
        return required_gpu.memory_size * resource_spec.gpu / sum(ac.memory_size for ac in target.accelerators if ac.brand == required_gpu.brand)
    
    if target.accelerators:
        return 0.01 / sum(ac.memory_size for ac in target.accelerators)
    
    return 1.0
