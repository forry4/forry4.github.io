// Find-in-note: every match of a query in the open note, drawn as ProseMirror
// decorations (the document itself is never touched, so finding cannot mark a note
// as edited), with one "current" match the find bar steps through.
//
// Matching runs per TEXT BLOCK over the concatenated text of its runs, not per text
// node: in the document a bolded word is its own node, so "reads 3:15" would never
// be found node by node. Image captions are searched too — a caption is where a
// screenshot's words live.
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

export const findKey = new PluginKey("ntFind");

export function findMatches(doc, query) {
	if (!query) return [];
	const out = [];
	doc.descendants((node, pos) => {
		if (node.isTextblock) {
			let text = "";
			const map = [];   // text index -> document position
			node.forEach((child, offset) => {
				const start = pos + 1 + offset;
				if (child.isText) {
					for (let i = 0; i < child.text.length; i++) map.push(start + i);
					text += child.text;
				} else {   // an inline atom (a hard break) — a separator nothing can match
					map.push(start);
					text += "\u0000";
				}
			});
			// toLowerCase is length-preserving for almost everything; where it is not,
			// search that block case-sensitively rather than map offsets wrongly.
			let hay = text.toLowerCase(), needle = query.toLowerCase();
			if (hay.length !== text.length || needle.length !== query.length) { hay = text; needle = query; }
			for (let i = hay.indexOf(needle); i !== -1; i = hay.indexOf(needle, i + needle.length)) {
				out.push({ from: map[i], to: map[i + needle.length - 1] + 1 });
			}
			return false;
		}
		if (node.type.name === "noteImage") {
			if ((node.attrs.caption || "").toLowerCase().includes(query.toLowerCase())) {
				out.push({ from: pos, to: pos + node.nodeSize, node: true });
			}
			return false;
		}
		return true;
	});
	return out;
}

function decorate(doc, matches, index) {
	return DecorationSet.create(doc, matches.map((m, i) => {
		const cls = i === index ? "nt-find nt-find-cur" : "nt-find";
		return m.node ? Decoration.node(m.from, m.to, { class: cls.replace(/nt-find/g, "nt-find-node") })
			: Decoration.inline(m.from, m.to, { class: cls });
	}));
}

export const FindInNote = Extension.create({
	name: "findInNote",
	addProseMirrorPlugins() {
		return [new Plugin({
			key: findKey,
			state: {
				init: () => ({ query: "", index: 0, matches: [], deco: DecorationSet.empty }),
				apply(tr, prev, _old, state) {
					const meta = tr.getMeta(findKey);
					if (!meta && !tr.docChanged) return prev;
					const query = meta && meta.query !== undefined ? meta.query : prev.query;
					const matches = meta?.query !== undefined || tr.docChanged ? findMatches(state.doc, query) : prev.matches;
					let index = meta && meta.index !== undefined ? meta.index : (meta?.query !== undefined ? 0 : prev.index);
					index = matches.length ? Math.min(Math.max(0, index), matches.length - 1) : 0;
					return { query, index, matches, deco: decorate(state.doc, matches, index) };
				},
			},
			props: { decorations: (state) => findKey.getState(state).deco },
		})];
	},
});
