from qibao_api.contracts.market import AssetKind
from qibao_api.gongbu.news_collection import deduplicate_articles


class NewsIngestionService:
    def __init__(
        self, source, repository, linker, compliance, ai_gateway=None, *,
        stock_source=None,
    ) -> None:
        self.source = source
        self.stock_source = stock_source
        self.repository = repository
        self.linker = linker
        self.compliance = compliance
        self.ai_gateway = ai_gateway

    async def sync(self) -> dict[str, int]:
        self.compliance.require_feature_sources("market_news", AssetKind.A_SHARE)
        articles = await self.source.fetch()
        return await self._ingest(articles)

    async def sync_symbol(self, symbol: str) -> dict[str, int]:
        self.compliance.require_feature_sources("market_news", AssetKind.A_SHARE)
        if self.stock_source is None:
            return {
                "fetched": 0, "inserted": 0, "clusters": 0, "events": 0,
                "interpretations": 0,
            }
        articles = await self.stock_source.fetch(symbol)
        return await self._ingest(articles)

    async def _ingest(self, articles) -> dict[str, int]:
        clusters = deduplicate_articles(articles)
        inserted = self.repository.append_articles(tuple(articles))
        for cluster in clusters:
            self.repository.append_cluster(cluster)
        article_ids = tuple(article.article_id for article in articles)
        article_by_id = {
            article.article_id: article
            for article in self.repository.articles_by_ids(article_ids)
        }
        event_count = 0
        interpretation_count = 0
        for cluster in clusters:
            primary = article_by_id[cluster.primary_article_id]
            event = self.linker.link(primary)
            event_inserted, _ = self.repository.reconcile_event(event)
            event_count += int(event_inserted)
            if event_inserted and self.ai_gateway is not None:
                interpretation = await self.ai_gateway.interpret(event)
                interpretation_count += int(
                    self.repository.append_interpretation(interpretation)
                )
        return {
            "fetched": len(articles),
            "inserted": inserted,
            "clusters": len(clusters),
            "events": event_count,
            "interpretations": interpretation_count,
        }
