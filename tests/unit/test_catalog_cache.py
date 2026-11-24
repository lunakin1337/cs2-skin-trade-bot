"""Тесты кэша каталога: ETag, TTL и версия каталога."""

import pytest

from catalog_cache import CatalogCache, etag_matches, make_etag


class TestEtag:
    def test_stable_and_quoted(self):
        first = make_etag(b'{"a": 1}')
        second = make_etag(b'{"a": 1}')

        assert first == second
        assert first.startswith('"') and first.endswith('"')
        assert make_etag(b'{"a": 2}') != first

    @pytest.mark.parametrize(
        "header",
        [
            '"abc"',
            "W/\"abc\"",
            '"xyz", "abc"',
            " * ",
        ],
    )
    def test_matches_expected_header(self, header):
        assert etag_matches(header, '"abc"') is True

    @pytest.mark.parametrize("header", [None, "", '"other"', 'W/"other"'])
    def test_rejects_other_header(self, header):
        assert etag_matches(header, '"abc"') is False


class TestCatalogCache:
    def test_returns_entry_within_ttl(self):
        cache = CatalogCache()
        etag = cache.put("k", "1", b"body")

        assert cache.get("k", "1", 60) == (etag, b"body")
        assert len(cache) == 1

    def test_expires_after_ttl(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr("catalog_cache.time.monotonic", lambda: clock[0])

        cache = CatalogCache()
        cache.put("k", "1", b"body")

        clock[0] += 61
        assert cache.get("k", "1", 60) is None
        assert len(cache) == 0

    def test_zero_ttl_disables_cache(self):
        cache = CatalogCache()
        cache.put("k", "1", b"body")

        assert cache.get("k", "1", 0) is None

    def test_new_version_drops_stale_entry(self):
        cache = CatalogCache()
        cache.put("k", "1", b"body")

        assert cache.get("k", "2", 60) is None
        assert cache.get("k", "1", 60) is None

    def test_clear(self):
        cache = CatalogCache()
        cache.put("a", "1", b"a")
        cache.put("b", "1", b"b")

        cache.clear()
        assert len(cache) == 0
