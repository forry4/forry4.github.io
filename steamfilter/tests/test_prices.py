"""Steam and eShop prices, off canned store answers shaped like the real ones."""
import json
import urllib.parse

import pytest

from steamfilter.tools import prices as p


# ── Steam ─────────────────────────────────────────────────────────────────

def test_a_full_price_game():
    item = {"best_purchase_option": {"final_price_in_cents": "1499", "formatted_final_price": "$14.99"}}
    assert p.steam_price(item) == [1499]


def test_a_sale_carries_its_regular_price_and_end():
    item = {"best_purchase_option": {
        "final_price_in_cents": "624", "original_price_in_cents": "2499", "discount_pct": 75,
        "active_discounts": [{"discount_amount": "1875", "discount_end_date": 1793725200}]}}
    assert p.steam_price(item) == [624, 2499, 1793725200]


def test_stacked_discounts_end_when_the_first_one_does():
    item = {"best_purchase_option": {
        "final_price_in_cents": "500", "original_price_in_cents": "2000",
        "active_discounts": [{"discount_end_date": 1800000000}, {"discount_end_date": 1790000000}]}}
    assert p.steam_price(item)[2] == 1790000000


def test_a_discount_with_no_end_has_none():
    item = {"best_purchase_option": {"final_price_in_cents": "500", "original_price_in_cents": "2000"}}
    assert p.steam_price(item) == [500, 2000]


def test_free_unbuyable_and_hidden_discounts():
    assert p.steam_price({"is_free": True, "best_purchase_option": None}) == [0]
    assert p.steam_price({"name": "Delisted"}) is None
    item = {"best_purchase_option": {"final_price_in_cents": "500", "original_price_in_cents": "2000",
                                     "price_cannot_be_displayed_as_discount": True}}
    assert p.steam_price(item) == [500]


def steam_fetch(items, seen=None):
    def fetch(url, check):
        q = json.loads(urllib.parse.unquote(url.split("input_json=", 1)[1]))
        assert q["data_request"] == {"include_all_purchase_options": True}
        ids = [x["appid"] for x in q["ids"]]
        if seen is not None:
            seen.append(ids)
        return check(json.dumps({"response": {"store_items": [
            dict(items[a], appid=a) for a in ids if a in items]}}))
    return fetch


def test_steam_is_asked_in_batches_of_a_hundred(monkeypatch):
    monkeypatch.setattr(p.time, "sleep", lambda s: None)
    seen = []
    items = {a: {"best_purchase_option": {"final_price_in_cents": "999"}} for a in range(1, 251)}
    out = p.steam_prices(steam_fetch(items, seen), lambda m: None, list(range(1, 251)), pause=0)
    assert [len(b) for b in seen] == [100, 100, 50]
    assert out[250] == [999]


def test_a_thin_steam_answer_fails():
    items = {1: {"best_purchase_option": {"final_price_in_cents": "999"}}}
    with pytest.raises(SystemExit):
        p.steam_prices(steam_fetch(items), lambda m: None, [1, 2, 3], pause=0)


# ── the eShop ─────────────────────────────────────────────────────────────

def hit(title, regular, sale=None, start=None, end=None, platform="Nintendo Switch", dlc=None):
    return {"title": title, "platform": platform, "dlcType": dlc, "eshopDetails": {
        "regularPrice": regular, "discountPrice": sale,
        "discountPriceStart": start, "discountPriceEnd": end}}


def test_an_eshop_sale_carries_its_window():
    h = hit("Balatro", 14.99, 12.74, "2026-10-20T16:00:00Z", "2026-11-01T06:59:59Z")
    assert p.eshop_price(h) == [1274, 1499, 1793516399, 1792512000]


def test_eshop_listings_that_are_not_a_buyable_game():
    assert p.eshop_price(hit("Doom Pack", 0.99, dlc="Individual")) is None
    assert p.eshop_price(hit("It Takes Two", None)) is None
    # A ROM Bundle is a game sold with its DLC — DOOM Eternal's base listing is one.
    assert p.eshop_price(hit("DOOM Eternal", 29.99, dlc="ROM Bundle")) == [2999]
    assert p.eshop_price(hit("Free", 0)) == [0]


def eshop_fetch(results):
    """Answers each query in a request from `results` ({query: [hits]})."""
    asked = []

    def fetch(url, check, data=None, headers=None):
        assert url == p.ALGOLIA and headers["X-Algolia-Application-Id"]
        reqs = json.loads(data)["requests"]
        qs = [urllib.parse.parse_qs(r["params"])["query"][0] for r in reqs]
        asked.append(qs)
        return check(json.dumps({"results": [{"hits": results.get(q, [])} for q in qs]}))
    fetch.asked = asked
    return fetch


def test_switch_prices_match_by_title_and_take_the_cheapest_listing(monkeypatch):
    monkeypatch.setattr(p.time, "sleep", lambda s: None)
    fetch = eshop_fetch({
        "hollow knight": [hit("Hollow Knight", 15.0),
                          hit("Hollow Knight – Nintendo Switch 2 Edition", 19.99, platform="Nintendo Switch 2"),
                          hit("Hollow Knight: Silksong", 19.99)],
        "doom eternal": [hit("DOOM® Eternal Deluxe Edition", 49.99),
                         hit("DOOM® Eternal", 29.99, 9.89, "2026-10-20T16:00:00Z", "2026-11-01T06:59:59Z"),
                         hit("DOOM Eternal: Rip and Tear Pack", 0.99, dlc="Individual")],
        "hades": [hit("Hades II", 29.99)],
    })
    games = [{"n": "Hollow Knight", "id": 1, "sw": 1}, {"n": "DOOM Eternal", "id": 2, "sw": 1},
             {"n": "Hades", "id": 3, "sw": 1}, {"n": "Not On Switch", "id": 4}]
    with pytest.raises(SystemExit):   # 2 of 3: under the floor
        p.switch_prices(fetch, lambda m: None, games, canaries=[])
    monkeypatch.setattr(p, "MIN_SWITCH", 0.5)
    out = p.switch_prices(fetch, lambda m: None, games, canaries=[])
    assert out == {1: {"w": [1500], "w2": 1}, 2: {"w": [989, 2999, 1793516399, 1792512000]}}
    # Only `sw` games are asked, by their folded title.
    assert fetch.asked[-1] == ["hollow knight", "doom eternal", "hades"]


def test_switch_queries_go_fifty_a_request(monkeypatch):
    monkeypatch.setattr(p.time, "sleep", lambda s: None)
    games = [{"n": f"Game {i}", "id": i, "sw": 1} for i in range(120)]
    fetch = eshop_fetch({f"game {i}": [hit(f"Game {i}", 9.99)] for i in range(120)})
    out = p.switch_prices(fetch, lambda m: None, games, canaries=[])
    assert [len(q) for q in fetch.asked] == [50, 50, 20] and len(out) == 120


def test_a_missing_canary_fails(monkeypatch):
    monkeypatch.setattr(p.time, "sleep", lambda s: None)
    monkeypatch.setattr(p, "MIN_SWITCH", 0)
    games = [{"n": "Hades", "id": 1, "sw": 1}]
    with pytest.raises(SystemExit, match="Hades"):
        p.switch_prices(eshop_fetch({}), lambda m: None, games, canaries=["Hades"])


def test_eshop_answer_must_have_one_result_per_query():
    with pytest.raises(p.Rejected):
        p.validate_queries(2)(json.dumps({"results": [{"hits": []}]}))
    with pytest.raises(p.Rejected):
        p.validate_queries(1)("<html>blocked</html>")


# ── the file ──────────────────────────────────────────────────────────────

def test_an_unchanged_answer_leaves_the_file_alone(monkeypatch, tmp_path):
    payload = tmp_path / "steam-filter.json"
    payload.write_text(json.dumps({"games": [{"n": "A", "id": 1, "sw": 1}]}))
    monkeypatch.setattr(p, "PAYLOAD", str(payload))
    monkeypatch.setattr(p, "steam_prices", lambda f, l, ids: {1: [999]})
    monkeypatch.setattr(p, "switch_prices", lambda f, l, g: {1: {"w": [1999], "w2": 1}})
    out = tmp_path / "steam-prices.json"
    p.main(["--out", str(out)])
    first = json.loads(out.read_text())
    assert first["games"] == {"1": {"s": [999], "w": [1999], "w2": 1}} and first["region"] == "US"
    out.write_text(json.dumps(dict(first, priced="earlier")))
    p.main(["--out", str(out)])
    assert json.loads(out.read_text())["priced"] == "earlier"
