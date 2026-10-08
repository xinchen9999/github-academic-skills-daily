# GitHub 科研学术 Agent Skills 每日榜单

每天检索 GitHub 上与科研学术相关的 Agent Skills 仓库，并生成两份前十榜单：累计 Star 数排名，以及近一日新增 Star 数排名。

## 榜单与数据

- `latest.md`：当天的累计 Star 前十和近一日新增 Star 前十。
- `reports/YYYY-MM-DD.md`：按日期保存的榜单历史。
- `data/star-snapshots.json`：保留连续日期的候选仓库 Star 快照，用于计算升星数。

近一日榜按前后两次每日快照的 Star 总数差值排序，定时运行时间为北京时间 08:05，因此比较区间约为 24 小时。只比较两次都检索到的仓库；新发现的仓库要连续积累两次快照后才进入升星榜。首次运行建立基线，下一次每日运行开始产生单日增量。

## 自动运行

`.github/workflows/daily-recommendations.yml` 配置每天北京时间 08:05 运行，也可在 GitHub 仓库 **Actions** 页面手动运行。更新工作流或推荐脚本时也会触发一次运行，以建立或刷新快照基线。

将工作流放在默认分支并启用 GitHub Actions。工作流使用仓库自带的 `GITHUB_TOKEN` 提交榜单和快照，不需要额外 API 密钥。

## 本地生成

需要 Python 3.10 或更高版本：

```powershell
python recommend.py
```

可选参数：

```powershell
python recommend.py --output-dir . --date 2026-10-08
```

## 搜索和排名规则

- 搜索 academic、scientific、scholarly、literature review、AI research 等组合关键词，检索仓库 README。
- 合并重复仓库，排除 fork、已归档仓库和非公开仓库。
- 要求仓库名称或简介明确出现 Skills，并用名称、简介和 topics 检查科研学术领域与 AI Agent 信号。
- 累计榜按 `stargazers_count` 降序；升星榜按两个快照的 Star 增量降序；并列时先按当前 Star 总数，再按仓库名排序。
- 每个搜索词最多采集 100 个结果。GitHub 搜索索引和关键词会影响召回率；使用前仍应查看仓库内容、许可证和维护状态。
