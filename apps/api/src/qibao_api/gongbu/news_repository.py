import hashlib
import hmac
import json
import sqlite3
from pathlib import Path

from qibao_api.contracts.news import (
    AIInterpretation,
    NewsArticle,
    NewsCorrection,
    NormalizedNewsEvent,
)
from qibao_api.gongbu.news_collection import NewsCluster


class NewsIntegrityError(RuntimeError):
    pass


class NewsRepository:
    def __init__(self, database: str | Path) -> None:
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS news_articles (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          article_id TEXT NOT NULL UNIQUE,
          content_hash TEXT NOT NULL,
          canonical_hash TEXT NOT NULL,
          metadata TEXT NOT NULL,
          raw_snapshot BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS news_clusters (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          cluster_id TEXT NOT NULL UNIQUE,
          canonical_hash TEXT NOT NULL,
          payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS news_events (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          event_id TEXT NOT NULL UNIQUE,
          canonical_hash TEXT NOT NULL,
          payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS news_interpretations (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          interpretation_id TEXT NOT NULL UNIQUE,
          event_id TEXT NOT NULL,
          canonical_hash TEXT NOT NULL,
          payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS news_corrections (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          correction_id TEXT NOT NULL UNIQUE,
          event_id TEXT NOT NULL,
          canonical_hash TEXT NOT NULL,
          payload TEXT NOT NULL
        );
        CREATE TRIGGER IF NOT EXISTS reject_update_news_articles
        BEFORE UPDATE ON news_articles
        BEGIN SELECT RAISE(ABORT, 'append-only news articles'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_news_articles
        BEFORE DELETE ON news_articles
        BEGIN SELECT RAISE(ABORT, 'append-only news articles'); END;
        CREATE TRIGGER IF NOT EXISTS reject_update_news_clusters
        BEFORE UPDATE ON news_clusters
        BEGIN SELECT RAISE(ABORT, 'append-only news clusters'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_news_clusters
        BEFORE DELETE ON news_clusters
        BEGIN SELECT RAISE(ABORT, 'append-only news clusters'); END;
        CREATE TRIGGER IF NOT EXISTS reject_update_news_events
        BEFORE UPDATE ON news_events
        BEGIN SELECT RAISE(ABORT, 'append-only news events'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_news_events
        BEFORE DELETE ON news_events
        BEGIN SELECT RAISE(ABORT, 'append-only news events'); END;
        CREATE TRIGGER IF NOT EXISTS reject_update_news_interpretations
        BEFORE UPDATE ON news_interpretations
        BEGIN SELECT RAISE(ABORT, 'append-only news interpretations'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_news_interpretations
        BEFORE DELETE ON news_interpretations
        BEGIN SELECT RAISE(ABORT, 'append-only news interpretations'); END;
        CREATE TRIGGER IF NOT EXISTS reject_update_news_corrections
        BEFORE UPDATE ON news_corrections
        BEGIN SELECT RAISE(ABORT, 'append-only news corrections'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_news_corrections
        BEFORE DELETE ON news_corrections
        BEGIN SELECT RAISE(ABORT, 'append-only news corrections'); END;
        """)

    def append_articles(self, articles: tuple[NewsArticle, ...]) -> int:
        inserted = 0
        with self.connection:
            for article in articles:
                existing = self.connection.execute(
                    "SELECT content_hash FROM news_articles WHERE article_id=?",
                    (article.article_id,),
                ).fetchone()
                if existing is not None:
                    if not hmac.compare_digest(existing["content_hash"], article.content_hash):
                        raise NewsIntegrityError(
                            f"news article id collision: {article.article_id}"
                        )
                    continue
                metadata = json.dumps(
                    article.model_dump(mode="json", exclude={"raw_snapshot"}),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                canonical_hash = _record_hash(metadata, article.raw_snapshot)
                self.connection.execute(
                    """INSERT INTO news_articles(
                    article_id,content_hash,canonical_hash,metadata,raw_snapshot
                    ) VALUES(?,?,?,?,?)""",
                    (
                        article.article_id,
                        article.content_hash,
                        canonical_hash,
                        metadata,
                        article.raw_snapshot,
                    ),
                )
                inserted += 1
        return inserted

    def append_cluster(self, cluster: NewsCluster) -> str:
        missing = [
            article_id
            for article_id in cluster.article_ids
            if self.connection.execute(
                "SELECT 1 FROM news_articles WHERE article_id=?", (article_id,)
            ).fetchone()
            is None
        ]
        if missing:
            raise NewsIntegrityError(f"cluster references missing articles: {missing}")
        payload = json.dumps(
            cluster.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        canonical_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        cluster_id = f"news-cluster-{canonical_hash[:24]}"
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO news_clusters(cluster_id,canonical_hash,payload) VALUES(?,?,?)",
                (cluster_id, canonical_hash, payload),
            )
        return cluster_id

    def articles(self) -> list[NewsArticle]:
        rows = self.connection.execute(
            "SELECT * FROM news_articles ORDER BY sequence"
        ).fetchall()
        articles: list[NewsArticle] = []
        for row in rows:
            canonical_hash = _record_hash(row["metadata"], row["raw_snapshot"])
            if not hmac.compare_digest(canonical_hash, row["canonical_hash"]):
                raise NewsIntegrityError(
                    f"news article {row['article_id']} failed integrity check"
                )
            values = json.loads(row["metadata"])
            values["raw_snapshot"] = row["raw_snapshot"]
            articles.append(NewsArticle.model_validate(values))
        return articles

    def append_event(self, event: NormalizedNewsEvent) -> bool:
        missing = [
            citation.article_id
            for citation in event.citations
            if self.connection.execute(
                "SELECT 1 FROM news_articles WHERE article_id=?",
                (citation.article_id,),
            ).fetchone()
            is None
        ]
        if missing:
            raise NewsIntegrityError(f"event references missing articles: {missing}")
        payload = json.dumps(
            event.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        canonical_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        existing = self.connection.execute(
            "SELECT canonical_hash FROM news_events WHERE event_id=?", (event.event_id,)
        ).fetchone()
        if existing is not None:
            if not hmac.compare_digest(existing["canonical_hash"], canonical_hash):
                raise NewsIntegrityError(f"news event id collision: {event.event_id}")
            return False
        with self.connection:
            self.connection.execute(
                "INSERT INTO news_events(event_id,canonical_hash,payload) VALUES(?,?,?)",
                (event.event_id, canonical_hash, payload),
            )
        return True

    def events(self) -> list[NormalizedNewsEvent]:
        rows = self.connection.execute(
            "SELECT * FROM news_events ORDER BY sequence"
        ).fetchall()
        events = []
        for row in rows:
            computed = hashlib.sha256(row["payload"].encode("utf-8")).hexdigest()
            if not hmac.compare_digest(computed, row["canonical_hash"]):
                raise NewsIntegrityError(
                    f"news event {row['event_id']} failed integrity check"
                )
            events.append(NormalizedNewsEvent.model_validate_json(row["payload"]))
        return events

    def append_interpretation(self, interpretation: AIInterpretation) -> bool:
        event_row = self.connection.execute(
            "SELECT payload FROM news_events WHERE event_id=?",
            (interpretation.event_id,),
        ).fetchone()
        if event_row is None:
            raise NewsIntegrityError(
                f"interpretation references missing event: {interpretation.event_id}"
            )
        event = NormalizedNewsEvent.model_validate_json(event_row["payload"])
        allowed = {citation.citation_id for citation in event.citations}
        supplied = {citation.citation_id for citation in interpretation.citations}
        if not supplied.issubset(allowed):
            raise NewsIntegrityError("interpretation citations differ from frozen event")
        payload = json.dumps(
            interpretation.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        canonical_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        existing = self.connection.execute(
            "SELECT canonical_hash FROM news_interpretations WHERE interpretation_id=?",
            (interpretation.interpretation_id,),
        ).fetchone()
        if existing is not None:
            if not hmac.compare_digest(existing["canonical_hash"], canonical_hash):
                raise NewsIntegrityError(
                    f"news interpretation id collision: {interpretation.interpretation_id}"
                )
            return False
        with self.connection:
            self.connection.execute(
                """INSERT INTO news_interpretations(
                interpretation_id,event_id,canonical_hash,payload
                ) VALUES(?,?,?,?)""",
                (
                    interpretation.interpretation_id,
                    interpretation.event_id,
                    canonical_hash,
                    payload,
                ),
            )
        return True

    def interpretations(self) -> list[AIInterpretation]:
        rows = self.connection.execute(
            "SELECT * FROM news_interpretations ORDER BY sequence"
        ).fetchall()
        interpretations = []
        for row in rows:
            computed = hashlib.sha256(row["payload"].encode("utf-8")).hexdigest()
            if not hmac.compare_digest(computed, row["canonical_hash"]):
                raise NewsIntegrityError(
                    f"news interpretation {row['interpretation_id']} failed integrity check"
                )
            interpretations.append(AIInterpretation.model_validate_json(row["payload"]))
        return interpretations

    def append_correction(self, correction: NewsCorrection) -> bool:
        if self.connection.execute(
            "SELECT 1 FROM news_events WHERE event_id=?", (correction.event_id,)
        ).fetchone() is None:
            raise NewsIntegrityError(
                f"correction references missing event: {correction.event_id}"
            )
        payload = json.dumps(
            correction.model_dump(mode="json"), ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        )
        canonical_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        existing = self.connection.execute(
            "SELECT canonical_hash FROM news_corrections WHERE correction_id=?",
            (correction.correction_id,),
        ).fetchone()
        if existing is not None:
            if not hmac.compare_digest(existing["canonical_hash"], canonical_hash):
                raise NewsIntegrityError(
                    f"news correction id collision: {correction.correction_id}"
                )
            return False
        with self.connection:
            self.connection.execute(
                """INSERT INTO news_corrections(
                correction_id,event_id,canonical_hash,payload
                ) VALUES(?,?,?,?)""",
                (
                    correction.correction_id,
                    correction.event_id,
                    canonical_hash,
                    payload,
                ),
            )
        return True

    def corrections(self) -> list[NewsCorrection]:
        rows = self.connection.execute(
            "SELECT * FROM news_corrections ORDER BY sequence"
        ).fetchall()
        corrections = []
        for row in rows:
            computed = hashlib.sha256(row["payload"].encode("utf-8")).hexdigest()
            if not hmac.compare_digest(computed, row["canonical_hash"]):
                raise NewsIntegrityError(
                    f"news correction {row['correction_id']} failed integrity check"
                )
            corrections.append(NewsCorrection.model_validate_json(row["payload"]))
        return corrections

    def clusters(self) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM news_clusters ORDER BY sequence"
        ).fetchall()
        result = []
        for row in rows:
            computed = hashlib.sha256(row["payload"].encode("utf-8")).hexdigest()
            if not hmac.compare_digest(computed, row["canonical_hash"]):
                raise NewsIntegrityError(
                    f"news cluster {row['cluster_id']} failed integrity check"
                )
            result.append(
                {
                    "cluster_id": row["cluster_id"],
                    "cluster": NewsCluster.model_validate_json(row["payload"]),
                }
            )
        return result

    def close(self) -> None:
        self.connection.close()


def _record_hash(metadata: str, raw_snapshot: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(metadata.encode("utf-8"))
    digest.update(b"\0")
    digest.update(raw_snapshot)
    return digest.hexdigest()
