import datetime as dt


def utcnow() -> dt.datetime:
    """Current UTC time as a naive datetime.

    Returns exactly what datetime.utcnow() returns, so stored timestamps and
    comparisons behave as before, without the DeprecationWarning that
    datetime.utcnow() has raised since Python 3.12."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
