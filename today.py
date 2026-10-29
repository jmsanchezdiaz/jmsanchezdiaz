import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import requests

USER = "jmsanchezdiaz"
BIRTHDAY = date(2002, 5, 11)  # date(AAAA, M, D) -> completar para el "Uptime"; si es None no se toca
SVGS = ["dark_mode.svg", "light_mode.svg"]
CACHE = Path("cache/loc.json")
API = "https://api.github.com/graphql"
HEADERS = {"Authorization": f"bearer {os.environ['ACCESS_TOKEN']}"}


def gql(query, variables=None):
    r = requests.post(API, json={"query": query, "variables": variables or {}},
                      headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def user_info():
    q = """query($login:String!){user(login:$login){
        id createdAt followers{totalCount}
        repositoriesContributedTo(first:1,contributionTypes:[COMMIT,ISSUE,PULL_REQUEST,REPOSITORY]){totalCount}}}"""
    u = gql(q, {"login": USER})["user"]
    return u["id"], u["createdAt"], u["followers"]["totalCount"], u["repositoriesContributedTo"]["totalCount"]


def repos_stars_langs():
    q = """query($login:String!,$cursor:String){user(login:$login){
        repositories(first:100,after:$cursor,ownerAffiliations:OWNER){
            totalCount
            pageInfo{hasNextPage endCursor}
            nodes{stargazerCount isFork
                languages(first:5,orderBy:{field:SIZE,direction:DESC}){edges{size node{name}}}}}}}"""
    cursor, stars, total, langs = None, 0, 0, {}
    while True:
        repos = gql(q, {"login": USER, "cursor": cursor})["user"]["repositories"]
        total = repos["totalCount"]
        for n in repos["nodes"]:
            stars += n["stargazerCount"]
            if n["isFork"]:
                continue
            for e in n["languages"]["edges"]:
                langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]
        if not repos["pageInfo"]["hasNextPage"]:
            top = sorted(langs, key=langs.get, reverse=True)[:5]
            return total, stars, top
        cursor = repos["pageInfo"]["endCursor"]


def total_commits(created_at):
    q = """query($login:String!,$from:DateTime!,$to:DateTime!){user(login:$login){
        contributionsCollection(from:$from,to:$to){
            totalCommitContributions restrictedContributionsCount}}}"""
    total = 0
    for year in range(int(created_at[:4]), datetime.now(timezone.utc).year + 1):
        c = gql(q, {"login": USER, "from": f"{year}-01-01T00:00:00Z",
                    "to": f"{year}-12-31T23:59:59Z"})["user"]["contributionsCollection"]
        total += c["totalCommitContributions"] + c["restrictedContributionsCount"]
    return total


def repo_commit_counts(uid):
    """nameWithOwner -> cantidad de commits propios en la rama por defecto."""
    q = """query($cursor:String,$uid:ID!){viewer{repositories(first:50,after:$cursor,
        ownerAffiliations:[OWNER,COLLABORATOR,ORGANIZATION_MEMBER]){
        pageInfo{hasNextPage endCursor}
        nodes{nameWithOwner defaultBranchRef{target{... on Commit{
            history(author:{id:$uid}){totalCount}}}}}}}}"""
    out, cursor = {}, None
    while True:
        repos = gql(q, {"cursor": cursor, "uid": uid})["viewer"]["repositories"]
        for n in repos["nodes"]:
            ref = n["defaultBranchRef"]
            if ref and ref["target"]:
                out[n["nameWithOwner"]] = ref["target"]["history"]["totalCount"]
        if not repos["pageInfo"]["hasNextPage"]:
            return out
        cursor = repos["pageInfo"]["endCursor"]


def repo_loc(name_with_owner, uid):
    owner, name = name_with_owner.split("/")
    q = """query($owner:String!,$name:String!,$uid:ID!,$cursor:String){
        repository(owner:$owner,name:$name){defaultBranchRef{target{... on Commit{
            history(first:100,after:$cursor,author:{id:$uid}){
                pageInfo{hasNextPage endCursor} nodes{additions deletions}}}}}}}"""
    add = dele = 0
    cursor = None
    while True:
        h = gql(q, {"owner": owner, "name": name, "uid": uid,
                    "cursor": cursor})["repository"]["defaultBranchRef"]["target"]["history"]
        for n in h["nodes"]:
            add += n["additions"]
            dele += n["deletions"]
        if not h["pageInfo"]["hasNextPage"]:
            return add, dele
        cursor = h["pageInfo"]["endCursor"]


def lines_of_code(uid):
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    counts = repo_commit_counts(uid)
    new_cache = {}
    for repo, commits in counts.items():
        old = cache.get(repo)
        if old and old["commits"] == commits:        # sin commits nuevos: usar cache
            new_cache[repo] = old
            continue
        add, dele = repo_loc(repo, uid)
        new_cache[repo] = {"commits": commits, "add": add, "del": dele}
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(new_cache, indent=1, sort_keys=True))
    add = sum(v["add"] for v in new_cache.values())
    dele = sum(v["del"] for v in new_cache.values())
    return add, dele


def uptime(born):
    today = date.today()
    years = today.year - born.year
    months = today.month - born.month
    days = today.day - born.day
    if days < 0:
        months -= 1
        prev_month_days = (date(today.year, today.month, 1) - date.resolution).day
        days += prev_month_days
    if months < 0:
        years -= 1
        months += 12
    return f"{years} years, {months} months, {days} days"


def update_svg(path, values):
    with open(path, encoding="utf-8") as f:
        svg = f.read()
    for tag_id, text in values.items():
        svg = re.sub(rf'(<tspan[^>]*id="{tag_id}"[^>]*>)[^<]*(</tspan>)',
                     lambda m: f"{m.group(1)}{text}{m.group(2)}", svg)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)


if __name__ == "__main__":
    uid, created_at, followers, contributed = user_info()
    repos, stars, langs = repos_stars_langs()
    add, dele = lines_of_code(uid)
    values = {
        "repo_data": f" {repos:,}",
        "contrib_data": f"{contributed:,}",
        "commit_data": f" {total_commits(created_at):,}",
        "star_data": f" {stars:,}",
        "follower_data": f" {followers:,}",
        "loc_data": f" {add - dele:,}",
        "loc_add": f"{add:,}",
        "loc_del": f"{dele:,}",
        "lang_data": " " + ", ".join(langs),
    }
    if BIRTHDAY:
        values["age_data"] = " " + uptime(BIRTHDAY)
    for svg in SVGS:
        update_svg(svg, values)
    print(values)
