from datetime import datetime, timedelta

from qibao_api.contracts.market import DataQuality


def assess_observed_at(
    observed_at: datetime,
    now: datetime,
    max_age: timedelta,
) -> DataQuality:
    age = now - observed_at
    if timedelta(0) <= age <= max_age:
        return DataQuality.FRESH
    return DataQuality.STALE

