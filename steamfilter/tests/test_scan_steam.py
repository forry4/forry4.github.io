"""The harvester's parsing and admission rule, off canned store markup.

The harvest itself needs the network; what can silently go wrong offline is the
parse (a row read as the wrong game, a bundle read as a game, a tooltip missed)
and the 90%-English rule, so those are pinned here."""
import json

import pytest

from steamfilter.tools import scan_steam as s

# Shaped like a real /search/results row: one game with a tooltip, one game too
# thin to have a score, one bundle (no single app id), one comma-joined package.
PAGE = """
<a href="https://store.steampowered.com/app/413150/Stardew_Valley/?snr=1" data-ds-appid="413150"
   data-ds-itemkey="App_413150" data-ds-tagids="[492,1662]" class="search_result_row ds_collapse_flag " >
  <div class="col search_capsule"><img src="x.jpg"></div>
  <div class="responsive_search_name_combined">
    <div class="col search_name ellipsis"><span class="title">Stardew Valley &amp; Friends</span></div>
    <div class="col search_released responsive_secondrow">26 Feb, 2016</div>
    <div class="col search_reviewscore responsive_secondrow">
      <span class="search_review_summary positive" data-tooltip-html="Overwhelmingly Positive&lt;br&gt;98% of the 612,345 user reviews for this game are positive.">
      </span>
    </div>
  </div>
</a>
<a href="https://store.steampowered.com/app/999/Tiny/" data-ds-appid="999" class="search_result_row ds_collapse_flag" >
  <span class="title">Tiny</span>
  <div class="col search_released responsive_secondrow">Coming soon</div>
  <div class="col search_reviewscore responsive_secondrow"></div>
</a>
<a href="https://store.steampowered.com/bundle/1/B/" data-ds-bundleid="1" data-ds-appid="1,2,3" class="search_result_row" >
  <span class="title">A Bundle</span>
</a>
<a href="https://store.steampowered.com/sub/7/" data-ds-packageid="7" data-ds-appid="12" class="search_result_row" >
  <span class="title">A Package</span>
</a>
"""


def test_parse_search_reads_games_and_skips_bundles():
    rows, games = s.parse_search(PAGE)
    assert rows == 4   # every row is counted, so a short page is still detectable
    assert [g["id"] for g in games] == [413150, 999]
    sv, tiny = games
    assert sv == {"id": 413150, "n": "Stardew Valley & Friends", "y": 2016, "pct": 98, "count": 612345}
    assert tiny["pct"] is None and tiny["count"] is None and tiny["y"] is None


@pytest.mark.parametrize("text,year", [
    ("26 Feb, 2016", 2016), ("Feb 26, 2016", 2016), ("Q1 2027", 2027), ("2009", 2009),
    ("Coming soon", None), ("To be announced", None), ("", None),
])
def test_year_of(text, year):
    assert s.year_of(text) == year


def test_admission_is_ninety_percent_of_english_reviews_and_the_floor():
    assert s.keep(90, 100, 50)            # exactly 90% is in
    assert not s.keep(89, 100, 50)
    assert not s.keep(49, 49, 50)         # perfect but under the floor
    assert s.keep(50, 50, 50)


def test_prefilter_is_looser_than_the_rule():
    # A game shown at 85% on the store can still be 90%+ in English.
    assert s.is_candidate({"pct": 85, "count": 60}, 50)
    assert not s.is_candidate({"pct": 79, "count": 60}, 50)
    assert not s.is_candidate({"pct": 99, "count": 40}, 50)
    assert not s.is_candidate({"pct": None, "count": None}, 50)


def test_responses_must_prove_themselves():
    with pytest.raises(s.Rejected):
        s.validate_search("<html>Access Denied</html>")
    with pytest.raises(s.Rejected):
        s.validate_search(json.dumps({"success": 2}))
    assert s.validate_search(json.dumps({"success": 1, "results_html": "", "total_count": 5}))
    with pytest.raises(s.Rejected):
        s.validate_reviews(json.dumps({"success": 1}))
    ok = s.validate_reviews(json.dumps({"success": 1, "query_summary": {
        "total_positive": 9, "total_negative": 1, "total_reviews": 10}}))
    assert ok["query_summary"]["total_reviews"] == 10
