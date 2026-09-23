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
	bullet: svg(<><circle cx="5.5" cy="7" r="1" fill="currentColor" /><circle cx="5.5" cy="12" r="1" fill="currentColor" /><circle cx="5.5" cy="17" r="1" fill="currentColor" /><path d="M9.5 7h10M9.5 12h10M9.5 17h10" /></>),
	ordered: svg(<><path d="M4.5 5.5h1.3v4M4.3 9.5h3M4.4 14.3c.3-.6.9-.9 1.5-.8.9.1 1.3 1 .8 1.8L4.4 18.3h2.9" /><path d="M10.5 7h9M10.5 12h9M10.5 17h9" /></>),
	check: svg(<><rect x="3.8" y="5" width="6" height="6" rx="1.2" /><path d="m5.3 8 1.3 1.3 2.2-2.6M13 8h7M3.8 13.5h6v6h-6ZM13 16.5h7" /></>),
	quote: svg(<><path d="M5.5 6.5v11M9.5 8h9M9.5 12h9M9.5 16h6" /></>),
	rule: svg(<path d="M4 12h16" />),
	link: svg(<><path d="M10.2 13.8a3.6 3.6 0 0 0 5.1 0l2.9-2.9a3.6 3.6 0 0 0-5.1-5.1l-1 1" /><path d="M13.8 10.2a3.6 3.6 0 0 0-5.1 0l-2.9 2.9a3.6 3.6 0 0 0 5.1 5.1l1-1" /></>),
	image: svg(<><rect x="3.8" y="5" width="16.4" height="14" rx="1.8" /><circle cx="9" cy="10" r="1.6" /><path d="m4.5 17.5 4.8-4.4 3.4 3 2.6-2.3 4.4 3.9" /></>),
	undo: svg(<><path d="M8.5 8.5H15a4.5 4.5 0 0 1 0 9h-4" /><path d="M11.5 5.2 8.2 8.5l3.3 3.3" /></>),
	redo: svg(<><path d="M15.5 8.5H9a4.5 4.5 0 0 0 0 9h4" /><path d="m12.5 5.2 3.3 3.3-3.3 3.3" /></>),
	expand: svg(<path d="M14 4.5h5.5V10M10 19.5H4.5V14M19.5 4.5l-6 6M4.5 19.5l6-6" />),
	close: svg(<path d="m6.5 6.5 11 11M17.5 6.5l-11 11" />),
};
