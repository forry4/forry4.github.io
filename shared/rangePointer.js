// Pointer handling for an <input type=range> dial, shared by the BGG and Steam filter
// pages. Spread the result onto the input: {...rangePointer(onChange)}.
//
// A FINGER IS NOT A MOUSE. The native thumb is ~16px of a ~336px track, and WebKit starts a
// drag only when the touch lands ON it — Chrome jumps the thumb to wherever you tap, iOS does
// not, so on a phone these dials were a 16px target that mostly ignored you. With `touch-action`
// unset the page scroller could also claim the gesture from any drag a few degrees off true. So
// the control handles its own pointer: press anywhere along the row to set the value, capture the
// pointer, and follow it. The CSS gives horizontal drags to the slider and leaves vertical ones
// to the page. The <input type=range> stays for keyboard and a11y.
export function rangePointer(onChange) {
	const set = (e) => {
		const el = e.currentTarget;
		const r = el.getBoundingClientRect();
		const min = Number(el.min), max = Number(el.max), step = Number(el.step) || 1;
		// the thumb's CENTRE travels between half-a-thumb in from each end, not the full width
		const pad = Math.min(11, r.width / 2);
		const t = Math.max(0, Math.min(1, (e.clientX - r.left - pad) / Math.max(1, r.width - pad * 2)));
		const v = Math.min(max, Math.max(min, Math.round((min + t * (max - min)) / step) * step));
		onChange(Number(v.toFixed(6)));   // 0.1 steps land on 1.7000000000000002 otherwise
	};
	// The press is tracked on the element itself rather than inferred from hasPointerCapture():
	// capture is an ENHANCEMENT that keeps a finger straying off the row still dragging, and it
	// can simply fail to take. Losing the drag whenever it does would be the same bug again.
	const end = (e) => {
		delete e.currentTarget.dataset.drag;
		try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* never captured */ }
	};
	return {
		onPointerDown: (e) => {
			if (e.button > 0) return;
			e.preventDefault();          // ours, or the native thumb drag fights it
			e.currentTarget.focus();     // preventDefault ate the focus, and keyboard must still work
			e.currentTarget.dataset.drag = "1";
			try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* enhancement only */ }
			set(e);
		},
		// `buttons` is 0 once a press has ended, so a pointerup we never saw (capture released
		// off-element) cannot leave the dial following an idle cursor.
		onPointerMove: (e) => { if (e.currentTarget.dataset.drag && e.buttons !== 0) set(e); },
		onPointerUp: end,
		onPointerCancel: end,          // the page scroller took the gesture
	};
}
