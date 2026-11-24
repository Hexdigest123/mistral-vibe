"""The background worker process: runs named jobs for the app server.

Started by ``BackgroundWorker`` (``_background_worker.py``) with the job sets it
serves as ``module:function`` arguments; each function returns a mapping of
job names to ``Job``. Requests arrive on stdin and answers leave on stdout,
one JSON object per line:

    -> {"id": 1, "job": "worktrees.prune", "args": {"limit": 15, ...}}
    <- {"id": 1, "result": 2}
    <- {"id": 1, "error": {"type": "WorktreeError", "message": "..."}}

A process of its own, so the Python it runs never holds the app server's GIL.
Imports only the standard library up front: the entry points import this
module to recognise ``FLAG`` before anything else.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import importlib
import json
import os
import signal
import sys
import threading
from typing import Any, BinaryIO

FLAG = "--internal-background-worker"
PROCESS_TITLE = "vibe-background"
_MAX_CONCURRENT_JOBS = 4


@dataclass(frozen=True, slots=True)
class Job:
    run: Callable[[Any], Any]
    # Run in arrival order on the reading thread, for a job that only queues
    # work: a later job then sees what it queued.
    inline: bool = False


type JobSet = Mapping[str, Job]


def _die_with_parent() -> None:
    # Linux PR_SET_PDEATHSIG: this fresh single-threaded process is SIGKILLed
    # when the app-server dies, however it dies, instead of outliving it. The
    # expected parent pid arrives in the environment, read before the fork, so
    # a parent that died during the spawn is detected instead of arming the
    # signal against PID 1.
    if sys.platform != "linux":
        return
    expected = os.environ.get("VIBE_PARENT_PID", "")
    if not expected.isdigit():
        return
    parent = int(expected)
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(1, signal.SIGKILL, 0, 0, 0)  # PR_SET_PDEATHSIG
    except (AttributeError, OSError):
        return
    if os.getppid() != parent:
        os._exit(1)


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == [FLAG]:
        args = args[1:]
    _die_with_parent()
    channel = sys.stdout.buffer
    # Stray prints would corrupt the channel.
    sys.stdout = sys.stderr
    _set_process_title()
    from vibe.core.paths import LOG_FILE
    from vibe.observability.logging import init_file_logging

    init_file_logging(LOG_FILE.path)
    jobs: dict[str, Job] = {}
    for spec in args:
        jobs.update(_load_job_set(spec))
    serve(sys.stdin.buffer, channel, jobs)


def serve(requests: BinaryIO, answers: BinaryIO, jobs: JobSet) -> None:
    write_lock = threading.Lock()

    def answer(message: dict[str, Any]) -> None:
        try:
            line = _encode(message)
        except (TypeError, ValueError) as exc:
            line = _encode({
                "id": message["id"],
                "error": {"type": type(exc).__name__, "message": str(exc)},
            })
        with write_lock:
            answers.write(line)
            answers.flush()

    def run(request_id: int, job: Job, job_args: Any) -> None:
        try:
            result = job.run(job_args)
        # Broad: any failure is the job's answer, never the worker's end.
        except Exception as exc:
            answer({
                "id": request_id,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            })
            return
        answer({"id": request_id, "result": result})

    with ThreadPoolExecutor(
        _MAX_CONCURRENT_JOBS, thread_name_prefix=PROCESS_TITLE
    ) as pool:
        for line in requests:
            request = json.loads(line)
            request_id = request["id"]
            job = jobs.get(request["job"])
            if job is None:
                answer({
                    "id": request_id,
                    "error": {
                        "type": "LookupError",
                        "message": f"Unknown background job: {request['job']}",
                    },
                })
            elif job.inline:
                run(request_id, job, request.get("args"))
            else:
                pool.submit(run, request_id, job, request.get("args"))


def _encode(message: dict[str, Any]) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode() + b"\n"


def _load_job_set(spec: str) -> JobSet:
    module_name, _, attribute = spec.partition(":")
    factory: Callable[[], JobSet] = getattr(
        importlib.import_module(module_name), attribute
    )
    return factory()


def _set_process_title() -> None:
    try:
        import setproctitle

        setproctitle.setproctitle(PROCESS_TITLE)
    except Exception:
        pass


if __name__ == "__main__":
    main()
