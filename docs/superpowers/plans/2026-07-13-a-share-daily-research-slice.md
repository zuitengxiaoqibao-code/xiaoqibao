# A 股每日研究纵向切片实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可在 Windows 本地运行的前后端工程，并用真实 A 股行情打通“工部采集 → 中书省摘要 → 刑部降级 → 情报中枢展示”的第一个可验证纵向切片。

**Architecture:** 单仓库包含 React 前端和 FastAPI 后端。后端按部门和资产域拆分模块，使用显式 Pydantic 契约通信；首个切片接入腾讯免费行情，SQLite 保存采集与审计记录，前端只消费后端 API。可转债仅注册为隔离资产域，不复用 A 股专属解析和评分。

**Tech Stack:** Python 3.12、FastAPI 0.116.1、Pydantic 2.11.7、SQLAlchemy 2.0.41、httpx 0.28.1、pytest 8.4.1、React 19.1.0、TypeScript 5.8.3、Vite 7.0.4、Vitest 3.2.4、pnpm 10。

## Global Constraints

- 仅支持中国 A 股与独立的可转债资产域；不实现期货。
- 第一版不连接券商、不执行真实交易。
- 大模型不得负责行情指标、因子、回测或风控计算。
- 每个结论必须携带数据来源、数据时间、质量状态和失效原因。
- A 股与可转债只共享基础设施和标准契约，不共享资产专属计算。
- 所有中文源码和数据文件使用 UTF-8；修改后扫描连续问号、替换字符和常见乱码片段。
- 本计划只完成首个 A 股纵向切片；完整 V1 后续拆为行情数据平台、研究回测、模拟交易、风险审计、可转债域和 AI 新闻理解六个独立计划。

## File Map

```text
apps/
  api/
    pyproject.toml                  # Python 依赖与 pytest 配置
    src/qibao_api/main.py           # FastAPI 应用装配
    src/qibao_api/settings.py       # 本地路径和运行配置
    src/qibao_api/contracts/market.py
    src/qibao_api/assets/registry.py
    src/qibao_api/gongbu/tencent_quotes.py
    src/qibao_api/gongbu/quality.py
    src/qibao_api/zhongshu/daily_research.py
    src/qibao_api/xingbu/gate.py
    src/qibao_api/shangshu/pipeline.py
    src/qibao_api/storage/database.py
    src/qibao_api/storage/quote_repository.py
    src/qibao_api/routes/health.py
    src/qibao_api/routes/research.py
    tests/                         # 与上述模块一一对应的后端测试
  web/
    package.json
    vite.config.ts
    src/app/App.tsx                # 路由和整体壳层
    src/app/theme.css              # 情报指挥中枢设计令牌
    src/features/dashboard/api.ts
    src/features/dashboard/types.ts
    src/features/dashboard/Dashboard.tsx
    src/features/dashboard/Dashboard.test.tsx
    src/main.tsx
package.json                       # pnpm workspace 命令
pnpm-workspace.yaml
scripts/dev.ps1                    # Windows 一键开发入口
README.md                          # 安装、运行和数据源说明
```

---

### Task 1: 建立可测试的单仓库工程

**Files:**
- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/src/qibao_api/__init__.py`
- Create: `apps/api/src/qibao_api/settings.py`
- Create: `apps/api/tests/test_settings.py`
- Create: `apps/web/package.json`
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/vite.config.ts`
- Create: `apps/web/index.html`

**Interfaces:**
- Produces: `Settings(data_dir: Path, database_url: str)` and workspace commands `test`, `build`, `dev`.

- [ ] **Step 1: Write the failing settings test**

```python
from pathlib import Path

from qibao_api.settings import Settings


def test_settings_places_runtime_data_outside_source(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    assert settings.database_url == f"sqlite:///{(tmp_path / 'qibao.db').as_posix()}"
```

- [ ] **Step 2: Run the test and verify import failure**

Run: `C:\Users\90090\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest apps/api/tests/test_settings.py -v`

Expected: FAIL because `qibao_api.settings` does not exist.

- [ ] **Step 3: Add the backend configuration and dependencies**

```toml
# apps/api/pyproject.toml
[project]
name = "qibao-api"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi==0.116.1",
  "httpx==0.28.1",
  "pydantic==2.11.7",
  "pydantic-settings==2.10.1",
  "sqlalchemy==2.0.41",
  "uvicorn[standard]==0.35.0",
]

[project.optional-dependencies]
dev = ["pytest==8.4.1", "pytest-asyncio==1.1.0", "ruff==0.12.3"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

```python
# apps/api/src/qibao_api/settings.py
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QIBAO_", extra="ignore")
    data_dir: Path = Path(".runtime")

    @computed_field
    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'qibao.db').as_posix()}"
```

- [ ] **Step 4: Add pnpm workspace metadata**

```json
{
  "name": "xiaoqibao",
  "private": true,
  "scripts": {
    "build": "pnpm --filter @qibao/web build",
    "test:web": "pnpm --filter @qibao/web test",
    "dev:web": "pnpm --filter @qibao/web dev"
  }
}
```

```yaml
# pnpm-workspace.yaml
packages:
  - apps/web
```

```json
{
  "name": "@qibao/web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {"dev":"vite","build":"tsc -b && vite build","test":"vitest run"},
  "dependencies": {"@vitejs/plugin-react":"4.6.0","vite":"7.0.4","typescript":"5.8.3","react":"19.1.0","react-dom":"19.1.0"},
  "devDependencies": {"@testing-library/react":"16.3.0","@testing-library/jest-dom":"6.6.3","jsdom":"26.1.0","vitest":"3.2.4","@types/react":"19.1.8","@types/react-dom":"19.1.6"}
}
```

- [ ] **Step 5: Install and verify the baseline**

Run: `C:\Users\90090\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pip install -e "apps/api[dev]"`

Run: `C:\Users\90090\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd install`

Run: `C:\Users\90090\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest apps/api/tests/test_settings.py -v`

Expected: one backend test passes.

- [ ] **Step 6: Commit**

```powershell
git add package.json pnpm-workspace.yaml apps
git commit -m "build: scaffold quant research workspace"
```

### Task 2: 定义资产隔离和市场数据契约

**Files:**
- Create: `apps/api/src/qibao_api/contracts/market.py`
- Create: `apps/api/src/qibao_api/assets/registry.py`
- Create: `apps/api/tests/contracts/test_market.py`
- Create: `apps/api/tests/assets/test_registry.py`

**Interfaces:**
- Produces: `AssetKind`, `Quote`, `DataQuality`, `AssetRegistry.get(kind)`.
- Consumers: all data, research, risk, API and frontend tasks.

- [ ] **Step 1: Write failing contract tests**

```python
from datetime import datetime
from decimal import Decimal

import pytest

from qibao_api.assets.registry import AssetRegistry
from qibao_api.contracts.market import AssetKind, DataQuality, Quote


def test_a_share_and_convertible_bond_are_distinct_domains() -> None:
    registry = AssetRegistry.default()
    assert registry.get(AssetKind.A_SHARE).route_prefix == "/a-shares"
    assert registry.get(AssetKind.CONVERTIBLE_BOND).route_prefix == "/convertible-bonds"


def test_quote_rejects_negative_price() -> None:
    with pytest.raises(ValueError):
        Quote(symbol="600000", asset=AssetKind.A_SHARE, name="浦发银行",
              price=Decimal("-1"), previous_close=Decimal("10"),
              observed_at=datetime.now(), source="tencent",
              quality=DataQuality.FRESH)
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest apps/api/tests/contracts apps/api/tests/assets -v`

Expected: FAIL because contracts and registry are missing.

- [ ] **Step 3: Implement exact contracts**

```python
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class AssetKind(StrEnum):
    A_SHARE = "a_share"
    CONVERTIBLE_BOND = "convertible_bond"


class DataQuality(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    CONFLICTED = "conflicted"
    UNAVAILABLE = "unavailable"


class Quote(BaseModel):
    symbol: str = Field(pattern=r"^\d{6}$")
    asset: AssetKind
    name: str
    price: Decimal = Field(gt=0)
    previous_close: Decimal = Field(gt=0)
    observed_at: datetime
    source: str
    quality: DataQuality
```

```python
from dataclasses import dataclass

from qibao_api.contracts.market import AssetKind


@dataclass(frozen=True)
class AssetDomain:
    kind: AssetKind
    route_prefix: str


class AssetRegistry:
    def __init__(self, domains: dict[AssetKind, AssetDomain]) -> None:
        self._domains = domains

    @classmethod
    def default(cls) -> "AssetRegistry":
        return cls({
            AssetKind.A_SHARE: AssetDomain(AssetKind.A_SHARE, "/a-shares"),
            AssetKind.CONVERTIBLE_BOND: AssetDomain(AssetKind.CONVERTIBLE_BOND, "/convertible-bonds"),
        })

    def get(self, kind: AssetKind) -> AssetDomain:
        return self._domains[kind]
```

- [ ] **Step 4: Run contract tests**

Run: `python -m pytest apps/api/tests/contracts apps/api/tests/assets -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/qibao_api/contracts apps/api/src/qibao_api/assets apps/api/tests
git commit -m "feat: define isolated asset domain contracts"
```

### Task 3: 接入并验证腾讯 A 股实时快照

**Files:**
- Create: `apps/api/src/qibao_api/gongbu/tencent_quotes.py`
- Create: `apps/api/src/qibao_api/gongbu/quality.py`
- Create: `apps/api/tests/gongbu/test_tencent_quotes.py`
- Create: `apps/api/tests/gongbu/test_quality.py`

**Interfaces:**
- Produces: `TencentQuoteSource.fetch(symbol) -> Quote`, `assess_freshness(quote, now, max_age) -> DataQuality`.
- Consumes: `Quote`, `AssetKind`, `DataQuality` from Task 2.

- [ ] **Step 1: Write parser and freshness tests using captured UTF-8-safe fixtures**

```python
from datetime import datetime
from decimal import Decimal

from qibao_api.gongbu.tencent_quotes import parse_tencent_quote


def test_parse_tencent_a_share_quote() -> None:
    fields = [""] * 50
    fields[1], fields[2], fields[3], fields[4], fields[30] = "浦发银行", "600000", "10.25", "10.10", "20260713103000"
    quote = parse_tencent_quote("~".join(fields), source="tencent")
    assert quote.symbol == "600000"
    assert quote.price == Decimal("10.25")
    assert quote.observed_at == datetime(2026, 7, 13, 10, 30)
```

```python
from datetime import datetime, timedelta

from qibao_api.contracts.market import DataQuality
from qibao_api.gongbu.quality import assess_observed_at


def test_old_quote_is_stale() -> None:
    now = datetime(2026, 7, 13, 10, 40)
    assert assess_observed_at(now - timedelta(minutes=10), now, timedelta(minutes=3)) == DataQuality.STALE
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest apps/api/tests/gongbu -v`

Expected: FAIL because the data source does not exist.

- [ ] **Step 3: Implement parser, source and explicit GBK decoding**

```python
from datetime import datetime
from decimal import Decimal

import httpx

from qibao_api.contracts.market import AssetKind, DataQuality, Quote


def market_prefix(symbol: str) -> str:
    return "sh" if symbol.startswith(("5", "6", "9")) else "sz"


def parse_tencent_quote(payload: str, source: str) -> Quote:
    fields = payload.split("~")
    if len(fields) < 31:
        raise ValueError("Tencent quote payload is incomplete")
    return Quote(symbol=fields[2], asset=AssetKind.A_SHARE, name=fields[1],
                 price=Decimal(fields[3]), previous_close=Decimal(fields[4]),
                 observed_at=datetime.strptime(fields[30], "%Y%m%d%H%M%S"),
                 source=source, quality=DataQuality.FRESH)


class TencentQuoteSource:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def fetch(self, symbol: str) -> Quote:
        response = await self.client.get(f"https://qt.gtimg.cn/q={market_prefix(symbol)}{symbol}")
        response.raise_for_status()
        body = response.content.decode("gbk", errors="strict")
        payload = body.split('="', 1)[1].rsplit('"', 1)[0]
        return parse_tencent_quote(payload, "tencent")
```

```python
from datetime import datetime, timedelta

from qibao_api.contracts.market import DataQuality


def assess_observed_at(observed_at: datetime, now: datetime, max_age: timedelta) -> DataQuality:
    age = now - observed_at
    return DataQuality.FRESH if timedelta(0) <= age <= max_age else DataQuality.STALE
```

- [ ] **Step 4: Run unit tests and one opt-in live smoke check**

Run: `python -m pytest apps/api/tests/gongbu -v`

Run: `curl.exe -sS "https://qt.gtimg.cn/q=sh600000"`

Expected: unit tests pass; live check returns a payload containing `600000` or fails visibly with a network/source error.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/qibao_api/gongbu apps/api/tests/gongbu
git commit -m "feat: ingest Tencent A-share quote snapshots"
```

### Task 4: 保存行情与审计记录

**Files:**
- Create: `apps/api/src/qibao_api/storage/database.py`
- Create: `apps/api/src/qibao_api/storage/quote_repository.py`
- Create: `apps/api/tests/storage/test_quote_repository.py`

**Interfaces:**
- Produces: `create_schema(engine)`, `QuoteRepository.save(quote)`, `QuoteRepository.latest(symbol)`.
- Consumes: `Quote` from Task 2 and `Settings.database_url` from Task 1.

- [ ] **Step 1: Write a failing repository round-trip test**

```python
def test_quote_round_trip() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    quote = Quote(symbol="600000", asset=AssetKind.A_SHARE, name="浦发银行",
                  price=Decimal("10.25"), previous_close=Decimal("10.10"),
                  observed_at=datetime(2026, 7, 13, 10, 30), source="tencent",
                  quality=DataQuality.FRESH)
    create_schema(engine)
    repository = QuoteRepository(engine)
    repository.save(quote)
    restored = repository.latest("600000")
    assert restored == quote
```

- [ ] **Step 2: Verify the test fails**

Run: `python -m pytest apps/api/tests/storage/test_quote_repository.py -v`

Expected: FAIL because repository classes are missing.

- [ ] **Step 3: Implement one normalized quote table and repository**

```python
from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table, create_engine

metadata = MetaData()
quotes = Table("quote_snapshots", metadata,
    Column("symbol", String(6), nullable=False, index=True),
    Column("observed_at", DateTime, nullable=False, index=True),
    Column("source", String(32), nullable=False),
    Column("payload", JSON, nullable=False))


def create_schema(engine) -> None:
    metadata.create_all(engine)
```

```python
from sqlalchemy import desc, insert, select

from qibao_api.contracts.market import Quote
from qibao_api.storage.database import quotes


class QuoteRepository:
    def __init__(self, engine) -> None:
        self.engine = engine

    def save(self, quote: Quote) -> None:
        with self.engine.begin() as connection:
            connection.execute(insert(quotes).values(symbol=quote.symbol,
                observed_at=quote.observed_at, source=quote.source,
                payload=quote.model_dump(mode="json")))

    def latest(self, symbol: str) -> Quote | None:
        statement = select(quotes.c.payload).where(quotes.c.symbol == symbol).order_by(desc(quotes.c.observed_at)).limit(1)
        with self.engine.connect() as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return Quote.model_validate(payload) if payload else None
```

- [ ] **Step 4: Run the repository test**

Run: `python -m pytest apps/api/tests/storage/test_quote_repository.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/qibao_api/storage apps/api/tests/storage
git commit -m "feat: persist quote snapshots for audit"
```

### Task 5: 生成研究摘要并执行刑部降级

**Files:**
- Create: `apps/api/src/qibao_api/contracts/research.py`
- Create: `apps/api/src/qibao_api/zhongshu/daily_research.py`
- Create: `apps/api/src/qibao_api/xingbu/gate.py`
- Create: `apps/api/tests/zhongshu/test_daily_research.py`
- Create: `apps/api/tests/xingbu/test_gate.py`

**Interfaces:**
- Produces: `ResearchCard`, `build_market_snapshot(quote)`, `RiskGate.review(card)`.
- Consumes: `Quote` and `DataQuality` from Task 2.

- [ ] **Step 1: Write failing behavior tests**

```python
def test_fresh_quote_produces_observation_card() -> None:
    quote = Quote(symbol="600000", asset=AssetKind.A_SHARE, name="浦发银行",
                  price=Decimal("10.25"), previous_close=Decimal("10.10"),
                  observed_at=datetime(2026, 7, 13, 10, 30), source="tencent",
                  quality=DataQuality.FRESH)
    card = build_market_snapshot(quote)
    assert card.action == "observe"
    assert card.evidence[0].source == "tencent"


def test_stale_quote_is_blocked() -> None:
    card = ResearchCard(symbol="600000", asset=AssetKind.A_SHARE, action="observe",
        change_percent=Decimal("1.49"), quality=DataQuality.STALE, evidence=[])
    reviewed = RiskGate().review(card)
    assert reviewed.action == "blocked"
    assert "数据已过期" in reviewed.invalid_reasons
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest apps/api/tests/zhongshu apps/api/tests/xingbu -v`

Expected: FAIL because research contracts are missing.

- [ ] **Step 3: Implement transparent, non-predictive first-slice output**

```python
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from qibao_api.contracts.market import AssetKind, DataQuality


class Evidence(BaseModel):
    label: str
    value: str
    source: str
    observed_at: datetime


class ResearchCard(BaseModel):
    symbol: str
    asset: AssetKind
    action: Literal["observe", "blocked"]
    change_percent: Decimal
    quality: DataQuality
    evidence: list[Evidence]
    invalid_reasons: list[str] = Field(default_factory=list)
```

```python
from decimal import Decimal

from qibao_api.contracts.research import Evidence, ResearchCard


def build_market_snapshot(quote) -> ResearchCard:
    change = (quote.price / quote.previous_close - Decimal("1")) * Decimal("100")
    return ResearchCard(symbol=quote.symbol, asset=quote.asset, action="observe",
        change_percent=change.quantize(Decimal("0.01")), quality=quote.quality,
        evidence=[Evidence(label="最新价", value=str(quote.price), source=quote.source,
                           observed_at=quote.observed_at)])
```

```python
from qibao_api.contracts.market import DataQuality


class RiskGate:
    def review(self, card):
        if card.quality is not DataQuality.FRESH:
            return card.model_copy(update={"action": "blocked", "invalid_reasons": ["数据已过期或质量异常"]})
        return card
```

- [ ] **Step 4: Run focused and full backend tests**

Run: `python -m pytest apps/api/tests/zhongshu apps/api/tests/xingbu -v`

Run: `python -m pytest apps/api/tests -v`

Expected: all backend tests pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/qibao_api/contracts apps/api/src/qibao_api/zhongshu apps/api/src/qibao_api/xingbu apps/api/tests
git commit -m "feat: add explainable research card and risk gate"
```

### Task 6: 用尚书省流水线和 FastAPI 暴露纵向切片

**Files:**
- Create: `apps/api/src/qibao_api/shangshu/pipeline.py`
- Create: `apps/api/src/qibao_api/dependencies.py`
- Create: `apps/api/src/qibao_api/routes/health.py`
- Create: `apps/api/src/qibao_api/routes/research.py`
- Create: `apps/api/src/qibao_api/main.py`
- Create: `apps/api/tests/routes/test_research.py`

**Interfaces:**
- Produces: `ResearchPipeline.run(symbol) -> ResearchCard`, `GET /api/v1/a-shares/{symbol}/snapshot`, `GET /health`.
- Consumes: Tasks 3-5 services.

- [ ] **Step 1: Write failing API tests with dependency override**

```python
class FakePipeline:
    async def run(self, symbol: str):
        return ResearchCard(symbol=symbol, asset=AssetKind.A_SHARE, action="observe",
            change_percent=Decimal("1.49"), quality=DataQuality.FRESH,
            evidence=[Evidence(label="最新价", value="10.25", source="tencent",
                               observed_at=datetime(2026, 7, 13, 10, 30))])


def make_client() -> TestClient:
    app.dependency_overrides[get_pipeline] = lambda: FakePipeline()
    return TestClient(app)


def test_a_share_snapshot_returns_evidence() -> None:
    client = make_client()
    response = client.get("/api/v1/a-shares/600000/snapshot")
    assert response.status_code == 200
    assert response.json()["symbol"] == "600000"
    assert response.json()["evidence"][0]["source"] == "tencent"


def test_convertible_bond_is_not_routed_through_a_share_endpoint() -> None:
    client = make_client()
    response = client.get("/api/v1/a-shares/113001/snapshot")
    assert response.status_code == 422
```

- [ ] **Step 2: Verify endpoint tests fail**

Run: `python -m pytest apps/api/tests/routes/test_research.py -v`

Expected: FAIL because the FastAPI app is missing.

- [ ] **Step 3: Implement orchestration and routes**

```python
class ResearchPipeline:
    def __init__(self, quote_source, repository, risk_gate) -> None:
        self.quote_source = quote_source
        self.repository = repository
        self.risk_gate = risk_gate

    async def run(self, symbol: str):
        quote = await self.quote_source.fetch(symbol)
        self.repository.save(quote)
        return self.risk_gate.review(build_market_snapshot(quote))
```

```python
from fastapi import Request


def get_pipeline(request: Request):
    return request.app.state.pipeline
```

```python
from fastapi import APIRouter, Depends, Path

from qibao_api.dependencies import get_pipeline

router = APIRouter(prefix="/api/v1/a-shares", tags=["A股"])


@router.get("/{symbol}/snapshot")
async def snapshot(symbol: str = Path(pattern=r"^(?!11|12)\d{6}$"), pipeline=Depends(get_pipeline)):
    return await pipeline.run(symbol)
```

```python
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine

from qibao_api.gongbu.tencent_quotes import TencentQuoteSource
from qibao_api.routes.health import router as health_router
from qibao_api.routes.research import router as research_router
from qibao_api.settings import Settings
from qibao_api.shangshu.pipeline import ResearchPipeline
from qibao_api.storage.database import create_schema
from qibao_api.storage.quote_repository import QuoteRepository
from qibao_api.xingbu.gate import RiskGate


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url)
    create_schema(engine)
    async with httpx.AsyncClient(timeout=10) as client:
        app.state.pipeline = ResearchPipeline(TencentQuoteSource(client), QuoteRepository(engine), RiskGate())
        yield

app = FastAPI(title="小七宝量化决策台", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(research_router)
```

- [ ] **Step 4: Run endpoint and full backend tests**

Run: `python -m pytest apps/api/tests/routes/test_research.py -v`

Run: `python -m pytest apps/api/tests -v`

Expected: all tests pass, including rejection of a convertible-bond code on the A-share route.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/qibao_api/shangshu apps/api/src/qibao_api/routes apps/api/src/qibao_api/main.py apps/api/tests/routes
git commit -m "feat: expose A-share research pipeline API"
```

### Task 7: 构建情报指挥中枢首页

**Files:**
- Create: `apps/web/src/main.tsx`
- Create: `apps/web/src/app/App.tsx`
- Create: `apps/web/src/app/theme.css`
- Create: `apps/web/src/features/dashboard/types.ts`
- Create: `apps/web/src/features/dashboard/api.ts`
- Create: `apps/web/src/features/dashboard/Dashboard.tsx`
- Create: `apps/web/src/features/dashboard/Dashboard.test.tsx`

**Interfaces:**
- Produces: responsive dashboard with loading, success, blocked and error states.
- Consumes: `GET /api/v1/a-shares/{symbol}/snapshot` from Task 6.

- [ ] **Step 1: Write failing dashboard state tests**

```tsx
const freshCard: ResearchCard = {
  symbol: "600000", asset: "a_share", action: "observe", change_percent: "1.49",
  quality: "fresh", invalid_reasons: [],
  evidence: [{label:"最新价", value:"10.25", source:"腾讯行情", observed_at:"2026-07-13T10:30:00"}]
};
const blockedCard: ResearchCard = {
  ...freshCard, action: "blocked", quality: "stale", invalid_reasons: ["数据已过期或质量异常"]
};

it("shows evidence source and data time", async () => {
  render(<Dashboard loadSnapshot={() => Promise.resolve(freshCard)} />);
  expect(await screen.findByText("腾讯行情")).toBeInTheDocument();
  expect(screen.getByText(/数据截至/)).toBeInTheDocument();
});

it("makes a blocked signal visually explicit", async () => {
  render(<Dashboard loadSnapshot={() => Promise.resolve(blockedCard)} />);
  expect(await screen.findByRole("status")).toHaveTextContent("仅观察");
  expect(screen.getByText("数据已过期或质量异常")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pnpm --filter @qibao/web test`

Expected: FAIL because `Dashboard` is missing.

- [ ] **Step 3: Implement typed API and dashboard states**

```ts
export type ResearchCard = {
  symbol: string;
  asset: "a_share";
  action: "observe" | "blocked";
  change_percent: string;
  quality: "fresh" | "stale" | "conflicted" | "unavailable";
  evidence: Array<{label:string;value:string;source:string;observed_at:string}>;
  invalid_reasons: string[];
};

export async function loadSnapshot(symbol: string): Promise<ResearchCard> {
  const response = await fetch(`/api/v1/a-shares/${symbol}/snapshot`);
  if (!response.ok) throw new Error(`行情请求失败 (${response.status})`);
  return response.json();
}
```

```tsx
import {FormEvent, useState} from "react";

import type {ResearchCard} from "./types";

type ViewState =
  | {kind:"idle"}
  | {kind:"loading"}
  | {kind:"ready"; card:ResearchCard}
  | {kind:"error"; message:string};
type Props = {loadSnapshot:(symbol:string) => Promise<ResearchCard>};

function ResearchPanel({card}:{card:ResearchCard}) {
  const blocked = card.action === "blocked";
  return <section className="research-panel">
    <div role="status">{blocked ? "仅观察" : "数据有效"}</div>
    <h2>{card.symbol}</h2><p>{card.change_percent}%</p>
    {card.evidence.map(item => <dl key={`${item.label}-${item.observed_at}`}>
      <dt>{item.label}</dt><dd>{item.value}</dd><dd>{item.source}</dd>
      <dd>数据截至 {new Date(item.observed_at).toLocaleString("zh-CN")}</dd>
    </dl>)}
    {card.invalid_reasons.map(reason => <p key={reason}>{reason}</p>)}
  </section>;
}

export function Dashboard({loadSnapshot}: Props) {
  const [state, setState] = useState<ViewState>({kind: "idle"});
  const [symbol, setSymbol] = useState("600000");
  async function inspect(symbol: string) {
    setState({kind:"loading"});
    try { setState({kind:"ready", card: await loadSnapshot(symbol)}); }
    catch (error) { setState({kind:"error", message: error instanceof Error ? error.message : "未知错误"}); }
  }
  return <main className="command-center">
    <header><p>尚书省 / 指令执行中心</p><h1>全域情报态势</h1></header>
    <form onSubmit={(event:FormEvent) => {event.preventDefault(); void inspect(symbol);}}>
      <label htmlFor="symbol">A 股代码</label>
      <input id="symbol" value={symbol} pattern="\d{6}" onChange={event => setSymbol(event.target.value)} />
      <button disabled={state.kind === "loading"}>调取行情</button>
    </form>
    {state.kind === "loading" && <section aria-busy="true">正在调取工部行情...</section>}
    {state.kind === "error" && <section role="alert">{state.message}</section>}
    {state.kind === "ready" && <ResearchPanel card={state.card} />}
  </main>;
}
```

- [ ] **Step 4: Declare restrained command-center tokens and responsive layout**

```css
:root {
  --ink-0: #090e14; --ink-1: #101824; --line: #2d3a49;
  --text: #dbe4ed; --muted: #8190a2; --signal: #9db8c9;
  --warning: #d0a26c; --danger: #d09198; --ok: #86b9aa;
  font-family: "Microsoft YaHei UI", sans-serif;
}
body { margin: 0; background: var(--ink-0); color: var(--text); letter-spacing: 0; }
.command-center { min-height: 100vh; display: grid; grid-template-columns: minmax(220px, 280px) 1fr; }
@media (max-width: 760px) { .command-center { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: .01ms !important; } }
```

- [ ] **Step 5: Run UI tests and production build**

Run: `pnpm --filter @qibao/web test`

Run: `pnpm --filter @qibao/web build`

Expected: tests pass and Vite produces `apps/web/dist` without TypeScript errors.

- [ ] **Step 6: Commit**

```powershell
git add apps/web
git commit -m "feat: add intelligence command dashboard"
```

### Task 8: 提供一键运行、文档和全链路验收

**Files:**
- Create: `scripts/dev.ps1`
- Create: `README.md`
- Modify: `.gitignore`
- Create: `apps/api/tests/integration/test_daily_slice.py`

**Interfaces:**
- Produces: one-command local startup and documented operational checks.
- Consumes: completed API and web application.

- [ ] **Step 1: Write a failing integration test for stale-data degradation**

```python
@pytest.mark.asyncio
async def test_pipeline_persists_quote_and_blocks_stale_data(tmp_path) -> None:
    stale_quote = Quote(symbol="600000", asset=AssetKind.A_SHARE, name="浦发银行",
        price=Decimal("10.25"), previous_close=Decimal("10.10"),
        observed_at=datetime(2026, 7, 13, 9, 30), source="fixture",
        quality=DataQuality.STALE)
    class StaleSource:
        async def fetch(self, symbol: str) -> Quote:
            return stale_quote
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    create_schema(engine)
    repository = QuoteRepository(engine)
    result = await ResearchPipeline(StaleSource(), repository, RiskGate()).run("600000")
    assert result.action == "blocked"
    assert repository.latest("600000") is not None
```

- [ ] **Step 2: Run the integration test**

Run: `python -m pytest apps/api/tests/integration/test_daily_slice.py -v`

Expected: PASS after wiring fixtures to the real pipeline; any failure identifies a missing cross-module contract.

- [ ] **Step 3: Add the Windows development launcher**

```powershell
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Missing .venv. Follow README setup first." }
Start-Process -FilePath $python -ArgumentList "-m","uvicorn","qibao_api.main:app","--reload","--port","8000" -WorkingDirectory (Join-Path $root "apps\api") -WindowStyle Hidden
& "C:\Users\90090\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd" --filter @qibao/web dev --host 127.0.0.1
```

- [ ] **Step 4: Document exact setup and operational boundaries**

```markdown
# 小七宝量化决策台

本地研究辅助软件。当前纵向切片只读取 A 股行情并生成可追溯观察卡，不连接券商，不构成投资建议。

## Setup

1. Use Python 3.12 to create `.venv`.
2. Run `.venv\Scripts\python.exe -m pip install -e "apps/api[dev]"`.
3. Run the bundled `pnpm.cmd install` command from the implementation plan.
4. Run `powershell -ExecutionPolicy Bypass -File scripts\dev.ps1`.
5. Open `http://127.0.0.1:5173`.

The Tencent quote adapter is a replaceable free source. Source failures are shown explicitly and never replaced with fabricated data.
```

- [ ] **Step 5: Run all verification and mojibake scans**

Run: `python -m pytest apps/api/tests -v`

Run: `pnpm --filter @qibao/web test`

Run: `pnpm --filter @qibao/web build`

Run: `rg -n "\?{3,}|�|锟|鐨|鍏|闇|璁|绯" apps README.md`

Expected: all tests and build pass; mojibake scan returns no matches.

- [ ] **Step 6: Manually verify the browser states**

Open `http://127.0.0.1:5173` at 1440x900 and 390x844. Verify default, loading, fresh, blocked and network-error states; confirm no text overlap, all controls remain usable, and the A-share screen contains no convertible-bond ranking.

- [ ] **Step 7: Commit**

```powershell
git add README.md scripts .gitignore apps/api/tests/integration
git commit -m "docs: add local workflow and slice verification"
```

## Follow-on Plans

After this slice passes review, create and execute these plans in order:

1. `a-share-market-data-platform`: historical bars, trading calendar, corporate actions, Parquet/DuckDB and backup-source reconciliation.
2. `strategy-research-and-backtest`: factor library, cost-aware backtest, train/validation/out-of-sample separation and result attribution.
3. `paper-trading-and-ledger`: 吏部资金预算、兵部方案、户部委托成交与组合复盘。
4. `risk-compliance-and-audit`: 刑部实时规则、东厂独立审计、礼部授权与留痕。
5. `convertible-bond-domain`: 独立行情、转股价值、溢价率、剩余规模、强赎风险和专属候选池。
6. `news-ai-and-daily-briefing`: 新闻去重、事件分类、证据引用、云端/本地模型网关和盘前盘后报告。
