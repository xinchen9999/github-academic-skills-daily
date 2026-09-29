#!/usr/bin/env python3
"""Build a daily top-10 list of academic and research agent-skill repositories."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


API_URL = "https://api.github.com/search/repositories"
API_VERSION = "2022-11-28"
TIMEZONE = ZoneInfo("Asia/Shanghai")
RESULTS_PER_QUERY = 100
TOP_N = 10

# The queries search repository READMEs. Metadata checks below remove obvious
# mismatches; several queries broaden discovery, and duplicate repos are merged
# before the final total-star ranking.
SEARCH_QUERIES = (
    "academic skills in:readme",
    "scientific skills in:readme",
    "scholarly skills in:readme",
    "literature review skills in:readme",
    "academic agent skills in:readme",
    "scientific agent skills in:readme",
    "AI research skills in:readme",
    "peer review skills agent in:readme",
)

ACADEMIC_RE = re.compile(
    r"\bacademic\b|\bscientific\b|\bscience\b|scholarly|scholar|"
    r"literature.review|literature.search|paper.writing|manuscript|peer.review|"
    r"citation.audit|citation.management|bibliograph|dissertation|\bthesis\b|"
    r"bioinformatics|clinical.research|study.design|grant.writing|"
    r"research.methodology|empirical.research|scientific.research|"
    r"machine.learning.research|\bML research\b|\bAI research\b|social.science",
    re.IGNORECASE,
)
SKILL_RE = re.compile(r"\bskills?\b", re.IGNORECASE)
AGENT_RE = re.compile(
    r"agent|artificial intelligence|\bAI\b|\bLLM\b|claude|codex|cursor|gemini|"
    r"copilot|anthropic|openai|model.context.protocol|\bMCP\b|skills\.sh",
    re.IGNORECASE,
)


def github_search(query: str, token: str | None) -> dict[str, Any]:
    params = urlencode(
        {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": RESULTS_PER_QUERY,
        }
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "github-academic-skills-daily/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(f"{API_URL}?{params}", headers=headers)
    for attempt in range(4):
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            if error.code in (403, 429) and attempt < 3:
                retry_after = error.headers.get("Retry-After")
                delay = int(retry_after) if retry_after and retry_after.isdigit() else 2**attempt * 5
                time.sleep(min(delay, 60))
                continue
            raise RuntimeError(f"GitHub API returned HTTP {error.code}: {body[:500]}") from error
        except (TimeoutError, URLError) as error:
            if attempt < 3:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"Could not reach GitHub API: {error}") from error
    raise RuntimeError("GitHub API request failed after retries")


def discover(token: str | None) -> list[dict[str, Any]]:
    repositories: dict[str, dict[str, Any]] = {}

    for query in SEARCH_QUERIES:
        payload = github_search(query, token)
        for repo in payload.get("items", []):
            if repo.get("visibility") != "public" or repo.get("fork") or repo.get("archived"):
                continue

            full_name = repo.get("full_name")
            if not full_name:
                continue

            name_and_description = " ".join(
                str(value or "")
                for value in (
                    repo.get("name"),
                    repo.get("description"),
                )
            )
            searchable_text = " ".join((name_and_description, " ".join(repo.get("topics") or [])))
            # The query has already found academic/research + skills language
            # in the repository README. This metadata check filters obvious
            # collisions such as human study-skills repositories.
            if (
                not ACADEMIC_RE.search(searchable_text)
                or not SKILL_RE.search(name_and_description)
                or not AGENT_RE.search(searchable_text)
            ):
                continue

            existing = repositories.get(full_name)
            if existing is None or repo.get("stargazers_count", 0) > existing.get("stargazers_count", 0):
                repo["matched_queries"] = [query]
                repositories[full_name] = repo
            elif query not in existing["matched_queries"]:
                existing["matched_queries"].append(query)
        time.sleep(1)

    return sorted(
        repositories.values(),
        key=lambda repo: (-repo.get("stargazers_count", 0), repo["full_name"].casefold()),
    )[:TOP_N]


def render_report(repositories: list[dict[str, Any]], report_date: str) -> str:
    if not repositories:
        raise RuntimeError(
            "No repositories passed the relevance filter. The existing report was left unchanged."
        )

    lines = [
        f"# 科研学术 Agent Skills 每日推荐（{report_date}）",
        "",
        "按 GitHub 总 Star 数从高到低排序。以下为公开、未归档且非 fork 的仓库。",
        "",
        f"检索时间：{datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M')}（Asia/Shanghai）  ",
        f"检索范围：GitHub Repository Search，合并 {len(SEARCH_QUERIES)} 组关键词，去重后取前 {TOP_N}。",
        "",
        "| 排名 | 仓库 | Stars | 简介 |",
        "|---:|---|---:|---|",
    ]

    for rank, repo in enumerate(repositories, start=1):
        full_name = repo["full_name"]
        url = repo.get("html_url") or f"https://github.com/{full_name}"
        stars = repo.get("stargazers_count", 0)
        description = (repo.get("description") or "（仓库未提供简介）").replace("|", "\\|").replace("\n", " ").strip()
        lines.append(f"| {rank} | [{full_name}]({url}) | {stars:,} | {description} |")

    lines.extend(
        [
            "",
            "> 排名反映生成时的累计 Star 数；GitHub 定时任务可能因平台负载延迟。关键词和筛选规则见 [README](README.md)。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=".", help="Directory where latest.md and dated reports are written")
    parser.add_argument("--date", help="Report date in YYYY-MM-DD format; defaults to today's Shanghai date")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    report_date = args.date or datetime.now(TIMEZONE).date().isoformat()
    try:
        datetime.strptime(report_date, "%Y-%m-%d")
        repositories = discover(os.environ.get("GITHUB_TOKEN"))
        report = render_report(repositories, report_date)
        dated_report = output_dir / "reports" / f"{report_date}.md"
        latest_report = output_dir / "latest.md"
        dated_report.parent.mkdir(parents=True, exist_ok=True)
        dated_report.write_text(report, encoding="utf-8")
        latest_report.write_text(report, encoding="utf-8")
    except (ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {dated_report} and {latest_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

