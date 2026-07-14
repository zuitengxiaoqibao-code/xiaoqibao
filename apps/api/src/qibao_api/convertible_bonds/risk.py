import hashlib
import json
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from qibao_api.contracts.instruments import validate_convertible_bond_code
from qibao_api.contracts.market import AssetKind
from qibao_api.convertible_bonds.metrics import EvidenceBackedClauseState


class BondRiskInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bond_code: str
    asset: Literal[AssetKind.CONVERTIBLE_BOND] = AssetKind.CONVERTIBLE_BOND
    turnover_amount: Decimal | None = Field(default=None, ge=0)
    conversion_premium: Decimal | None
    remaining_size: Decimal = Field(ge=0)
    remaining_days: int = Field(ge=0)
    strong_redemption: EvidenceBackedClauseState

    @field_validator("bond_code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        return validate_convertible_bond_code(value)

    @model_validator(mode="after")
    def evidence_matches_bond(self) -> "BondRiskInput":
        if self.strong_redemption.bond_code != self.bond_code:
            raise ValueError("strong-redemption evidence must match bond_code")
        return self


class BondRiskPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    minimum_turnover_amount: Decimal = Decimal("1000000")
    maximum_conversion_premium: Decimal = Decimal("0.50")
    minimum_remaining_size: Decimal = Decimal("0.50")
    minimum_remaining_days: int = 30
    version: str = "bond-risk.1"


class BondRiskResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    bond_code: str
    asset: Literal[AssetKind.CONVERTIBLE_BOND] = AssetKind.CONVERTIBLE_BOND
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["eligible", "observe_only", "exclude"]
    reason_code: str
    rule_id: str
    rule_version: str
    priority: int


def risk_input_fingerprint(value: BondRiskInput, rule_version: str) -> str:
    evidence = value.strong_redemption
    payload = {
        "asset": value.asset.value,
        "bond_code": value.bond_code,
        "conversion_premium": str(value.conversion_premium) if value.conversion_premium is not None else None,
        "remaining_days": value.remaining_days,
        "remaining_size": str(value.remaining_size),
        "rule_version": rule_version,
        "strong_redemption": {
            "bond_code": evidence.bond_code,
            "clause_text": evidence.clause_text,
            "observed_at": evidence.observed_at.isoformat(),
            "source": evidence.source,
            "state": evidence.state,
        },
        "turnover_amount": str(value.turnover_amount) if value.turnover_amount is not None else None,
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def evaluate_bond_risk(value: BondRiskInput, policy: BondRiskPolicy) -> BondRiskResult:
    findings: list[tuple[int, str, str, Literal["observe_only", "exclude"]]] = []
    state = value.strong_redemption.state
    if state in {"triggered", "announced", "completed"}:
        findings.append((500, f"bond_strong_redemption_{state}", "bond_strong_redemption", "exclude"))
    elif state == "unknown":
        findings.append((350, "bond_strong_redemption_unknown", "bond_strong_redemption", "observe_only"))
    if value.remaining_days < policy.minimum_remaining_days:
        findings.append((400, "bond_maturity_too_near", "bond_maturity", "exclude"))
    if value.remaining_size < policy.minimum_remaining_size:
        findings.append((300, "bond_remaining_size_too_small", "bond_remaining_size", "exclude"))
    if value.conversion_premium is None:
        findings.append((200, "bond_conversion_premium_missing", "bond_conversion_premium", "observe_only"))
    elif value.conversion_premium > policy.maximum_conversion_premium:
        findings.append((200, "bond_conversion_premium_too_high", "bond_conversion_premium", "exclude"))
    if value.turnover_amount is None:
        findings.append((100, "bond_turnover_amount_missing", "bond_liquidity", "observe_only"))
    elif value.turnover_amount < policy.minimum_turnover_amount:
        findings.append((100, "bond_liquidity_below_minimum", "bond_liquidity", "exclude"))
    fingerprint = risk_input_fingerprint(value, policy.version)
    common = {"bond_code": value.bond_code, "input_fingerprint": fingerprint, "rule_version": policy.version}
    if not findings:
        return BondRiskResult(outcome="eligible", reason_code="bond_risk_eligible", rule_id="bond_combined", priority=0, **common)
    severity = {"observe_only": 1, "exclude": 2}
    priority, reason, rule_id, outcome = max(
        findings, key=lambda item: (severity[item[3]], item[0], item[1])
    )
    return BondRiskResult(outcome=outcome, reason_code=reason, rule_id=rule_id, priority=priority, **common)
