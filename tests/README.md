# article_manager tests

The executable regression tests for this standalone plugin currently live in the host project at `test/plugins/article_manager/` so they can use the Neo-MoFox test fixtures and plugin loader.

Run from the Neo-MoFox project root:

```bash
uv run pytest test/plugins/article_manager
```
