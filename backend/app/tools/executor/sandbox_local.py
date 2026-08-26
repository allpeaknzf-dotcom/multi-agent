"""L1 沙箱：本地受限子进程。

隔离措施（无外部依赖）：
- 独立临时工作目录（位于应用 artifacts 目录下，与用户项目隔离）
- 虚拟内存上限 + CPU 时间限制（通过 ulimit 包装命令）
- 执行超时强制 kill
- 仅捕获 stdout/stderr/退出码，不做网络隔离
安全提示：L1 为"进程级"隔离，无法绝对阻止对文件系统的访问；
需要更强隔离请启用 L2（Docker，默认禁网 + 只读挂载）。
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ...core.config import ARTIFACT_DIR

# 语言 -> 可执行 + 文件扩展名
SUPPORTED_LANGS: dict[str, tuple[str, str]] = {
    "python": ("python3", "py"),
    "node": ("node", "js"),
    "shell": ("bash", "sh"),
    "sh": ("bash", "sh"),
}

# 默认资源上限
DEFAULT_MEM_LIMIT = 512 * 1024 * 1024  # 512MB 虚拟内存


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    duration_ms: int
    workdir: str = ""


async def run_code_local(
    code: str,
    language: str = "python",
    timeout: int = 60,
) -> SandboxResult:
    if language not in SUPPORTED_LANGS:
        return SandboxResult("", f"不支持的语言: {language}", -1, False, 0, "")

    exe, ext = SUPPORTED_LANGS[language]
    workdir = Path(tempfile.mkdtemp(prefix="masbx_", dir=ARTIFACT_DIR))
    source = workdir / f"main.{ext}"
    source.write_text(code, encoding="utf-8")

    env = dict(os.environ)
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            # 提示子进程工作区根目录（代码可据此读写自己的文件）
            "MULTIAGENT_WORKDIR": str(workdir),
        }
    )

    # 通过 ulimit 限制虚拟内存与 CPU 时间（bash 包装，避免 shell 注入：路径均由本模块控制）
    mem_kb = DEFAULT_MEM_LIMIT // 1024
    wrapper = (
        f"ulimit -v {mem_kb} 2>/dev/null; "
        f"ulimit -t {timeout} 2>/dev/null; "
        f"exec {exe} '{source}'"
    )
    cmd = ["bash", "-c", wrapper]

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workdir),
            env=env,
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
        return SandboxResult("", f"沙箱启动失败: {exc}", -1, False, 0, str(workdir))
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
