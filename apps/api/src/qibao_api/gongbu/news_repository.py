import hashlib
import hmac
import json
import sqlite3
from datetime import datetime, timezone
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


_CORRECTABLE_EVENT_FIELDS = (
    "affected_instruments",
    "industries",
    "themes",
    "association_confidence",
    "review_state",
)
_FROZEN_EVENT_FIELDS = (
    "event_id",
    "event_type",
    "headline",
    "occurred_at",
    "normalized_at",
    "citations",
)


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
        return self._articles_from_rows(rows)

    def articles_by_ids(self, article_ids: tuple[str, ...]) -> list[NewsArticle]:
        if not article_ids:
            return []
        placeholders = ",".join("?" for _ in article_ids)
        rows = self.connection.execute(
            f"SELECT * FROM news_articles WHERE article_id IN ({placeholders}) "
            "ORDER BY sequence",
            article_ids,
        ).fetchall()
        return self._articles_from_rows(rows)

    @staticmethod
    def _articles_from_rows(rows) -> list[NewsArticle]:
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

    def reconcile_event(self, event: NormalizedNewsEvent) -> tuple[bool, bool]:
        row = self.connection.execute(
            "SELECT * FROM news_events WHERE event_id=?", (event.event_id,)
        ).fetchone()
        if row is None:
            return self.append_event(event), False

        original = self._events_from_rows((row,))[0]
        corrections = [
            item for item in self.corrections() if item.event_id == event.event_id
        ]
        effective = self._apply_corrections(original, corrections)
        if effective == event:
            return False, False
        if any(
            getattr(original, field) != getattr(event, field)
            for field in _FROZEN_EVENT_FIELDS
        ):
            raise NewsIntegrityError(f"news event id collision: {event.event_id}")
        if corrections and corrections[-1].origin == "human":
            return False, False

        target = {
            field: getattr(event, field)
            for field in _CORRECTABLE_EVENT_FIELDS
        }
        semantic_payload = json.dumps(
            {"event_id": event.event_id, **target},
            default=str,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(semantic_payload.encode("utf-8")).hexdigest()
        correction = NewsCorrection(
            correction_id=f"system-correction-{digest[:32]}",
            event_id=event.event_id,
            corrected_at=datetime.now(timezone.utc),
            reason="deterministic_linker_classification_update",
            origin="system",
            review_state=event.review_state,
            affected_instruments=event.affected_instruments,
            industries=event.industries,
            themes=event.themes,
            association_confidence=event.association_confidence,
        )
        return False, self.append_correction(correction)

    def events(self) -> list[NormalizedNewsEvent]:
        rows = self.connection.execute(
            "SELECT * FROM news_events ORDER BY sequence"
        ).fetchall()
        return self._events_from_rows(rows)

    @staticmethod
    def _events_from_rows(rows) -> list[NormalizedNewsEvent]:
        events = []
        for row in rows:
            computed = hashlib.sha256(row["payload"].encode("utf-8")).hexdigest()
            if not hmac.compare_digest(computed, row["canonical_hash"]):
                raise NewsIntegrityError(
                    f"news event {row['event_id']} failed integrity check"
                )
            events.append(NormalizedNewsEvent.model_validate_json(row["payload"]))
        return events

    def effective_events(
        self, *, cutoff: datetime | None = None
    ) -> list[NormalizedNewsEvent]:
        normalized_cutoff = cutoff.astimezone(timezone.utc) if cutoff else None
        corrections_by_event: dict[str, list[NewsCorrection]] = {}
        for correction in self.corrections():
            if (
                normalized_cutoff is not None
                and correction.corrected_at > normalized_cutoff
            ):
                continue
            corrections_by_event.setdefault(correction.event_id, []).append(correction)
        return [
            self._apply_corrections(
                event, corrections_by_event.get(event.event_id, [])
            )
            for event in self.events()
        ]

    @staticmethod
    def _apply_corrections(
        event: NormalizedNewsEvent, corrections: list[NewsCorrection]
    ) -> NormalizedNewsEvent:
        effective = event
        for correction in corrections:
            update = {
                "affected_instruments": correction.affected_instruments,
                "industries": correction.industries,
                "themes": correction.themes,
                "review_state": correction.review_state,
            }
            if correction.association_confidence is not None:
                update["association_confidence"] = correction.association_confidence
            effective = effective.model_copy(update=update)
        return effective

    def effective_events_for_symbol(
        self, symbol: str, *, cutoff: datetime | None = None
    ) -> list[NormalizedNewsEvent]:
        normalized_cutoff = cutoff.astimezone(timezone.utc) if cutoff else None
        return [
            event
            for event in self.effective_events(cutoff=normalized_cutoff)
            if ("a_share", symbol) in {
                (asset.value, code) for asset, code in event.affected_instruments
            }
            and event.review_state == "verified"
            and (normalized_cutoff is None or event.normalized_at <= normalized_cutoff)
            and (normalized_cutoff is None or event.occurred_at <= normalized_cutoff)
        ]

    def events_for_symbol(
        self, symbol: str, *, cutoff: datetime | None = None
    ) -> list[NormalizedNewsEvent]:
        normalized_cutoff = (
            cutoff.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if cutoff else None
        )
        rows = self.connection.execute(
            """SELECT DISTINCT news_events.* FROM news_events,
               json_each(json_extract(news_events.payload, '$.affected_instruments')) linked
               WHERE json_extract(linked.value, '$[0]') = 'a_share'
                 AND json_extract(linked.value, '$[1]') = ?
                 AND json_extract(news_events.payload, '$.review_state') = 'verified'
                 AND (? IS NULL OR json_extract(
                     news_events.payload, '$.normalized_at'
                 ) <= ?)
                 AND (? IS NULL OR json_extract(
                     news_events.payload, '$.occurred_at'
                 ) <= ?)
               ORDER BY news_events.sequence""",
            (
                symbol,
                normalized_cutoff,
                normalized_cutoff,
                normalized_cutoff,
                normalized_cutoff,
            ),
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
