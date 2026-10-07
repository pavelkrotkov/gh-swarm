# Swarm selection and flock serialization are the only local coordination primitives.
# A named swarm must exist; ambiguous implicit selection requires the operator to choose.
# Lock scope is one swarm and never the Hermes gateway or unrelated swarms.
import os
from contextlib import contextmanager
from pathlib import Path
try: import fcntl
except ImportError: fcntl=None
HOME=Path(os.environ.get("HERMES_HOME",Path.home()/".hermes")).expanduser(); STATE=Path(os.environ.get("HERMES_SWARM_STATE_DIR",HOME/"swarms")).expanduser()
def manifest_path(swarm_id): return STATE/f"{swarm_id}.json"
def manifests(): STATE.mkdir(parents=True,exist_ok=True); return sorted(STATE.glob("*.json"))
def selected(*,name=None,all_swarms=False):
    if name:
        if not (path:=manifest_path(name)).exists(): raise RuntimeError(f"unknown swarm {name}")
        return [path]
    if len(paths:=manifests())==1 or all_swarms: return paths
    raise RuntimeError("Specify --name or --all")
@contextmanager
def locked(path,*,nonblocking=False):
    if fcntl is None: raise RuntimeError("swarm reconcile locking requires POSIX flock support")
    path.parent.mkdir(parents=True,exist_ok=True)
    with open(path,"w",encoding="utf-8") as handle: fcntl.flock(handle,fcntl.LOCK_EX|(fcntl.LOCK_NB if nonblocking else 0)); yield
