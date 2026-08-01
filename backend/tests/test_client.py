"""The ClickHouse client is memoized so one pooled connection is reused across queries."""
from data import client as ch


def test_get_client_is_memoized(monkeypatch):
    created = []

    def fake_get_client(**kwargs):
        obj = object()
        created.append(obj)
        return obj

    monkeypatch.setattr(ch.clickhouse_connect, "get_client", fake_get_client)
    ch.get_client.cache_clear()
    try:
        first = ch.get_client()
        second = ch.get_client()
        assert first is second       # same client instance reused
        assert len(created) == 1     # underlying connection built only once
    finally:
        ch.get_client.cache_clear()
