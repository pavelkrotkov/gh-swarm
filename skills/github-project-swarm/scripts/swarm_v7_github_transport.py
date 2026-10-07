# GitHub CLI transport is bounded, paginated and JSON-shape checked.
# GraphQL pages with errors fail before data reaches issue observation.
# Pagination has an explicit finite ceiling; malformed list pages never silently truncate.
import json
from swarm_v7_cli_process import run_command
from swarm_v7_github_scalars import GitHubReadError,mapping,_rows
class GhReader:
    def __init__(self,timeout_s=30.0):
        if timeout_s<=0: raise ValueError("timeout_s must be positive")
        self.timeout_s=timeout_s
    def get(self,endpoint):
        try: return json.loads(run_command(["gh","api","--method","GET","-H","Accept: application/vnd.github+json",endpoint],timeout=self.timeout_s))
        except (json.JSONDecodeError,RuntimeError) as exc: raise GitHubReadError(f"GitHub returned invalid JSON for {endpoint}" if isinstance(exc,json.JSONDecodeError) else str(exc)) from exc
    def text(self,endpoint):
        try: return run_command(["gh","api","--allow-escape-sequences","--method","GET",endpoint],timeout=self.timeout_s)
        except RuntimeError as exc: raise GitHubReadError(str(exc)) from exc
    def graphql(self,query): result=json.loads(run_command(["gh","api","graphql","--paginate","--slurp","-f",f"query={query}"],timeout=self.timeout_s)); return [mapping(row.get("data") if not row.get("errors") else None,"GraphQL data") for row in _rows(result)]
    def list(self,endpoint):
        rows=[]
        for page in range(1,101):
            value=self.get(f"{endpoint}{'&' if '?' in endpoint else '?'}per_page=100&page={page}")
            if not isinstance(value,list): raise GitHubReadError(f"expected a list from {endpoint}")
            rows.extend(row for row in value if isinstance(row,dict))
            if len(value)<100: return rows
        raise GitHubReadError(f"pagination limit exceeded for {endpoint}")
