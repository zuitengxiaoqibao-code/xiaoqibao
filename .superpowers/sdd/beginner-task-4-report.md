# Task 4 Report: Beginner Navigation And Research Cockpit

## Result

- Replaced the department navigation with exactly six beginner routes: 今日研判, A 股观察, 新闻热点, 风险提醒, 历史复盘, 数据设置.
- Kept 可转债 as an isolated asset entry that drops the A-share symbol from its URL.
- Rebuilt the first research viewport around stock selection, preparation status, the three-state action card, reasons, risks, waiting signals, re-evaluation conditions, and the three daily phases.
- Mapped deterministic actions to exactly 暂不参与, 加入观察, 回避.
- Removed candidate-ledger, simulation-plan, gate, strategy-version, internal-ID, price, position, stop, order, and department UI from the cockpit.
- Moved raw section data into one collapsed 数据详情 disclosure and omitted funds/backtest unavailable sections.
- Preserved stale-response isolation, live-to-history context isolation, stock switching, and convertible-bond route isolation.
- Added compatibility for older cockpit responses without `preparation`; availability is derived from existing sections without hiding the deterministic action card.

## Design

The interface keeps the existing dark technical identity but uses a restrained research-terminal layout. Status color is semantic: green for observable, amber for waiting, red for avoid. Body and metadata sizes were raised to 12-14px, with a fixed desktop rail and horizontally scrollable mobile navigation.

## Verification

- Frontend tests: 68 tests expected after the compatibility regression.
- Production build: TypeScript and Vite build.
- Browser: six navigation buttons present, isolated bond entry present, no horizontal overflow at the available 1157px viewport, legacy snapshot no longer crashes after compatibility fix.
- Mobile layout is covered by responsive CSS and component tests; the connected browser surface did not expose viewport resizing.

## Concerns

- Risk and settings are intentionally lightweight placeholders; Task 5 owns functional data and AI settings.
- Some legacy governance and operations components remain in source for backend compatibility but are no longer reachable from the user navigation.
