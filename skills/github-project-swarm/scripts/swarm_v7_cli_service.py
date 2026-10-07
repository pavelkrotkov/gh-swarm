# User-systemd integration controls only the swarm reconciler units.
# Timer health fails closed if systemd reports an active timer with no next elapse.
# The Hermes gateway is intentionally outside this boundary.
from swarm_v7_cli_process import run_command
_TIMER="hermes-swarm-reconcile.timer"; _SERVICE="hermes-swarm-reconcile.service"
def systemctl(*args,check=True): return run_command(["systemctl","--user",*args],check=check)
def _timer_health():
    values=dict(line.split("=",1) for line in systemctl("show",_TIMER,"-p","ActiveState","-p","NextElapseUSecMonotonic",check=False).splitlines() if "=" in line); dead=values.get("ActiveState")=="active" and values.get("NextElapseUSecMonotonic") in {"","0"}
    if dead and systemctl("show",_SERVICE,"-p","ActiveState","--value",check=False) not in {"active","activating"}: raise RuntimeError(f"{_TIMER} is active but has no next elapse; run `systemctl --user restart {_TIMER}`")
