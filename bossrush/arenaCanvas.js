// Keep arena coordinates in CSS pixels and use the display's original pixel ratio.
export function arenaCanvas(canvas) {
	const ctx = canvas.getContext("2d", { alpha: false });
	const viewport = canvas.ownerDocument.defaultView;
	const touch = viewport.matchMedia("(any-pointer: coarse)");
	const head = canvas.closest(".br-run")?.querySelector(".br-run-head");
	const controls = canvas.parentElement?.querySelector(".br-touch");
	const arena = { ctx, width: 0, height: 0, px: 1, bossBarInset: 0, autoFireInset: 0, revision: 0, observe };

	function resize() {
		const ratio = Math.min(viewport.devicePixelRatio || 1, 2);
		const width = canvas.clientWidth, height = canvas.clientHeight;
		const w = Math.max(1, Math.round(width * ratio)), h = Math.max(1, Math.round(height * ratio));
		if (canvas.width !== w) canvas.width = w;
		if (canvas.height !== h) canvas.height = h;
		ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
		arena.width = width;
		arena.height = height;
		// Keep a useful horizontal field of view on a portrait phone.
		arena.px = touch.matches ? Math.max(1, Math.min(width / 14, height / 12)) : Math.max(1, width / 24, height / 10);
		arena.bossBarInset = touch.matches ? head?.offsetHeight || 0 : 0;
		arena.autoFireInset = touch.matches ? controls?.offsetHeight || 0 : 0;
		arena.revision++;
	}

	function observe(onResize) {
		const update = () => { resize(); onResize?.(); };
		const observer = new viewport.ResizeObserver(update);
		observer.observe(canvas);
		if (head) observer.observe(head);
		if (controls) observer.observe(controls);
		viewport.addEventListener("resize", update);
		update();
		return () => {
			observer.disconnect();
			viewport.removeEventListener("resize", update);
		};
	}

	return arena;
}
