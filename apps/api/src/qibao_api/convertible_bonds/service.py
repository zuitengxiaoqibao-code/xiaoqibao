from datetime import datetime, timedelta, timezone
from decimal import Decimal

from qibao_api.contracts.market import AssetKind
from qibao_api.convertible_bonds.candidates import BondCandidate, filter_and_rank_candidates
from qibao_api.convertible_bonds.metrics import (
    EvidenceBackedClauseState,
    calculate_metrics,
)
from qibao_api.convertible_bonds.risk import BondRiskInput, BondRiskPolicy, evaluate_bond_risk


class ConvertibleBondService:
    def __init__(self, quote_source, clause_source, linked_stock_source, repository, compliance,
                 diagnosis_repository,
                 *, clock=lambda: datetime.now(timezone.utc)) -> None:
        self.quote_source = quote_source
        self.clause_source = clause_source
        self.linked_stock_source = linked_stock_source
        self.repository = repository
        self.compliance = compliance
        self.diagnosis_repository = diagnosis_repository
        self.clock = clock

    def dashboard(self) -> dict:
        codes = sorted({item.contract.bond_code for item in self.repository.all_latest()})
        return {"status": "ready" if codes else "empty", "bond_count": len(codes), "bond_codes": codes}

    async def diagnose(self, bond_code: str) -> dict:
        asset = AssetKind.CONVERTIBLE_BOND
        self.compliance.require_feature_sources("bond_quotes", asset)
        quote = await self.quote_source.fetch(bond_code)
        self.compliance.require_feature_sources("bond_clauses", asset)
        snapshot = await self.clause_source.fetch(bond_code)
        latest_by_source = {
            item.source: item for item in self.repository.snapshots(bond_code)
            if item.source != snapshot.source
        }
        self.repository.append(snapshot)
        stock = await self.linked_stock_source.fetch(snapshot.contract.linked_stock)

        metrics = calculate_metrics(
            par_value=Decimal("100"), conversion_price=snapshot.contract.conversion_price,
            stock_price=stock.price, bond_price=quote.price, pure_bond_value=None,
            as_of=self.clock().date(), maturity=snapshot.contract.maturity,
            remaining_size=snapshot.contract.remaining_size, bond_suspended=quote.suspended,
            stock_suspended=getattr(stock, "suspended", False),
        )
        evidence = EvidenceBackedClauseState(
            bond_code=bond_code, state=snapshot.strong_redemption.state,
            clause_text=snapshot.strong_redemption.clause_text,
            source=snapshot.source, observed_at=snapshot.fetched_at,
        )
        risk_input = BondRiskInput(
            bond_code=bond_code, turnover_amount=None,
            conversion_premium=metrics.conversion_premium,
            remaining_size=metrics.remaining_size, remaining_days=metrics.remaining_term.days,
            strong_redemption=evidence,
        )
        risk = evaluate_bond_risk(risk_input, BondRiskPolicy())
        source_conflict = any(
            item.contract.linked_stock != snapshot.contract.linked_stock
            or item.contract.conversion_price != snapshot.contract.conversion_price
            for item in latest_by_source.values()
        )
        stale = self.clock() - quote.observed_at.astimezone(timezone.utc) > timedelta(minutes=3)
        status = "source_conflict" if source_conflict else "stale_quote" if stale else "ready"
        result = {
            "status": status,
            "bond": {"code": bond_code, "name": quote.name, "price": quote.price,
                     "previous_close": quote.previous_close, "suspended": quote.suspended},
            "linked_stock": {"code": stock.symbol, "name": stock.name, "price": stock.price,
                             "source": stock.source, "observed_at": stock.observed_at},
            "quote": {"source": quote.source, "observed_at": quote.observed_at,
                      "quality": "stale" if stale else quote.quality, "raw_identity": quote.raw_identity},
            "clause_snapshot": {"source": snapshot.source, "fetched_at": snapshot.fetched_at,
                                "content_hash": snapshot.content_hash,
                                "conversion_price": snapshot.contract.conversion_price,
                                "maturity": snapshot.contract.maturity,
                                "remaining_size": snapshot.contract.remaining_size},
            "metric_inputs": {"par_value": Decimal("100"), "bond_price": quote.price,
                              "stock_price": stock.price,
                              "conversion_price": snapshot.contract.conversion_price},
            "metrics": metrics.model_dump(mode="json"),
            "risk": {**risk.model_dump(mode="json"),
                     "unknowns": ["pure_bond_value", "turnover_amount"],
                     "explanations": [risk.reason_code]},
            "strong_redemption": evidence.model_dump(mode="json"),
        }
        result["diagnosis_id"] = self.diagnosis_repository.append(bond_code, result)
        return result

    def candidates(self) -> dict:
        items = []
        for stored in self.diagnosis_repository.latest_by_bond():
            diagnosis = stored["payload"]
            if diagnosis["bond"]["suspended"] or diagnosis["bond"]["price"] is None:
                continue
            metrics = diagnosis["metrics"]
            evidence = EvidenceBackedClauseState.model_validate(diagnosis["strong_redemption"])
            risk_input = BondRiskInput(
                bond_code=diagnosis["bond"]["code"], turnover_amount=None,
                conversion_premium=metrics["conversion_premium"],
                remaining_size=metrics["remaining_size"],
                remaining_days=metrics["remaining_term"]["days"], strong_redemption=evidence,
            )
            risk = evaluate_bond_risk(risk_input, BondRiskPolicy())
            items.append(BondCandidate(
                bond_code=diagnosis["bond"]["code"], bond_price=diagnosis["bond"]["price"],
                turnover_amount=None, conversion_premium=metrics["conversion_premium"],
                remaining_size=metrics["remaining_size"],
                remaining_days=metrics["remaining_term"]["days"],
                strong_redemption=evidence, risk=risk,
            ))
        ranked = filter_and_rank_candidates(items)
        return {"status": "ready" if ranked else "empty",
                "items": [item.model_dump(mode="json") for item in ranked]}
