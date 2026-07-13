# A 股市场数据平台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 A 股主域增加可审计的历史日线采集、本地 DuckDB/Parquet 存储、数据质量报告和工部状态界面。

**Architecture:** 通达信 mootdx 是历史 K 线主源，腾讯继续作为实时快照源；历史数据先转换为统一 `DailyBar` 契约，再写入 DuckDB 并导出按标的分区的 Parquet。所有源状态通过统一健康模型暴露，失败时明确降级，不调用东财行情接口。

**Tech Stack:** Python 3.12、mootdx 0.11.x、DuckDB 1.3.x、Pydantic 2.11.7、FastAPI 0.116.1、React 19.1.0、Vitest 3.2.4。

## Global Constraints

- A 股是默认主域，可转债不复用 A 股 K 线解析器。
- 历史行情优先使用 mootdx；实时行情保留腾讯适配器。
- 不使用东财获取可由通达信或腾讯提供的行情。
- 每条日线记录来源、交易日期和写入时间。
- 网络失败不得返回虚构数据；状态必须显示错误原因。
- 中文源码和数据统一 UTF-8，并执行乱码扫描。

## File Map

```text
apps/api/src/qibao_api/contracts/bars.py          # 日线与同步报告契约
apps/api/src/qibao_api/gongbu/tdx_client.py       # 通达信服务器选择
apps/api/src/qibao_api/gongbu/tdx_history.py      # mootdx DataFrame 转换
apps/api/src/qibao_api/storage/bar_repository.py  # DuckDB 与 Parquet
apps/api/src/qibao_api/gongbu/data_service.py     # 同步编排与状态
apps/api/src/qibao_api/routes/data.py             # 工部数据 API
apps/web/src/features/data-status/                # 工部状态面板
```

---

### Task 1: 定义历史日线契约

**Files:**
- Create: `apps/api/src/qibao_api/contracts/bars.py`
- Test: `apps/api/tests/contracts/test_bars.py`

**Interfaces:**
- Produces: `DailyBar`, `DataSourceState`, `SyncReport`.

- [ ] **Step 1: Write the failing validation test**

```python
def test_daily_bar_rejects_inverted_high_low() -> None:
    with pytest.raises(ValidationError):
        DailyBar(symbol="600000", trade_date=date(2026, 7, 13),
                 open=Decimal("10"), high=Decimal("9"), low=Decimal("8"),
                 close=Decimal("9.5"), volume=100, amount=Decimal("950"), source="mootdx")
```

- [ ] **Step 2: Run RED**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/contracts/test_bars.py -v`

Expected: import failure for `contracts.bars`.

- [ ] **Step 3: Implement contracts**

```python
class DailyBar(BaseModel):
    symbol: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: int = Field(ge=0)
    amount: Decimal = Field(ge=0)
    source: str

    @model_validator(mode="after")
    def validate_range(self):
        if self.high < self.low or not self.low <= self.open <= self.high or not self.low <= self.close <= self.high:
            raise ValueError("OHLC values are outside the daily range")
        return self
```

- [ ] **Step 4: Run GREEN and commit**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/contracts/test_bars.py -v`

Commit: `feat: define historical market data contracts`

### Task 2: 增加通达信历史日线适配器

**Files:**
- Modify: `apps/api/pyproject.toml`
- Create: `apps/api/src/qibao_api/gongbu/tdx_client.py`
- Create: `apps/api/src/qibao_api/gongbu/tdx_history.py`
- Test: `apps/api/tests/gongbu/test_tdx_history.py`

**Interfaces:**
- Produces: `TdxHistorySource.fetch_daily(symbol, limit) -> list[DailyBar]`.

- [ ] **Step 1: Write RED with a fake client**

```python
def test_history_source_converts_rows_to_sorted_daily_bars() -> None:
    frame = pd.DataFrame([{"open": 9.0, "high": 10.0, "low": 8.8, "close": 9.5,
                           "vol": 1000, "amount": 9500, "datetime": "2026-07-13"}])
    bars = TdxHistorySource(FakeClient(frame)).fetch_daily("600000", 20)
    assert bars[0].trade_date == date(2026, 7, 13)
    assert bars[0].source == "mootdx"
```

- [ ] **Step 2: Run RED**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/gongbu/test_tdx_history.py -v`

- [ ] **Step 3: Implement explicit-server client and adapter**

```python
class TdxHistorySource:
    def __init__(self, client): self.client = client

    def fetch_daily(self, symbol: str, limit: int = 250) -> list[DailyBar]:
        frame = self.client.bars(symbol=symbol, category=4, offset=limit)
        if frame is None or frame.empty:
            raise DataSourceUnavailable("mootdx returned no daily bars")
        bars = [DailyBar(symbol=symbol, trade_date=pd.to_datetime(row["datetime"]).date(),
                         open=row["open"], high=row["high"], low=row["low"], close=row["close"],
                         volume=int(row["vol"]), amount=row["amount"], source="mootdx")
                for _, row in frame.iterrows()]
        return sorted(bars, key=lambda item: item.trade_date)
```

- [ ] **Step 4: Run GREEN, live smoke and commit**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/gongbu/test_tdx_history.py -v`

Live smoke: fetch 20 bars for `600000`; failure must print the attempted server and exception.

Commit: `feat: ingest mootdx daily bars`

### Task 3: 保存 DuckDB 并导出 Parquet

**Files:**
- Create: `apps/api/src/qibao_api/storage/bar_repository.py`
- Test: `apps/api/tests/storage/test_bar_repository.py`

**Interfaces:**
- Produces: `BarRepository.upsert`, `latest`, `export_parquet`.

- [ ] **Step 1: Write RED for idempotent upsert**

```python
def test_upsert_replaces_same_symbol_and_date(tmp_path, daily_bar) -> None:
    repository = BarRepository(tmp_path / "market.duckdb")
    repository.upsert([daily_bar])
    repository.upsert([daily_bar.model_copy(update={"close": Decimal("9.60")})])
    assert repository.latest("600000", 10)[0].close == Decimal("9.60")
```

- [ ] **Step 2: Run RED**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/storage/test_bar_repository.py -v`

- [ ] **Step 3: Implement keyed storage and export**

Use a DuckDB table keyed by `(symbol, trade_date)` and `INSERT OR REPLACE`. Export with:

```sql
COPY (SELECT * FROM daily_bars WHERE symbol = ? ORDER BY trade_date)
TO ? (FORMAT PARQUET, COMPRESSION ZSTD)
```

- [ ] **Step 4: Run GREEN, inspect Parquet row count and commit**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/storage/test_bar_repository.py -v`

Commit: `feat: persist historical bars in DuckDB and Parquet`

### Task 4: 编排同步和数据质量报告

**Files:**
- Create: `apps/api/src/qibao_api/gongbu/data_service.py`
- Test: `apps/api/tests/gongbu/test_data_service.py`

**Interfaces:**
- Produces: `MarketDataService.sync_symbol(symbol, limit) -> SyncReport`.

- [ ] **Step 1: Write RED for success and source failure**

```python
def test_sync_report_exposes_source_failure() -> None:
    report = MarketDataService(FailingSource(), repository).sync_symbol("600000", 20)
    assert report.state == DataSourceState.ERROR
    assert report.written_rows == 0
    assert "timeout" in report.message
```

- [ ] **Step 2: Run RED**

Run: `.venv\Scripts\python.exe -m pytest apps/api/tests/gongbu/test_data_service.py -v`

- [ ] **Step 3: Implement service**

```python
def sync_symbol(self, symbol: str, limit: int = 250) -> SyncReport:
    started = datetime.now()
    try:
        bars = self.source.fetch_daily(symbol, limit)
        self.repository.upsert(bars)
        path = self.repository.export_parquet(symbol)
        return SyncReport(symbol=symbol, state="ready", written_rows=len(bars),
                          source="mootdx", parquet_path=str(path), started_at=started,
                          finished_at=datetime.now(), message="同步完成")
    except Exception as error:
        return SyncReport(symbol=symbol, state="error", written_rows=0, source="mootdx",
                          started_at=started, finished_at=datetime.now(), message=str(error))
```

- [ ] **Step 4: Run GREEN and commit**

Commit: `feat: orchestrate auditable market data sync`

### Task 5: 暴露工部 API 与数据状态面板

**Files:**
- Create: `apps/api/src/qibao_api/routes/data.py`
- Modify: `apps/api/src/qibao_api/main.py`
- Create: `apps/web/src/features/data-status/DataStatusPanel.tsx`
- Modify: `apps/web/src/features/dashboard/Dashboard.tsx`
- Test: `apps/api/tests/routes/test_data.py`
- Test: `apps/web/src/features/data-status/DataStatusPanel.test.tsx`

**Interfaces:**
- Produces: `POST /api/v1/a-shares/{symbol}/history/sync`, `GET /api/v1/a-shares/{symbol}/history`.

- [ ] **Step 1: Write failing API and UI tests**

```python
def test_sync_endpoint_returns_auditable_report(client):
    response = client.post("/api/v1/a-shares/600000/history/sync?limit=20")
    assert response.status_code == 200
    assert response.json()["source"] == "mootdx"
```

```tsx
it("shows written rows and source without fabricated freshness", () => {
  render(<DataStatusPanel report={report} />);
  expect(screen.getByText("mootdx")).toBeInTheDocument();
  expect(screen.getByText("20 条日线")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run RED**

Run both focused tests and confirm missing route/component failures.

- [ ] **Step 3: Implement API and panel**

The panel belongs in the existing right rail, uses existing design tokens, and renders `ready`, `error`, `empty`, and `syncing` states. It must not merge convertible-bond history into A-share routes.

- [ ] **Step 4: Full verification and commit**

Run backend tests, Ruff, frontend tests, production build, live sync for `600000`, and mojibake scan.

Commit: `feat: add Gongbu market data status workflow`
