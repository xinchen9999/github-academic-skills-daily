#!/usr/bin/env python3
"""Build a daily top-10 list of academic and research agent-skill repositories."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
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
            # The README query discovers candidates; metadata checks keep the
            # daily snapshots focused on academic skills for AI agents.
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
    )


def update_star_snapshots(
    snapshot_path: Path,
    repositories: list[dict[str, Any]],
    report_date: str,
) -> tuple[list[dict[str, Any]], str, str | None, str]:
    current_date = date.fromisoformat(report_date)
    previous_date = (current_date - timedelta(days=1)).isoformat()
    current_captured_at = datetime.now(TIMEZONE).isoformat(timespec="seconds")

    if snapshot_path.exists():
        try:
            saved = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Could not read star snapshot data: {error}") from error
        if not isinstance(saved, dict) or not isinstance(saved.get("snapshots", {}), dict):
            raise RuntimeError("Star snapshot data has an unsupported format.")
        snapshots = saved.get("snapshots", {})
    else:
        snapshots = {}

    previous = snapshots.get(previous_date)
    previous_repositories = previous.get("repositories", {}) if isinstance(previous, dict) else {}
    growth: list[dict[str, Any]] = []

    if previous_repositories:
        for repo in repositories:
            full_name = repo["full_name"]
            old_stars = previous_repositories.get(full_name)
            if old_stars is None:
                continue
            increase = repo.get("stargazers_count", 0) - old_stars
            if increase > 0:
                item = repo.copy()
                item["daily_growth"] = increase
                growth.append(item)

    growth.sort(
        key=lambda repo: (
            -repo["daily_growth"],
            -repo.get("stargazers_count", 0),
            repo["full_name"].casefold(),
        )
    )

    today = {
        repo["full_name"]: repo.get("stargazers_count", 0)
        for repo in repositories
    }
    snapshots[report_date] = {
        "captured_at": current_captured_at,
        "repositories": today,
    }
    keep_dates = {previous_date, report_date}
    snapshots = {day: value for day, value in snapshots.items() if day in keep_dates}

    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = snapshot_path.with_suffix(snapshot_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps({"snapshots": snapshots}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(snapshot_path)

    return (
        growth[:TOP_N],
        previous_date,
        previous.get("captured_at") if isinstance(previous, dict) else None,
        current_captured_at,
    )


def render_repository_table(
    repositories: list[dict[str, Any]],
    star_column: str,
    star_value_key: str,
    include_current_stars: bool = False,
) -> list[str]:
    if include_current_stars:
        lines = [
            f"| 排名 | 仓库 | {star_column} | 当前总 Stars | 简介 |",
            "|---:|---|---:|---:|---|",
        ]
    else:
        lines = [
            f"| 排名 | 仓库 | {star_column} | 简介 |",
            "|---:|---|---:|---|",
        ]

    for rank, repo in enumerate(repositories[:TOP_N], start=1):
        full_name = repo["full_name"]
        url = repo.get("html_url") or f"https://github.com/{full_name}"
        stars = repo.get(star_value_key, 0)
        description = (repo.get("description") or "（仓库未提供简介）").replace("|", "\\|").replace("\n", " ").strip()
        if include_current_stars:
            lines.append(
                f"| {rank} | [{full_name}]({url}) | {stars:,} | "
                f"{repo.get('stargazers_count', 0):,} | {description} |"
            )
        else:
            lines.append(f"| {rank} | [{full_name}]({url}) | {stars:,} | {description} |")
    return lines


def render_report(
    repositories: list[dict[str, Any]],
    growth: list[dict[str, Any]],
    report_date: str,
    previous_date: str,
    previous_captured_at: str | None,
    current_captured_at: str,
) -> str:
    if not repositories:
        raise RuntimeError(
            "No repositories passed the relevance filter. The existing report was left unchanged."
        )

    lines = [
        f"# 科研学术 Agent Skills 每日推荐（{report_date}）",
        "",
        "以下榜单只包含公开、未归档且非 fork 的科研学术 Agent Skills 仓库。",
        "",
        f"检索时间：{current_captured_at}（Asia/Shanghai）  ",
        f"检索范围：GitHub Repository Search，合并 {len(SEARCH_QUERIES)} 组关键词。",
        "",
        "## 累计 Star 前十",
        "",
        "按当前累计 Star 数从高到低排序。",
    ]
    lines.extend(render_repository_table(repositories, "总 Stars", "stargazers_count"))
    lines.extend(["", "## 近一日新增 Star 前十", ""])

    if previous_captured_at:
        lines.append(
            f"按 {previous_date} 与 {report_date} 两次快照的累计 Star 差值排序；比较时段约为 24 小时。"
        )
        if growth:
            lines.extend(
                render_repository_table(
                    growth,
                    "新增 Stars",
                    "daily_growth",
                    include_current_stars=True,
                )
            )
        else:
            lines.append("已追踪的仓库在两次快照之间暂无 Star 增长。")
    else:
        lines.append(
            "正在建立第一份 Star 基线；从下一次每日运行开始，将对连续两天均检索到的仓库计算新增 Star。"
        )

    lines.extend(
        [
            "",
            "> 新发现的仓库需积累连续两天的数据后才进入升星榜。Star 数来自 GitHub 仓库搜索结果；关键词和筛选规则见 [README](README.md)。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=".", help="Directory where reports and snapshot data are written")
    parser.add_argument("--date", help="Report date in YYYY-MM-DD format; defaults to today's Shanghai date")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    report_date = args.date or datetime.now(TIMEZONE).date().isoformat()
    try:
        datetime.strptime(report_date, "%Y-%m-%d")
        repositories = discover(os.environ.get("GITHUB_TOKEN"))
        if not repositories:
            raise RuntimeError(
                "No repositories passed the relevance filter. The existing report was left unchanged."
            )
        growth, previous_date, previous_captured_at, current_captured_at = update_star_snapshots(
            output_dir / "data" / "star-snapshots.json",
            repositories,
            report_date,
        )
        report = render_report(
            repositories,
            growth,
            report_date,
            previous_date,
            previous_captured_at,
            current_captured_at,
        )
        dated_report = output_dir / "reports" / f"{report_date}.md"
        latest_report = output_dir / "latest.md"
        dated_report.parent.mkdir(parents=True, exist_ok=True)
        dated_report.write_text(report, encoding="utf-8")
        latest_report.write_text(report, encoding="utf-8")
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {dated_report}, {latest_report}, and the star snapshot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
