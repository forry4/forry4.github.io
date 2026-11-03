"""Anime Filter harvester — three rating sites, one raw file.

Runs on a GitHub runner (.github/workflows/anime-harvest.yml): the dev container's
network policy reaches GitHub and nothing else, so every site below is asked from
there. Writes animefilter/tools/results_all.json; make_data.py turns that into the
shipped payload, offline, as often as it likes.

Sources:
  * AniList (graphql.anilist.co) — score, popularity, English title, genres, tags,
    start date and the SEQUEL/PREQUEL relations that group seasons into a show.
  * MyAnimeList, through Jikan (api.jikan.moe/v4) — score, voters, members, English
    title, demographic. MAL's own API needs a registered client id.
  * Kitsu (kitsu.app/api/edge) — average rating and its vote count.
  * manami-project/anime-offline-database (a GitHub release) — the cross-site id map
    (which Kitsu entry is which AniList entry).
  * MAL-Dubs (raw.githubusercontent.com) — MAL ids with an English dub.

Universe: AniList's score-ranked list above a popularity floor, plus MAL's top list
above a score floor, plus every sequel/prequel of either (a franchise must be averaged
over ALL its seasons, not just the ones good enough to chart on their own).

Every answer is validated BEFORE it is cached (the BGG lesson: a cached rate-limit
page reads as "no data" forever) and cached under tools/cache/ so a re-run resumes.
"""
import argparse, hashlib, json, os, socket, sys, time, urllib.error, urllib.parse, urllib.request

# Try IPv4 addresses first. The first runner harvest died on Jikan with "Network is
# unreachable" (errno 101) — the shape of an IPv6 address on a host with no IPv6 route.
_gai = socket.getaddrinfo
def _v4_first(*a, **k):
	return sorted(_gai(*a, **k), key=lambda r: r[0] != socket.AF_INET)
socket.getaddrinfo = _v4_first

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "results_all.json")
UA = "forrest-games-anime-filter/1.0 (+https://forry4.github.io/animefilter)"

ANILIST = "https://graphql.anilist.co"
JIKAN = "https://api.jikan.moe/v4"
KITSU = "https://kitsu.io/api/edge"  # kitsu.app answers runners with a Cloudflare 403
AOD = "https://github.com/manami-project/anime-offline-database/releases/latest/download/anime-offline-database-minified.json"
DUBS = "https://raw.githubusercontent.com/MAL-Dubs/MAL-Dubs/main/data/dubInfo.json"

# Formats that can be a "season" or a film. Specials, OVAs, music videos and recaps
# are neither, and would pull a show's average around without being the show.
SHOW_FORMATS = ["TV", "TV_SHORT", "ONA", "MOVIE"]
MAL_TYPES = {"TV", "ONA", "Movie"}
GROUP_EDGES = {"SEQUEL", "PREQUEL"}

# Minimum seconds between requests, per host. AniList's documented limit is 90/min
# but it has run "degraded" at 30/min for long stretches; Jikan allows 60/min.
GAP = {"graphql.anilist.co": 2.1, "api.jikan.moe": 1.15, "kitsu.io": 0.5}
_last = {}


class Reject(Exception):
	"""A response that arrived but is not data — never cached, always retried."""


def _key(url, body):
	return hashlib.sha1((url + "\n" + (body or "")).encode()).hexdigest()


def fetch(url, body=None, validate=None, fresh_hours=72, tries=10):
	"""GET (or POST `body` as JSON) -> parsed JSON, through the cache.

	A 404 is a real answer ("no such entry") and is cached as None. 429 and 5xx back
	off (honouring Retry-After); anything `validate` rejects is retried, never cached.
	"""
	os.makedirs(CACHE, exist_ok=True)
	path = os.path.join(CACHE, _key(url, body) + ".json")
	if os.path.exists(path) and time.time() - os.path.getmtime(path) < fresh_hours * 3600:
		with open(path, encoding="utf-8") as f:
			return json.load(f)["v"]
	host = urllib.parse.urlparse(url).hostname
	err = None
	for attempt in range(tries):
		wait = GAP.get(host, 1.0) - (time.time() - _last.get(host, 0))
		if wait > 0:
			time.sleep(wait)
		_last[host] = time.time()
		headers = {"User-Agent": UA, "Accept": "application/json"}
		data = None
		if body is not None:
			headers["Content-Type"] = "application/json"
			data = body.encode()
		req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
		try:
			with urllib.request.urlopen(req, timeout=60) as r:
				raw = r.read()
			v = json.loads(raw)
			if validate:
				validate(v)
		except urllib.error.HTTPError as e:
			if e.code == 404:
				v = None
			elif e.code in (429, 500, 502, 503, 504, 520, 522, 524):
				ra = e.headers.get("Retry-After")
				delay = float(ra) + 1 if ra and ra.isdigit() else min(60, 5 * (attempt + 1))
				err = f"HTTP {e.code}"
				print(f"  {host}: {err}, waiting {delay:.0f}s", flush=True)
				time.sleep(delay)
				continue
			else:
				# AniList answers a malformed/over-complex query with 400 + an errors body.
				detail = e.read()[:300]
				raise RuntimeError(f"{url}: HTTP {e.code} {detail!r}")
		except (Reject, ValueError) as e:
			err = f"rejected: {e}"
			print(f"  {host}: {err}", flush=True)
			time.sleep(min(30, 3 * (attempt + 1)))
			continue
		except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
			err = str(e)
			time.sleep(min(30, 3 * (attempt + 1)))
			continue
		with open(path, "w", encoding="utf-8") as f:
			json.dump({"url": url, "v": v}, f)
		return v
	raise RuntimeError(f"{url}: gave up after {tries} tries ({err})")


# ---------------------------------------------------------------- AniList

MEDIA_FIELDS = """
id idMal title { romaji english native } synonyms format episodes duration status
countryOfOrigin startDate { year month day } season seasonYear
averageScore meanScore popularity favourites genres
tags { name rank isGeneralSpoiler isMediaSpoiler isAdult category }
studios(isMain: true) { nodes { name } }
relations { edges { relationType node { id idMal type format } } }
coverImage { medium }
"""

Q_TOP = """query ($page: Int, $pop: Int) { Page(page: $page, perPage: 50) {
pageInfo { hasNextPage }
media(type: ANIME, sort: [SCORE_DESC], popularity_greater: $pop, isAdult: false,
      format_in: [TV, TV_SHORT, ONA, MOVIE]) { %s } } }""" % MEDIA_FIELDS

Q_IDS = """query ($ids: [Int]) { Page(page: 1, perPage: 50) {
media(type: ANIME, id_in: $ids) { %s } } }""" % MEDIA_FIELDS

Q_MAL = """query ($ids: [Int]) { Page(page: 1, perPage: 50) {
media(type: ANIME, idMal_in: $ids) { %s } } }""" % MEDIA_FIELDS


def v_anilist(v):
	if not isinstance(v, dict) or v.get("errors") or not isinstance((v.get("data") or {}).get("Page"), dict):
		raise Reject(str(v)[:200])
	if not isinstance(v["data"]["Page"].get("media"), list):
		raise Reject("no media list")


def anilist(query, **variables):
	return fetch(ANILIST, json.dumps({"query": query, "variables": variables}, sort_keys=True),
		validate=v_anilist)["data"]["Page"]


def anilist_top(pop_floor, score_floor, max_pages=200):
	out = {}
	for page in range(1, max_pages + 1):
		p = anilist(Q_TOP, page=page, pop=pop_floor)
		media = p["media"]
		for m in media:
			out[m["id"]] = m
		low = min((m["averageScore"] or 0) for m in media) if media else 0
		print(f"AniList top page {page}: {len(media)} (lowest score {low}), {len(out)} total", flush=True)
		if not media or not p["pageInfo"]["hasNextPage"] or low < score_floor:
			break
	return out


def anilist_by(query, ids):
	out = {}
	ids = sorted(set(ids))
	for i in range(0, len(ids), 50):
		for m in anilist(query, ids=ids[i:i + 50])["media"]:
			out[m["id"]] = m
	return out


def group_neighbours(m):
	"""AniList ids joined to `m` by a sequel/prequel edge to another show-format entry."""
	for e in (m.get("relations") or {}).get("edges") or []:
		n = e.get("node") or {}
		if e.get("relationType") in GROUP_EDGES and n.get("type") == "ANIME" and n.get("format") in SHOW_FORMATS:
			yield n["id"]


def close_over_sequels(al, cap):
	"""Pull in every sequel/prequel (transitively) of what is already held."""
	for rnd in range(30):
		want = {n for m in list(al.values()) if m.get("format") in SHOW_FORMATS
			for n in group_neighbours(m)} - set(al)
		if not want:
			return
		if len(al) + len(want) > cap:
			raise RuntimeError(f"sequel closure passed the {cap}-entry cap — a relation chain is runaway")
		print(f"sequel closure round {rnd + 1}: {len(want)} more", flush=True)
		al.update(anilist_by(Q_IDS, want))


# ---------------------------------------------------------------- MyAnimeList (Jikan)

def v_jikan(v):
	if not isinstance(v, dict) or "data" not in v:
		raise Reject(str(v)[:200])


def mal_trim(a):
	"""The fields make_data reads, so results_all.json stays a sane size."""
	return {
		"id": a["mal_id"], "title": a.get("title"), "title_english": a.get("title_english"),
		"type": a.get("type"), "episodes": a.get("episodes"), "status": a.get("status"),
		"score": a.get("score"), "scored_by": a.get("scored_by"), "rank": a.get("rank"),
		"members": a.get("members"), "year": a.get("year"),
		"aired_from": (a.get("aired") or {}).get("from"),
		"genres": [g["name"] for g in a.get("genres") or []],
		"themes": [g["name"] for g in a.get("themes") or []],
		"demographics": [g["name"] for g in a.get("demographics") or []],
	}


def mal_top(score_floor, max_pages=400):
	out = {}
	for page in range(1, max_pages + 1):
		v = fetch(f"{JIKAN}/top/anime?page={page}", validate=v_jikan)
		rows = v["data"]
		for a in rows:
			out[a["mal_id"]] = mal_trim(a)
		low = min((a.get("score") or 0) for a in rows) if rows else 0
		if page % 10 == 0 or not rows:
			print(f"MAL top page {page}: {len(out)} total (lowest score {low})", flush=True)
		if not rows or not (v.get("pagination") or {}).get("has_next_page") or low < score_floor:
			break
	return out


def mal_one(mid):
	v = fetch(f"{JIKAN}/anime/{mid}", validate=v_jikan)
	return mal_trim(v["data"]) if v and v.get("data") else None


# ---------------------------------------------------------------- Kitsu

def v_kitsu(v):
	if not isinstance(v, dict) or not isinstance(v.get("data"), list):
		raise Reject(str(v)[:200])


def kitsu_trim(k):
	a = k.get("attributes") or {}
	freq = a.get("ratingFrequencies") or {}
	votes = sum(int(x) for x in freq.values() if str(x).isdigit())
	t = a.get("titles") or {}
	return {"id": int(k["id"]), "rating": float(a["averageRating"]) if a.get("averageRating") else None,
		"votes": votes, "users": a.get("userCount"), "title_en": t.get("en") or t.get("en_us"),
		"canonical": a.get("canonicalTitle"), "subtype": a.get("subtype")}


def kitsu_many(ids):
	out = {}
	ids = sorted(set(ids))
	fields = "canonicalTitle,titles,averageRating,userCount,ratingFrequencies,subtype"
	for i in range(0, len(ids), 20):
		chunk = ",".join(str(x) for x in ids[i:i + 20])
		v = fetch(f"{KITSU}/anime?filter%5Bid%5D={chunk}&page%5Blimit%5D=20&fields%5Banime%5D={fields}",
			validate=v_kitsu)
		for k in v["data"]:
			out[int(k["id"])] = kitsu_trim(k)
	return out


def kitsu_from_mal(mid):
	v = fetch(f"{KITSU}/mappings?filter%5BexternalSite%5D=myanimelist/anime&filter%5BexternalId%5D={mid}&include=item",
		validate=v_kitsu)
	for inc in (v or {}).get("included") or []:
		if inc.get("type") == "anime":
			return int(inc["id"])
	return None


# ---------------------------------------------------------------- the cross-site map

def site_id(sources, prefix):
	for s in sources:
		if s.startswith(prefix):
			tail = s[len(prefix):].split("/")[0].split("?")[0]
			if tail.isdigit():
				return int(tail)
	return None


def v_aod(v):
	if len((v or {}).get("data") or []) < 20000:
		raise Reject("offline database came back short")


def v_dubs(v):
	if len((v or {}).get("dubbed") or []) < 2000:
		raise Reject("dub list came back short")


def aod_maps(aod):
	"""AniList id -> Kitsu id, and MAL id -> Kitsu id, from the offline database."""
	by_al, by_mal = {}, {}
	for a in aod["data"]:
		src = a.get("sources") or []
		k = site_id(src, "https://kitsu.app/anime/") or site_id(src, "https://kitsu.io/anime/")
		if not k:
			continue
		al = site_id(src, "https://anilist.co/anime/")
		mal = site_id(src, "https://myanimelist.net/anime/")
		if al:
			by_al[al] = k
		if mal:
			by_mal[mal] = k
	return by_al, by_mal


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--anilist-pop", type=int, default=8000, help="AniList popularity floor for the top list")
	ap.add_argument("--anilist-score", type=int, default=68, help="stop paging AniList below this score")
	ap.add_argument("--mal-score", type=float, default=7.0, help="stop paging MAL below this score")
	ap.add_argument("--mal-members", type=int, default=20000, help="MAL top entries below this aren't chased onto AniList")
	ap.add_argument("--cap", type=int, default=12000)
	args = ap.parse_args()
	t0 = time.time()

	aod = fetch(AOD, validate=v_aod, fresh_hours=24 * 7)
	dubs = fetch(DUBS, validate=v_dubs, fresh_hours=24)
	k_by_al, k_by_mal = aod_maps(aod)
	print(f"offline database {aod.get('lastUpdate')}: {len(k_by_al)} AniList->Kitsu links; {len(dubs['dubbed'])} dubbed MAL ids", flush=True)

	al = anilist_top(args.anilist_pop, args.anilist_score)
	mal = mal_top(args.mal_score)
	print(f"AniList top: {len(al)}, MAL top: {len(mal)}", flush=True)

	have_mal = {m["idMal"] for m in al.values() if m.get("idMal")}
	chase = [a["id"] for a in mal.values() if a["type"] in MAL_TYPES and (a["members"] or 0) >= args.mal_members
		and a["id"] not in have_mal]
	print(f"MAL-top entries missing from AniList's list: {len(chase)}", flush=True)
	al.update(anilist_by(Q_MAL, chase))
	close_over_sequels(al, args.cap)
	print(f"AniList universe after the sequel closure: {len(al)}", flush=True)

	need = sorted({m["idMal"] for m in al.values() if m.get("idMal")} - set(mal))
	print(f"MAL details to fetch one by one: {len(need)}", flush=True)
	for i, mid in enumerate(need):
		a = mal_one(mid)
		if a:
			mal[mid] = a
		if (i + 1) % 100 == 0:
			print(f"  MAL {i + 1}/{len(need)}", flush=True)

	kmap = {}
	for m in al.values():
		k = k_by_al.get(m["id"]) or (m.get("idMal") and k_by_mal.get(m["idMal"]))
		if k:
			kmap[m["id"]] = k
	missing = [m for m in al.values() if m["id"] not in kmap and m.get("idMal")]
	print(f"Kitsu ids from the offline database: {len(kmap)}; by mapping lookup: {len(missing)}", flush=True)
	for m in missing:
		k = kitsu_from_mal(m["idMal"])
		if k:
			kmap[m["id"]] = k
	kitsu = kitsu_many(kmap.values())
	print(f"Kitsu entries: {len(kitsu)}", flush=True)

	# The canaries: a harvest that lost one of these lost far more in silence.
	for name, alid in (("Fullmetal Alchemist: Brotherhood", 5114), ("Attack on Titan", 16498),
			("Steins;Gate", 9253), ("Frieren", 154587)):
		if alid not in al:
			raise SystemExit(f"canary missing from AniList: {name} ({alid})")
		mid = al[alid].get("idMal")
		if mid not in mal or not mal[mid].get("score"):
			raise SystemExit(f"canary missing from MAL: {name} ({mid})")
		if alid not in kmap or kmap[alid] not in kitsu:
			raise SystemExit(f"canary missing from Kitsu: {name}")
	if len(kitsu) < 0.8 * len(al):
		raise SystemExit(f"Kitsu covered only {len(kitsu)} of {len(al)} entries")

	out = {
		"collected": time.strftime("%Y-%m-%d", time.gmtime()),
		"aod_updated": aod.get("lastUpdate"),
		"floors": vars(args),
		"anilist": {str(k): v for k, v in al.items()},
		"mal": {str(k): v for k, v in mal.items()},
		"kitsu": {str(k): v for k, v in kitsu.items()},
		"kitsu_for": {str(k): v for k, v in kmap.items()},
		"dubbed": dubs["dubbed"], "dub_incomplete": dubs.get("incomplete") or [],
	}
	with open(OUT, "w", encoding="utf-8") as f:
		json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
	print(f"wrote {OUT}: {len(al)} AniList, {len(mal)} MAL, {len(kitsu)} Kitsu in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
	sys.exit(main())
