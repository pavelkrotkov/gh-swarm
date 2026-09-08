import os, pathlib, re, shlex, subprocess, tempfile

def subprocess_timeout():
    try: value = float(os.environ.get("HERMES_SWARM_SUBPROCESS_TIMEOUT", "180"))
    except ValueError as exc: raise RuntimeError("HERMES_SWARM_SUBPROCESS_TIMEOUT must be a positive number") from exc
    if value <= 0: raise RuntimeError("HERMES_SWARM_SUBPROCESS_TIMEOUT must be a positive number")
    return value

def ensure_worker_github_auth(assignee):
    home=os.path.realpath(os.path.expanduser(os.environ.get("HERMES_HOME","~/.hermes"))); profiles=os.path.join(home,"profiles"); name=str(assignee or ""); profile=os.path.realpath(os.path.join(profiles,name)); config=os.path.realpath(os.path.expanduser(os.environ.get("GH_CONFIG_DIR",os.path.join(os.environ.get("XDG_CONFIG_HOME","~/.config"),"gh")))); env=os.path.join(profile,".env")
    if not all((name,os.path.dirname(profile)==profiles,os.path.isdir(profile),os.path.isfile(os.path.join(config,"hosts.yml")))) or os.path.islink(env): raise RuntimeError(f"GitHub CLI auth/profile unavailable for Hermes worker {name!r}; run `gh auth login`, ensure {profile} exists without a symlinked .env, or set GH_CONFIG_DIR")
    auth_env={key:value for key,value in os.environ.items() if key not in {"GH_TOKEN","GITHUB_TOKEN","GH_ENTERPRISE_TOKEN","GITHUB_ENTERPRISE_TOKEN"}}; auth_env["GH_CONFIG_DIR"]=config; auth=run_process(("gh","auth","status","--active","--hostname","github.com"),check=False,env=auth_env)
    if auth.returncode: raise RuntimeError(f"GitHub CLI auth unavailable through projected config {config}; run `GH_CONFIG_DIR={config} gh auth login` before swarm dispatch")
    text=pathlib.Path(env).read_text(encoding="utf-8") if os.path.exists(env) else ""; projected=(re.sub(r"(?m)^GH_CONFIG_DIR=.*(?:\n|$)","",text).rstrip("\n")+f"\nGH_CONFIG_DIR={config}\n").lstrip("\n")
    with tempfile.NamedTemporaryFile("w",dir=profile,delete=False,encoding="utf-8") as out: out.write(projected); out.flush(); os.fsync(out.fileno()); os.fchmod(out.fileno(),0o600); tmp=out.name
    os.replace(tmp,env)

def run_process(cmd, cwd=None, *, check=True, timeout=None, input_text=None, error_type=RuntimeError, env=None):
    timeout = min(subprocess_timeout(), timeout) if timeout is not None else subprocess_timeout()
    try: proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, input=input_text, timeout=timeout, check=False, env=env)
    except subprocess.TimeoutExpired as exc: raise error_type(f"external command timed out after {timeout:g}s: {shlex.join(map(str, cmd))}") from exc
    if check and proc.returncode: raise error_type(proc.stderr.strip() or proc.stdout.strip() or f"command exited {proc.returncode}")
    return proc

def run_command(cmd, cwd=None, *, check=True, timeout=None, input_text=None):
    return run_process(cmd, cwd, check=check, timeout=timeout, input_text=input_text).stdout.strip()