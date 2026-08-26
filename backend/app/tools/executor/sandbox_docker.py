"""L2 沙箱：Docker 容器（可选增强）。

隔离：--network none（禁网）、只读 / 隔离、CPU/内存限制、超时自动清理。
依赖：本机已安装并运行 Docker。
不可用时抛出异常，由 runner 回退到 L1。
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from pathlib import Path

from ...core.config import ARTIFACT_DIR
from .sandbox_local import SandboxResult

_IMAGES = {
    "python": "python:3.12-slim",
    "node": "node:20-slim",
    "shell": "alpine:latest",
    "sh": "alpine:latest",
}

_DOCKER_CACHE: bool | None = None


def docker_available() -> bool:
    global _DOCKER_CACHE
    if _DOCKER_CACHE is None:
        _DOCKER_CACHE = shutil.which("docker") is not None
    return _DOCKER_CACHE


async def run_code_docker(
    code: str,
    language: str = "python",
    timeout: int = 60,
) -> SandboxResult:
    if not docker_available():
        raise RuntimeError("Docker 不可用")

    image = _IMAGES.get(language)
    if not image:
        raise RuntimeError(f"Docker 沙箱不支持语言: {language}")

    ext = {"python": "py", "node": "js", "shell": "sh", "sh": "sh"}[language]
    workdir = Path(tempfile.mkdtemp(prefix="masbx_dk_", dir=ARTIFACT_DIR))
    source = workdir / f"main.{ext}"
    source.write_text(code, encoding="utf-8")

    entry = {
        "python": ["python", f"/work/main.{ext}"],
        "node": ["node", f"/work/main.{ext}"],
        "shell": ["sh", f"/work/main.{ext}"],
        "sh": ["sh", f"/work/main.{ext}"],
    }[language]

    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--memory",
        "512m",
        "--cpus",
        "1",
        "-v",
        f"{workdir}:/work:ro",
        "-w",
        "/work",
        image,
        *entry,
    ]

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            timed_out = False
        except asyncio.TimeoutError:
            proc.kill()
            out_b, err_b = await proc.communicate()
            timed_out = True
        exit_code = proc.returncode or 0
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Docker 执行失败: {exc}") from exc
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)

    return SandboxResult(
        stdout=out_b.decode("utf-8", errors="replace"),
        stderr=err_b.decode("utf-8", errors="replace"),
        exit_code=exit_code,
        timed_out=timed_out,
        duration_ms=duration_ms,
        workdir=str(workdir),
    )
