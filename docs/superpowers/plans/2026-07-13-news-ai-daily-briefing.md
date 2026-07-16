# 新闻 AI 与每日简报实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Use checkbox steps and TDD.

**Goal:** 生成有来源、可追溯、可降级的盘前简报、盘中事件流和盘后复盘。

**Architecture:** 工部采集和去重新闻，确定性规则完成时间、标的、行业和来源校验；AI 网关只做文本分类、摘要、影响方向和新手解释。量化数据以结构化字段输入，模型不可自行计算价格指标或绕过风控。

## Tasks

### Task 1: 新闻与证据契约
- Define immutable article, normalized event, evidence citation and AI interpretation.
- Preserve URL, publisher, published time, fetched time, content hash and raw snapshot.
- Tests reject interpretations without citations or with future timestamps.

### Task 2: 采集、去重与关联
- Implement source adapters with per-source rate limits and retry policy.
- Deduplicate by canonical URL, content hash and near-duplicate title; preserve all source links.
- Map events to A shares, industries and themes with confidence and review state.

### Task 3: Mixed AI gateway
- Define provider-neutral interface for cloud and local models.
- Require JSON schema output; invalid output retries once then degrades to deterministic summary.
- Redact API keys from logs; store provider, model, prompt version and latency.

### Task 4: Daily workflows
- Preshare: overnight events, policy, risks and evidence-backed watchlist.
- Intraday: new event stream, duplicate suppression and affected-watchlist update.
- Postclose: signal outcomes, errors, risk events and next-day observations.
- Every report freezes its input snapshot and cannot be rewritten by later news.

### Task 5: UI and evaluation
- Add timeline, evidence drawer, contrary evidence and uncertainty display.
- Separate facts, model interpretation, quantitative result and risk decision visually.
- Track citation coverage, duplicate rate, invalid JSON rate and human correction rate.

## Acceptance

- Model outage still leaves deterministic market data and raw news usable.
- No strong signal is created from an unverified source.
- Every AI sentence in a decision card links to evidence or is labeled interpretation.
- API keys never appear in database rows, logs or browser responses.
