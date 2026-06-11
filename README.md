# article_manager

小说的创建、管理、编写、审阅、发布。目前只支持番茄小说。

依赖 [`novel_writer`](http://39.96.71.162/plugin/novel_writer) 插件提供正文生成能力。

## 命令总览

```text
/小说 help
/小说 status                              — 查询账号/作品/发布记录概括
/小说 works                              — 列出本地作品
/小说 accounts                           — 列出番茄账号与登录态状态
/小说 records                            — 列出发布记录
/小说 remote-status <作品> [账号标签]    — 查看番茄线上作品/章节状态

/小说 bind <标签> <state路径> [auto]     — 绑定番茄登录态，auto 允许自动发布
/小说 create <标题> [简介]               — 创建本地作品
/小说 remote-create <作品> [账号标签]    — 在番茄后台创建作品并自动绑定
/小说 link <作品> <番茄作品ID>           — 手动绑定本地作品到番茄后台

/小说 generate <作品> <要求>             — 生成新章草稿
/小说 continue <作品> [续写要求]         — 续写新章草稿
/小说 genpub <作品> <要求> [账号标签]    — 续写并尝试发布
/小说 publish <章节|作品> [账号标签]     — 发布已有章节或最新章节
/小说 preview <作品> [latest|all|章节]   — 用合并转发预览章节正文
/小说 schedule <作品> <间隔s> <延迟s> <auto|draft> <账号> <要求>
```

别名：`/文章`、`/article`；`preview` 支持中文「预览」「查看正文」；`remote-status` 支持「线上状态」「番茄状态」。

## 快速开始

### 1. 导出番茄登录态

确保已安装 Playwright Chromium：

```bash
uv run python -m playwright install chromium
```

运行内置导出脚本，在打开的浏览器中登录番茄作者后台，完成后按 Enter 保存：

```bash
uv run python plugins/article_manager/scripts/export_fanqie_state.py
```

输出路径默认为 `data/plugins/article_manager/sessions/fanqie_storage_state.json`。

### 2. 绑定账号

```text
/小说 bind qf data/plugins/article_manager/sessions/fanqie_storage_state.json auto
```

不带 `auto` 只绑定登录态，带 `auto` 才允许自动发布。

### 3. 创建作品并绑定番茄

```text
/小说 create 长夜与三月的日常 日常同人短篇
/小说 remote-create 长夜与三月的日常 qf
```

`remote-create` 为后台任务，会打开番茄后台创建作品并自动写回远端作品 ID。

### 4. 续写并发布

```text
/小说 genpub 长夜与三月的日常 写一章温馨互动，正文不少于两千字 qf
```

### 5. 查看线上状态

```text
/小说 remote-status 长夜与三月的日常 qf
```

## 发布质量门禁

发布前强制校验：

- 章节标题 ≥ 5 个字
- 正文 > 1000 字

不达标会直接失败，不进入浏览器发布流程。

## 组件

- `article_manager:service:article_library` — 作品、章节、账号、定时任务和发布记录管理
- `article_manager:service:article_orchestrator` — 生成、续写、草稿保存、发布编排
- `article_manager:service:fanqie_platform` — 番茄登录态校验和平台操作
- `article_manager:command:article` — 确定性命令入口
- `article_manager:action:manage_article` — LLM 可调用的文章管理动作
- `article_manager:tool:article_status` — LLM 可查询的文章状态工具

## 安全与约束

- 所有数据按 `owner_person_id` 隔离，不跨用户可见
- 番茄登录态通过 Playwright `storage_state.json` 读写，插件不保存账号密码
- `fanqie.kill_switch=true` 阻止所有番茄发布/创建
- `fanqie.auto_publish_enabled=false` 阻止自动发布
- 第一版不支持远端删除

## 存储

- 数据库：`data/plugins/article_manager/article_manager.db`
- 登录态：`data/plugins/article_manager/sessions/`
- 调试产物：`data/plugins/article_manager/artifacts/`

## 依赖

- 插件依赖：[`novel_writer`](http://39.96.71.162/plugin/novel_writer) (>= 1.2.0)
- Python 依赖：`playwright >= 1.49.0`（自动安装）
- 浏览器二进制：需手动执行 `playwright install chromium`
