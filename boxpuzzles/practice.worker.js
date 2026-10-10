// Runs the practice generator off the page's thread: a search can take a few seconds,
// and the board, the buttons and the sounds must not stall while it does.
import { generate } from "./practice.js";

self.onmessage = (e) => {
	const { exclude } = e.data || {};
	self.postMessage({ box: generate(exclude || []) });
};
