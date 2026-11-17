
// CSS lives in the sibling .css file(s) imported below, NOT in a JS template
// literal. `?inline` hands us the stylesheet as a STRING, so it is still injected
// by this component's own <style> tag only while it is mounted — behaviour is
// unchanged. What goes away is the footgun: a single stray backtick inside a css
// template literal silently reparsed the rest of the file as a tagged template and
// blanked the whole page. A .css file cannot do that, and editors lint it properly.
import _baseCssText from "./theme.base-css.css?inline";
import _gameKitText from "./theme.game-kit.css?inline";
// Shared design system for the Forrest Games site — the single source of truth
// for fonts, color tokens, and primitive controls (buttons, inputs). Imported by
// the shell (games/spender/Spender.jsx) and by any standalone page (e.g. the
// books page) so every screen shares one look. Prepend it to a screen's own CSS:
//   <style>{baseCss + myScreenCss}</style>
// The @import must stay first in the stylesheet, so baseCss always leads.
export const baseCss = _baseCssText + _gameKitText;
// The game kit on its own, for a screen that mounts bare and carries its own palette
// copy instead of baseCss (Castles of Crimson). See theme.game-kit.css.
export const gameKitCss = _gameKitText;
