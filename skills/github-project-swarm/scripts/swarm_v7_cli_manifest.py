# Runtime persistence uses atomic replace plus file and directory fsync before returning.
# Schema 5/6 state is rejected rather than migrated into the schema-7 authority model.
# Persistence stores configuration/cursors only; no journal row is read back as semantic truth.
import errno,json,os,tempfile
from pathlib import Path
from swarm_v7_controller import RuntimeManifest
from swarm_v7_cli_selection import HOME,STATE,locked,manifest_path,manifests,selected
def _fsync_directory(path):
    if os.name=="nt": return
    fd=os.open(path,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
    try: os.fsync(fd)
    except OSError as exc:
        if exc.errno not in (errno.EINVAL,errno.ENOTSUP): raise
    finally: os.close(fd)
def save(runtime):
    STATE.mkdir(parents=True,exist_ok=True); target=manifest_path(runtime.config.swarm_id); fd,tmp=tempfile.mkstemp(prefix=f".{runtime.config.swarm_id}.",suffix=".tmp",dir=STATE)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out: json.dump(runtime.to_dict(),out,ensure_ascii=False,indent=2); out.write("\n"); out.flush(); os.fsync(out.fileno())
        os.replace(tmp,target); _fsync_directory(STATE)
    finally: Path(tmp).unlink(missing_ok=True)
def load(path):
    raw=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw,dict): raise RuntimeError(f"{path}: swarm manifest must be a JSON object")
    if raw.get("schema")!=7: raise RuntimeError(f"{path}: unsupported swarm schema {raw.get('schema')!r}; schema 5/6 migration is intentionally disabled. Initialize a fresh v7 swarm.")
    return RuntimeManifest.from_dict(raw)
