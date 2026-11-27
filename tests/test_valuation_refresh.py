from threading import Event
from unittest.mock import Mock

import tax_sale_app as app


def test_shared_background_sales_refresh(monkeypatch):
    release = Event()
    catalog = (None, None, "2026-06-18")
    def stalled_feed(day):
        assert release.wait(5)
        return catalog
    feed = Mock(side_effect=stalled_feed)
    comparison = Mock(return_value=(125000, [], "single family"))
    monkeypatch.setattr(app, "sold_catalog", feed)
    monkeypatch.setattr(app, "sold_comparison", comparison)
    service = app.SoldValuations()
    parcels = frozenset(app.comp_apn(p) for p in ["1-01-15-002.01", "1011500201"])
    try:
        for _ in range(3):
            values, _, _, _, busy = service.snapshot(parcels)
            assert busy and not values
        release.set()
        service.job.result(timeout=5)
        values, _, updated, _, busy = service.snapshot(parcels)
        assert values["1011500201"][0] == 125000 and not busy
        comparison.assert_called_once()
        feed.assert_called_once()
        service.refresh_at = 0
        feed.side_effect = ValueError("Malformed feed")
        service.snapshot(parcels)
        service.worker.submit(lambda: None).result(timeout=5)
        for _ in range(3):
            stale, _, timestamp, error, busy = service.snapshot(parcels)
            assert stale == values and timestamp == updated and error and not busy
        assert feed.call_count == 2
        feed.side_effect = None
        feed.return_value = (None, None, "2026-11-26")
        service.snapshot(parcels, retry=True)
        service.job.result(timeout=5)
        assert service.snapshot(parcels)[1] == "2026-11-26"
        assert comparison.call_count == 2
    finally:
        release.set()
        service.worker.shutdown()
