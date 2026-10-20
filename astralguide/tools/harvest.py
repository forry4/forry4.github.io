"""Fetch every main-namespace page of the Astral Ascent wiki (astralascent.wiki.gg) as
wikitext into tools/cache/pages.json. make_data.py turns that into the shipped payload.

The wiki's `?action=raw` and HTML pages answer a script with a "Blocked" page, but the
MediaWiki API (api.php) is open, so everything goes through it, 40 titles per request.
"""
import json
import os
import urllib.parse
import urllib.request

API = "https://astralascent.wiki.gg/api.php"
UA = "ForrestGamesGuideHarvester/1.0 (personal fan guide; one pass, cached)"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")


def api(**params):
	params["format"] = "json"
	req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={"User-Agent": UA})
	with urllib.request.urlopen(req, timeout=60) as r:
		return json.load(r)


def all_titles():
	titles, cont = [], {}
	while True:
		d = api(action="query", list="allpages", aplimit=500, apfilterredir="nonredirects", **cont)
		titles += [p["title"] for p in d["query"]["allpages"]]
		if "continue" not in d:
			return titles
		cont = {"apcontinue": d["continue"]["apcontinue"]}


def main():
	os.makedirs(CACHE, exist_ok=True)
	titles = all_titles()
	pages = {}
	for i in range(0, len(titles), 40):
		d = api(action="query", prop="revisions", rvprop="content|timestamp", rvslots="main",
			titles="|".join(titles[i:i + 40]))
		for p in d["query"]["pages"].values():
			rev = (p.get("revisions") or [None])[0]
			if rev:
				pages[p["title"]] = {"text": rev["slots"]["main"]["*"], "ts": rev["timestamp"]}
	# Every page must have come back, or a section of the guide is silently empty.
	missing = sorted(set(titles) - set(pages))
	if missing:
		raise SystemExit(f"{len(missing)} pages came back without content: {missing[:10]}")
	with open(os.path.join(CACHE, "pages.json"), "w", encoding="utf-8") as f:
		json.dump(pages, f, ensure_ascii=False, indent=0)
	print(f"{len(pages)} pages cached")


if __name__ == "__main__":
	main()
