from qibao_api.contracts.market import AssetKind
from qibao_api.gongbu.news_collection import deduplicate_articles


class NewsIngestionService:
    def __init__(self, source, repository, linker, compliance) -> None:
        self.source = source
        self.repository = repository
        self.linker = linker
        self.compliance = compliance

    async def sync(self) -> dict[str, int]:
        self.compliance.require_feature_sources("market_news", AssetKind.A_SHARE)
        articles = await self.source.fetch()
        clusters = deduplicate_articles(articles)
        inserted = self.repository.append_articles(tuple(articles))
        for cluster in clusters:
            self.repository.append_cluster(cluster)
        article_by_id = {article.article_id: article for article in articles}
        event_count = 0
        for cluster in clusters:
            primary = article_by_id[cluster.primary_article_id]
            event_count += int(self.repository.append_event(self.linker.link(primary)))
        return {
            "fetched": len(articles),
            "inserted": inserted,
            "clusters": len(clusters),
            "events": event_count,
        }
