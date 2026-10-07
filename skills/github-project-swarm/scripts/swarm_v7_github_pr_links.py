# PR linkage is derived from native closure references or same-repository timeline cross-references.
# Closed issues accept only merged closure/timeline candidates.
# Multiple open linked PRs are ambiguous and fail closed.
# Branch filtering is deterministic and never treats an unmerged closed PR as completion.
from swarm_v7_github_scalars import UnsafeGitHubObservation,_rows,mapping,nested_text,positive_int
def _labels(value): return {str(row.get("name") if isinstance(row,dict) else row).lower() for row in value} if isinstance(value,list) else set()
def _same_repo(issue,repo): value=str(issue.get("repository_url") or "").rstrip("/"); return not value or value==f"https://api.github.com/repos/{repo}"
def _closure_pr_ok(pr,number): return positive_int(pr.get("number"),"PR number")==number and bool(pr.get("merged_at"))
def _closure_pr(reader,repo,node): node=mapping(node,"closure reference"); number=positive_int(node.get("number"),"closure PR number"); pr=mapping(reader.get(f"repos/{repo}/pulls/{number}"),f"PR {number}") if nested_text(node,"repository","nameWithOwner")==repo and node.get("merged") else mapping(None,"valid closure reference"); return pr if _closure_pr_ok(pr,number) else mapping(None,"confirmed closure PR")
def _closure_prs(reader,repo,issue): owner,name=repo.split("/",1); query=f'query($endCursor:String){{repository(owner:"{owner}",name:"{name}"){{issue(number:{issue}){{closedByPullRequestsReferences(first:100,after:$endCursor){{nodes{{number,merged,repository{{nameWithOwner}}}} pageInfo{{hasNextPage,endCursor}}}}}}}}}}'; pages=reader.graphql(query); pages=[pages] if isinstance(pages,dict) else _rows(pages); nodes=[node for data in pages for node in _rows(mapping(mapping(mapping(data.get("repository"),"repository").get("issue"),"issue").get("closedByPullRequestsReferences"),"closure references").get("nodes"))]; return None if not nodes else [_closure_pr(reader,repo,node) for node in nodes if node.get("merged")]
def _cross_reference(event,repo): source=event.get("source") if event.get("event")=="cross-referenced" else None; linked=source.get("issue") if isinstance(source,dict) else None; return positive_int(linked.get("number"),"linked PR number") if isinstance(linked,dict) and _same_repo(linked,repo) and isinstance(linked.get("pull_request"),dict) else None
def _timeline_prs(reader,repo,issue): numbers={number for event in reader.list(f"repos/{repo}/issues/{issue}/timeline") if (number:=_cross_reference(event,repo)) is not None}; return [mapping(reader.get(f"repos/{repo}/pulls/{number}"),f"PR {number}") for number in sorted(numbers)]
def _linked_prs(reader,repo,issue,issue_state=None,branch=None): prs=_closure_prs(reader,repo,issue) if issue_state=="CLOSED" else None; return ([pr for pr in _branch_prs(_timeline_prs(reader,repo,issue),branch) if pr.get("merged_at")] if issue_state=="CLOSED" else _timeline_prs(reader,repo,issue)) if prs is None else prs
def _branch_prs(prs,branch): return prs if branch is None else [pr for pr in prs if isinstance(pr.get("head"),dict) and pr["head"].get("ref")==branch]
def _select_pr(prs,branch=None):
    prs=_branch_prs(prs,branch); opened=[pr for pr in prs if str(pr.get("state") or "").lower()=="open"]
    if len(opened)>1: raise UnsafeGitHubObservation("multiple open PRs are linked to the issue")
    return next(iter(opened),max((pr for pr in prs if pr.get("merged_at")),key=lambda pr:str(pr.get("merged_at")),default=None))
def _merged_at(reader,repo,issue,branch=None): return max((str(pr["merged_at"]) for pr in _branch_prs(_linked_prs(reader,repo,issue),branch) if pr.get("merged_at")),default=None)
