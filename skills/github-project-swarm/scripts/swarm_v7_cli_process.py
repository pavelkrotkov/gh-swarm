# Shared bounded subprocess transport for every external CLI adapter.
# Timeout policy is centralized here; callers choose only command-specific error types.
import os, shlex, subprocess
def subprocess_timeout():
    try: value = float(os.environ.get("HERMES_SWARM_SUBPROCESS_TIMEOUT", "180"))
    except ValueError as exc: raise RuntimeError("HERMES_SWARM_SUBPROCESS_TIMEOUT must be a positive number") from exc
    if value <= 0: raise RuntimeError("HERMES_SWARM_SUBPROCESS_TIMEOUT must be a positive number")
    return value

def run_process(cmd, cwd=None, *, check=True, timeout=None, input_text=None, error_type=RuntimeError, env=None):
    timeout = min(subprocess_timeout(), timeout) if timeout is not None else subprocess_timeout()
    try: proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, input=input_text, timeout=timeout, check=False, env=env)
    except subprocess.TimeoutExpired as exc: raise error_type(f"external command timed out after {timeout:g}s: {shlex.join(map(str, cmd))}") from exc
    if check and proc.returncode: raise error_type(proc.stderr.strip() or proc.stdout.strip() or f"command exited {proc.returncode}")
    return proc

def run_command(cmd, cwd=None, *, check=True, timeout=None, input_text=None):
    return run_process(cmd, cwd, check=check, timeout=timeout, input_text=input_text).stdout.strip()

