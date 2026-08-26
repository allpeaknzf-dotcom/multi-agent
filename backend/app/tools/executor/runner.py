"""沙箱统一入口：自动选择 L1（本地受限进程）或 L2（Docker）。"""
from __future__ import annotations

from ...core.config import SANDBOX_TIMEOUT
from .sandbox_docker import docker_available, run_code_docker
from .sandbox_local import SandboxResult, run_code_local

__all__ = ["SandboxResult", "run_code", "run_code_local", "run_code_docker", "docker_available"]


async def run_code(
    code: str,
    language: str = "python",
    timeout: int | None = None,
    use_docker: bool = False,
) -> SandboxResult:
    """执行代码。默认 L1；use_docker=True 且环境支持时走 L2。"""
    timeout = timeout or SANDBOX_TIMEOUT

    if use_docker and docker_available():
        try:
            return await run_code_docker(code, language=language, timeout=timeout)
        except Exception:  # noqa: BLE001   Docker 失败回退 L1
            pass

    return await run_code_local(code, language=language, timeout=timeout)
