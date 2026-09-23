// Notes HTTP client. The session token travels in the Authorization header, never
// the URL — which is also why images cannot be plain <img src> links (see images.js).
const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
export const HTTP_BASE = WS_BASE.replace(/^ws/, "http").replace(/\/ws$/, "");

// A failed request carries `status` (undefined = never reached the server, i.e.
// offline or a cold Render box) and the parsed body as `data`.
export class ApiError extends Error {
	constructor(message, status, data) {
		super(message);
		this.status = status;
		this.data = data;
	}
}

export function makeApi(token) {
	const auth = token ? { Authorization: `Bearer ${token}` } : {};

	async function req(method, path, body, { keepalive = false } = {}) {
		let res;
		try {
			res = await fetch(HTTP_BASE + path, {
				method,
				keepalive,
				headers: body === undefined ? auth : { ...auth, "Content-Type": "application/json" },
				body: body === undefined ? undefined : JSON.stringify(body),
			});
		} catch (e) {
			throw new ApiError("offline", undefined, null);
		}
		let data = null;
		try { data = await res.json(); } catch { /* empty or non-JSON body */ }
		if (!res.ok) throw new ApiError(data?.detail || `HTTP ${res.status}`, res.status, data);
		return data;
	}

	return {
		tree: () => req("GET", "/notes/tree"),
		getNote: (id) => req("GET", `/notes/note/${id}`).then((d) => d.note),
		createNote: (folderId, title = "") =>
			req("POST", "/notes/note", { folder_id: folderId ?? null, title }).then((d) => d.note),
		// keepalive lets the last save of a closing tab still land (bodies < 64KB).
		saveNote: (id, body, opts) => req("PUT", `/notes/note/${id}`, body, opts).then((d) => d.note),
		noteMeta: (id, fields) => req("POST", `/notes/note/${id}/meta`, fields).then((d) => d.note),
		deleteNote: (id) => req("DELETE", `/notes/note/${id}`),
		emptyTrash: () => req("POST", "/notes/trash/empty"),
		createFolder: (parentId, name) =>
			req("POST", "/notes/folder", { parent_id: parentId ?? null, name }).then((d) => d.folder),
		updateFolder: (id, fields) => req("POST", `/notes/folder/${id}`, fields).then((d) => d.folder),
		deleteFolder: (id) => req("DELETE", `/notes/folder/${id}`),
		uploadImage: (body) => req("POST", "/notes/image", body).then((d) => d.image),
		imageBlob: async (id) => {
			let res;
			try { res = await fetch(`${HTTP_BASE}/notes/image/${id}`, { headers: auth }); }
			catch { throw new ApiError("offline", undefined, null); }
			if (!res.ok) throw new ApiError(`HTTP ${res.status}`, res.status, null);
			return res.blob();
		},
	};
}
