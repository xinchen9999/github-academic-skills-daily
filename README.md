# GitHub 科研学术 Agent Skills 每日推荐

这个小项目每天检索 GitHub 上与科研学术相关的 Agent Skills 仓库，去重后按累计 Star 数从高到低列出前十名。

## 现有类似项目

GitHub 上已经有学术 Agent Skills 清单和通用 Agent Skills 目录，但检索时没有找到一个专门每天更新“科研学术 Skills 前十名、按累计 Star 排序”的自动榜单。本项目把目录检索和每日榜单更新合并起来。

## 每日运行

`.github/workflows/daily-recommendations.yml` 配置为每天北京时间 08:05 执行，也可以在 GitHub 仓库的 **Actions** 页面手动运行。成功后：

- `latest.md` 保存最新榜单。
- `reports/YYYY-MM-DD.md` 按日期保留历史榜单。

将本目录内容放入一个 GitHub 仓库并推送到默认分支，然后在仓库设置中启用 Actions。工作流会用仓库自带的 `GITHUB_TOKEN` 更新榜单文件，不需要额外 API 密钥。

## 本地生成

需要 Python 3.10 或更高版本。运行：

```powershell
python recommend.py
```

可选参数：

```powershell
python recommend.py --output-dir . --date 2026-09-29
```

## 搜索和排名规则

- 搜索 academic、research、scientific 与 skills / agent skills 的组合关键词；查询内容包含仓库 README。
- 合并重复仓库，排除 fork 和已归档仓库。
- 要求仓库名称或简介明确出现 Skills，并用名称、简介和 topics 检查科研学术领域与 AI Agent 信号，排除仅在 README 中顺带提到科研技能的通用项目。
- 依 `stargazers_count` 降序排序，取前十；同 Star 数时按仓库名排序。
- Star 数是 GitHub 累计值，不代表过去一天新增 Star；每日更新用于提供当日榜单快照。

GitHub 搜索索引和关键词会影响召回率；这份榜单适合发现项目，使用前仍应查看仓库内容、许可证和维护状态。

