// The data store's front door — serves the site's GENERATED data files out of a Workers
// KV namespace, and takes a new copy from the job that made it.
//
// WHY THIS EXISTS. Every refreshed data file (prices twice a day, LoL, anime, ...) used
// to reach the site as a COMMIT to main followed by a full Pages build, because Pages
// can only serve what was in the build artifact. That put two commits a day of price
// data in `git log`, ran the whole site build and render gate for a 235KB JSON, and
// raced every human push. Here a refresh is one PUT; nothing is committed, built or
// deployed. The page reads this first and falls back to the copy bundled with the
// site (shared/dataUrl.js), so with this Worker down — or never deployed — the site
// behaves exactly as it did before.
//
//   GET  /<name>.json   public, CORS-open (it is the same public data the site ships),
//                       ETag + a short max-age so a refresh shows within minutes
//   PUT  /<name>.json   Authorization: Bearer <PUBLISH_TOKEN>; body must be JSON
//
// KV AND NOT R2, deliberately: R2 needs a billing subscription on the account even to
// stay inside its free tier, and KV does not — on the Workers Free plan it has hard
// daily limits (100k reads, 1k writes, 1GB) and simply refuses past them, so this can
// never produce a charge. A value may be 25MB; the largest file is 2.6MB. KV is
// eventually consistent (a write can take up to a minute to be read everywhere), which
// is why the publishing job retries its read-back.
//
// The name is the whole key: one flat namespace of lowercase `*.json` files, the same
// filenames that live in webapp/public/data/. `handle` is exported so the unit test
// (webapp/test/unit/dataWorker.test.mjs) drives it against a stand-in bucket.

const NAME = /^[a-z0-9][a-z0-9-]{0,63}\.json$/;
export const MAX_BYTES = 8 * 1024 * 1024;     // the largest file today is 2.6MB
const MAX_AGE = 300;

const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
	"Access-Control-Allow-Headers": "If-None-Match",
	"Access-Control-Expose-Headers": "ETag, Last-Modified",
	"Access-Control-Max-Age": "86400",
};

const json = (status, body) => new Response(JSON.stringify(body), {
	status, headers: { "Content-Type": "application/json", ...CORS },
});

// Constant-time, so the token cannot be recovered a byte at a time from response timing.
function sameToken(a, b) {
	if (typeof a !== "string" || typeof b !== "string" || !b) return false;
	const x = new TextEncoder().encode(a), y = new TextEncoder().encode(b);
	let diff = x.length ^ y.length;
	for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i % y.length];
	return diff === 0;
}

export async function handle(request, env) {
	const { pathname } = new URL(request.url);
	const name = pathname.slice(1);
	const method = request.method;

	if (method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
	if (pathname === "/") return json(200, { ok: true, service: "forrestgames-data" });
	if (!NAME.test(name)) return json(404, { ok: false, message: "no such file" });

	if (method === "GET" || method === "HEAD") {
		const { value, metadata } = await env.DATA.getWithMetadata(name, "arrayBuffer");
		if (value === null) return json(404, { ok: false, message: "no such file" });
		const etag = (metadata && metadata.etag) || null;
		const headers = {
			"Content-Type": "application/json",
			"Cache-Control": `public, max-age=${MAX_AGE}`,
			...(etag ? { ETag: etag } : {}),
			...(metadata && metadata.uploaded ? { "Last-Modified": new Date(metadata.uploaded).toUTCString() } : {}),
			...CORS,
		};
		const seen = request.headers.get("If-None-Match");
		if (etag && seen && seen.split(",").map((s) => s.trim()).includes(etag)) {
			return new Response(null, { status: 304, headers });
		}
		return new Response(method === "HEAD" ? null : value, { status: 200, headers });
	}

	if (method === "PUT") {
		const auth = request.headers.get("Authorization") || "";
		if (!sameToken(auth.replace(/^Bearer\s+/i, ""), env.PUBLISH_TOKEN)) {
			return json(401, { ok: false, message: "bad token" });
		}
		const declared = Number(request.headers.get("Content-Length") || 0);
		if (declared > MAX_BYTES) return json(413, { ok: false, message: "too large" });
		const body = await request.arrayBuffer();
		if (body.byteLength > MAX_BYTES) return json(413, { ok: false, message: "too large" });
		// A half-written or truncated upload must never replace a good file: the page
		// would parse-fail and fall back, and the next job would build on garbage.
		try {
			const parsed = JSON.parse(new TextDecoder().decode(body));
			if (parsed === null || typeof parsed !== "object") throw new Error("not an object");
		} catch {
			return json(400, { ok: false, message: "body is not a JSON object or array" });
		}
		const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", body));
		const etag = `"${[...digest.slice(0, 16)].map((b) => b.toString(16).padStart(2, "0")).join("")}"`;
		await env.DATA.put(name, body, { metadata: { etag, uploaded: Date.now() } });
		return json(200, { ok: true, name, bytes: body.byteLength, etag });
	}

	return json(405, { ok: false, message: "method not allowed" });
}

export default { fetch: handle };
