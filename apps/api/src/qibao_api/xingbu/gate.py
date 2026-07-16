from qibao_api.contracts.market import DataQuality
from qibao_api.contracts.research import ResearchCard


class RiskGate:
    def review(self, card: ResearchCard) -> ResearchCard:
        if card.quality is DataQuality.FRESH:
            return card
        return card.model_copy(
            update={
                "action": "blocked",
                "invalid_reasons": ["数据已过期或质量异常"],
            }
        )
