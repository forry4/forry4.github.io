// The data store's Worker (data-worker/src/index.js) and the page-side reader
// (shared/dataUrl.js), against a stand-in R2 bucket and a stand-in fetch.
import test from "node:test";
import assert from "node:assert/strict";
import { handle, MAX_BYTES } from "../../../data-worker/src/index.js";
import { fetchData } from "../../../shared/dataUrl.js";

function bucket() {
	const store = new Map();
	let n = 0;
	return {
		store,
		async get(key) {
			const o = store.get(key);
			return o ? { body: o.bytes, httpEtag: o.etag, uploaded: o.uploaded } : null;
		},
		async put(key, bytes) {
			const o = { bytes, etag: `"v${++n}"`, uploaded: Date.now() };
			store.set(key, o);
			return { httpEtag: o.etag };
		},
	};
}
const env = () => ({ DATA: bucket(), PUBLISH_TOKEN: "s3cret-token" });
const req = (method, path, { token, body, headers = {} } = {}) => new Request(`https://data.example${path}`, {
	method, body, headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...headers },
});

test("a published file is served back, CORS-open, with an ETag and a short max-age", async () => {
	const e = env();
	const put = await handle(req("PUT", "/steam-prices.json", { token: "s3cret-token", body: '{"games":{"1":[5,10,0,0]}}' }), e);
	assert.equal(put.status, 200);
	const got = await handle(req("GET", "/steam-prices.json"), e);
	assert.equal(got.status, 200);
	assert.deepEqual(await got.json(), { games: { 1: [5, 10, 0, 0] } });
	assert.equal(got.headers.get("Access-Control-Allow-Origin"), "*");
	assert.match(got.headers.get("Cache-Control"), /max-age=300/);
	const etag = got.headers.get("ETag");
	assert.ok(etag);
	const again = await handle(req("GET", "/steam-prices.json", { headers: { "If-None-Match": etag } }), e);
	assert.equal(again.status, 304);
	assert.equal((await handle(req("HEAD", "/steam-prices.json"), e)).status, 200);
});

test("only the publish token can write", async () => {
	const e = env();
	for (const token of [undefined, "", "wrong", "s3cret-toke", "s3cret-token2"]) {
		const r = await handle(req("PUT", "/x.json", { token, body: "{}" }), e);
		assert.equal(r.status, 401, String(token));
	}
	assert.equal(e.DATA.store.size, 0);
	// A Worker deployed without its secret must refuse everyone, not accept an empty token.
	const open = { DATA: bucket() };
	assert.equal((await handle(req("PUT", "/x.json", { body: "{}" }), open)).status, 401);
	assert.equal((await handle(req("PUT", "/x.json", { token: "undefined", body: "{}" }), open)).status, 401);
});

test("a body that is not JSON never replaces a good file", async () => {
	const e = env();
	await handle(req("PUT", "/a.json", { token: "s3cret-token", body: '{"ok":1}' }), e);
	for (const body of ['{"games": {"1": [5,', "", "null", "7", "<html>502</html>"]) {
		const r = await handle(req("PUT", "/a.json", { token: "s3cret-token", body }), e);
		assert.equal(r.status, 400, body);
	}
	assert.deepEqual(await (await handle(req("GET", "/a.json"), e)).json(), { ok: 1 });
	const big = await handle(req("PUT", "/a.json", { token: "s3cret-token", body: `"${"x".repeat(MAX_BYTES)}"` }), e);
	assert.equal(big.status, 413);
});

test("names are one flat namespace of lowercase .json files", async () => {
	const e = env();
	for (const path of ["/a/b.json", "/A.json", "/a.txt", "/.json", "/a%2Fb.json"]) {
		assert.equal((await handle(req("GET", path), e)).status, 404, path);
		assert.equal((await handle(req("PUT", path, { token: "s3cret-token", body: "{}" }), e)).status, 404, path);
	}
	assert.equal((await handle(req("GET", "/missing.json"), e)).status, 404);
	assert.equal((await handle(req("DELETE", "/a.json", { token: "s3cret-token" }), e)).status, 405);
	assert.equal((await handle(req("OPTIONS", "/a.json"), e)).status, 204);
	assert.equal((await handle(req("GET", "/"), e)).status, 200);
});

// ── the page side ────────────────────────────────────────────────────────────
const res = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => JSON.parse(body) });
function fetcher(routes) {
	const calls = [];
	const f = async (url) => {
		calls.push(url);
		const r = routes[url];
		if (r === undefined) throw new TypeError("Failed to fetch");
		return res(...r);
	};
	return [f, calls];
}

test("the store's copy wins when the build knows a store", async () => {
	const [f, calls] = fetcher({ "https://d.example/p.json": [200, '{"from":"store"}'], "/data/p.json": [200, '{"from":"site"}'] });
	assert.deepEqual(await fetchData("p.json", { fetchImpl: f, remote: "https://d.example", base: "/" }), { from: "store" });
	assert.deepEqual(calls, ["https://d.example/p.json"]);
});

test("with no store configured only the bundled copy is asked for", async () => {
	const [f, calls] = fetcher({ "/data/p.json": [200, '{"from":"site"}'] });
	assert.deepEqual(await fetchData("p.json", { fetchImpl: f, remote: "", base: "/" }), { from: "site" });
	assert.deepEqual(calls, ["/data/p.json"]);
});

test("every way the store can fail falls back to the bundled copy", async () => {
	for (const store of [undefined, [404, "{}"], [500, "oops"], [200, "<html>not json</html>"]]) {
		const routes = { "/sub/data/p.json": [200, '{"from":"site"}'] };
		if (store) routes["https://d.example/p.json"] = store;
		const [f] = fetcher(routes);
		assert.deepEqual(await fetchData("p.json", { fetchImpl: f, remote: "https://d.example", base: "/sub/" }), { from: "site" });
	}
});

test("both missing is an error the caller can show", async () => {
	const [f] = fetcher({ "/data/p.json": [404, "{}"] });
	await assert.rejects(fetchData("p.json", { fetchImpl: f, remote: "https://d.example", base: "/" }), /HTTP 404/);
});
