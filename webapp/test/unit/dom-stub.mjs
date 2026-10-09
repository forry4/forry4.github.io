// The few browser globals the shared modules touch, for `node --test`.
// Each test calls `installDom()` to start from a clean window, history and storage.

class MemoryStorage {
	#m = new Map();
	getItem(k) { return this.#m.has(k) ? this.#m.get(k) : null; }
	setItem(k, v) { this.#m.set(k, String(v)); }
	removeItem(k) { this.#m.delete(k); }
	clear() { this.#m.clear(); }
}

export function installDom(pathname = "/") {
	const win = new EventTarget();
	const entries = [{ state: null, path: pathname }];
	win.location = { pathname };
	win.history = {
		pushes: 0,
		replaces: 0,
		get state() { return entries.at(-1).state; },
		pushState(state, _t, path) { this.pushes++; entries.push({ state, path }); win.location.pathname = path; },
		replaceState(state, _t, path) { this.replaces++; entries[entries.length - 1] = { state, path }; win.location.pathname = path; },
	};
	globalThis.window = win;
	globalThis.localStorage = new MemoryStorage();
	globalThis.PopStateEvent ??= class PopStateEvent extends Event {
		constructor(type, init = {}) { super(type); this.state = init.state ?? null; }
	};
	return win;
}

// Replace global fetch with a queue of canned responses; returns the call log.
export function mockFetch(responses) {
	const calls = [];
	globalThis.fetch = async (url, init = {}) => {
		calls.push({ url: String(url), init });
		const next = responses.shift();
		if (!next) throw new Error(`unexpected fetch ${url}`);
		if (next instanceof Error) throw next;
		const { status = 200, body } = next;
		return { ok: status >= 200 && status < 300, status, json: async () => body };
	};
	return calls;
}
