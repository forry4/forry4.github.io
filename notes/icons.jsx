// Line-art glyphs on the site's 24x24 drawing grid — SVG, never emoji, for the reason
// the home menu's extras row was rebuilt: an emoji arrives in a different typeface,
// weight and often colour scheme on every OS.
const svg = (children) => (
	<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6"
		strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">{children}</svg>
);

export const I = {
	caret: svg(<path d="M9.5 6.5 15 12l-5.5 5.5" />),
	folder: svg(<path d="M3.5 7.2c0-1 .8-1.7 1.7-1.7h4l1.8 2h7.8c.9 0 1.7.8 1.7 1.7v8.1c0 1-.8 1.7-1.7 1.7H5.2c-.9 0-1.7-.8-1.7-1.7Z" />),
	note: svg(<><path d="M6.5 3.5h7.8l3.7 3.7v13.3H6.5Z" /><path d="M14 3.7v3.8h3.8M9.2 12h5.6M9.2 15.4h5.6" /></>),
	pin: svg(<><path d="M9 4h6l-1 5.5 3 3H7l3-3Z" /><path d="M12 12.5V20" /></>),
	dots: svg(<><circle cx="6" cy="12" r=".9" fill="currentColor" /><circle cx="12" cy="12" r=".9" fill="currentColor" /><circle cx="18" cy="12" r=".9" fill="currentColor" /></>),
	trash: svg(<><path d="M4.5 7h15M9.5 7V4.8h5V7M6.5 7l.9 12.5h9.2L17.5 7" /></>),
	plus: svg(<path d="M12 5.5v13M5.5 12h13" />),
	back: svg(<path d="M14.5 6.5 9 12l5.5 5.5" />),
	clock: svg(<><circle cx="12" cy="12" r="8" /><path d="M12 7.8V12l2.8 2" /></>),
	// toolbar
	// Solid dots and short lines: at 18px, a list icon has to read as DOTS first. The
	// old 1px-radius dots vanished, leaving eight near-identical stacks of lines in a
	// row (lists, quote, align, indent) — and Indent got clicked for "bullet list".
	bullet: svg(<><circle cx="5.2" cy="6.5" r="2.3" fill="currentColor" stroke="none" /><circle cx="5.2" cy="12" r="2.3" fill="currentColor" stroke="none" /><circle cx="5.2" cy="17.5" r="2.3" fill="currentColor" stroke="none" /><path d="M10.5 6.5h9M10.5 12h9M10.5 17.5h9" /></>),
	ordered: svg(<><text x="1.6" y="11" fontSize="10.5" fontWeight="700" fill="currentColor" stroke="none" fontFamily="Arial,Helvetica,sans-serif">1</text><text x="1.3" y="21.5" fontSize="10.5" fontWeight="700" fill="currentColor" stroke="none" fontFamily="Arial,Helvetica,sans-serif">2</text><path d="M10.5 7.5h9M10.5 17.5h9" /></>),
	check: svg(<><rect x="3.8" y="5" width="6" height="6" rx="1.2" /><path d="m5.3 8 1.3 1.3 2.2-2.6M13 8h7M3.8 13.5h6v6h-6ZM13 16.5h7" /></>),
	// Quotation marks, not a bar + lines (which read as one more list/indent icon).
	quote: svg(<><path d="M10 7.5c-2.6.6-4.2 2.6-4.2 5.4v3.6h4v-4H7.6c.1-1.5 1.1-2.6 2.6-3Z" fill="currentColor" stroke="none" /><path d="M18.2 7.5c-2.6.6-4.2 2.6-4.2 5.4v3.6h4v-4h-2.2c.1-1.5 1.1-2.6 2.6-3Z" fill="currentColor" stroke="none" /></>),
	rule: svg(<path d="M4 12h16" />),
	// A SOLID arrowhead: the 1.6px chevron these used to have disappeared at 18px.
	indent: svg(<><path d="M4.5 5.5h15M11.5 10h8M11.5 14h8M4.5 18.5h15" /><path d="M4 8.8 8.6 12 4 15.2Z" fill="currentColor" /></>),
	outdent: svg(<><path d="M4.5 5.5h15M11.5 10h8M11.5 14h8M4.5 18.5h15" /><path d="M8.6 8.8 4 12l4.6 3.2Z" fill="currentColor" /></>),
	alignLeft: svg(<path d="M4.5 6h15M4.5 10h9M4.5 14h15M4.5 18h9" />),
	alignCenter: svg(<path d="M4.5 6h15M7.5 10h9M4.5 14h15M7.5 18h9" />),
	alignRight: svg(<path d="M4.5 6h15M10.5 10h9M4.5 14h15M10.5 18h9" />),
	link: svg(<><path d="M10.2 13.8a3.6 3.6 0 0 0 5.1 0l2.9-2.9a3.6 3.6 0 0 0-5.1-5.1l-1 1" /><path d="M13.8 10.2a3.6 3.6 0 0 0-5.1 0l-2.9 2.9a3.6 3.6 0 0 0 5.1 5.1l1-1" /></>),
	image: svg(<><rect x="3.8" y="5" width="16.4" height="14" rx="1.8" /><circle cx="9" cy="10" r="1.6" /><path d="m4.5 17.5 4.8-4.4 3.4 3 2.6-2.3 4.4 3.9" /></>),
	undo: svg(<><path d="M8.5 8.5H15a4.5 4.5 0 0 1 0 9h-4" /><path d="M11.5 5.2 8.2 8.5l3.3 3.3" /></>),
	redo: svg(<><path d="M15.5 8.5H9a4.5 4.5 0 0 0 0 9h4" /><path d="m12.5 5.2 3.3 3.3-3.3 3.3" /></>),
	expand: svg(<path d="M14 4.5h5.5V10M10 19.5H4.5V14M19.5 4.5l-6 6M4.5 19.5l6-6" />),
	search: svg(<><circle cx="10.5" cy="10.5" r="5.5" /><path d="m14.6 14.6 4.9 4.9" /></>),
	up: svg(<path d="M6.5 14.5 12 9l5.5 5.5" />),
	down: svg(<path d="M6.5 9.5 12 15l5.5-5.5" />),
	close: svg(<path d="m6.5 6.5 11 11M17.5 6.5l-11 11" />),
};
