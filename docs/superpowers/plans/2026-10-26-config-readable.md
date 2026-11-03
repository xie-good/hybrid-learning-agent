# 配置可读性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将配置改成普通默认值与显式环境读取，保留功能并交付完整验证。

**Architecture:** 保留单一 `Settings` 数据类，使用 `from_env()` 集中加载。三个生产调用点显式加载，测试及服务仍可注入数据类。

**Tech Stack:** Python、dataclasses、python-dotenv、unittest、FastAPI、Streamlit。

**Spec:** `F:/桌面/毕设/docs/superpowers/specs/2026-10-26-config-readable-design.md`

## Global Constraints

- 保留 `Settings` 数据类、现有 14 个字段、默认值和环境变量名，不增加依赖。
- 不引入嵌套配置类、反射、动态字段映射或配置框架。
- 本轮只简化配置及其调用入口，不改检索算法、接口契约、预处理结果或实际 `.env`。
- 保存当前未提交代码，不将历史修改重置、暂存或混入提交。

## Review Focus

- 检查所有生产构造入口，避免服务启动或索引任务漏读环境变量。
- 检查相对、绝对、用户目录和空路径，保持原有定位规则。
- 检查显式注入及 `replace()` 在异常环境变量下仍然可用。
- 检查空字符串、非数字、NaN、无穷和边界超时的校验。
- 检查 `.env` 加载优先级和时机，不向文档或产物复制实际密钥。

## Task 1: 配置、入口、文档与回归

**Files:** 修改 `backend/config.py`、`backend/main.py`、`pipeline/build_index.py`、`README.md`、`.env.example`；创建 `tests/test_config.py`。

**Interfaces:** 消费既有配置字段和构造参数；产出 `Settings.from_env() -> Settings`，保留服务及 HTTP 接口。

- [x] 保存当前版本副本和原始配置 SHA256，运行原有测试。
  - Run: `python -B -m unittest discover -s tests -v`
  - Expected: 146 个测试通过。
- [x] 先编写默认值、环境覆盖、路径、校验、显式注入和索引入口测试。
  - Run: `python -B -m unittest tests.test_config.SettingsTests.test_constructor_is_independent_of_environment -v`
  - Expected: 当前配置被环境覆盖，断言失败。
- [x] 实现普通数据类默认值和 `from_env()`，适配三个调用点，更新中文配置说明。
  - Run: `python -B -m unittest tests.test_config -v`
  - Expected: 新增配置测试全部通过。
- [x] 运行全量回归和真实 HTTP 冒烟；独立代码审查。
  - Run: `python -B -m unittest discover -s tests -v`
  - Expected: 全部通过。
  - Run: `python -B tools/smoke_api.py --start-local --with-frontend --output <证据路径>`
  - Expected: 13 个操作、11 条路由、12 章、759 块、前端 HTTP 就绪。
- [x] 生成变更包、补丁、验证记录、回滚脚本；在另一个副本执行回滚并复测。
  - Expected: 原始哈希与旧行为恢复，工作项目保持新代码。
- [x] 将本轮通过验证的文件同步主项目，检查最终哈希和全量测试，不自动提交历史修改。
