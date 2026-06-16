// Shared design system for the Forrest Games site — the single source of truth
// for fonts, color tokens, and primitive controls (buttons, inputs). Imported by
// the shell (games/spender/Spender.jsx) and by any standalone page (e.g. the
// books page) so every screen shares one look. Prepend it to a screen's own CSS:
//   <style>{baseCss + myScreenCss}</style>
// The @import must stay first in the stylesheet, so baseCss always leads.
export const baseCss = `
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Crimson+Pro:ital,wght@0,300;0,400;1,300&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f0e0c;--surface:#1a1814;--surface2:#242018;--surface3:#2c2820;--border:#3a342a;
  --gold:#c9a84c;--gold-light:#e8c96a;--text:#e8dfc8;--text-dim:#8a7d6a;--text-muted:#5a5248;
  --white-gem:#ddd4be;--blue-gem:#6e74ff;--green-gem:#54c23d;--red-gem:#e05555;--black-gem:#6a6a7a;--gold-gem:#f5c842;
  --radius:8px;--radius-lg:14px;
}
html,body{height:100%}
body{background:var(--bg);color:var(--text);font-family:'Crimson Pro',Georgia,serif;min-height:100vh;
  padding-bottom:env(safe-area-inset-bottom,0px);
  padding-left:env(safe-area-inset-left,0px);padding-right:env(safe-area-inset-right,0px)}
/* screens without a sticky nav bar own the top safe area themselves */
.auth-screen,.browser{padding-top:calc(env(safe-area-inset-top,0px) + 32px)}
.app{min-height:100vh;display:flex;flex-direction:column}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:11px 20px;border-radius:var(--radius);border:none;cursor:pointer;font-family:'Cinzel',serif;font-size:.88rem;letter-spacing:.06em;font-weight:600;transition:all .15s;white-space:nowrap}
.btn-gold{background:var(--gold);color:#0f0e0c}.btn-gold:hover{background:var(--gold-light)}
.btn-outline{background:transparent;color:var(--gold);border:1px solid var(--gold)}.btn-outline:hover{background:var(--gold);color:#0f0e0c}
.btn-ghost{background:transparent;color:var(--text-dim);border:1px solid var(--border)}.btn-ghost:hover{border-color:var(--text-dim);color:var(--text)}
.btn-danger{background:transparent;color:var(--red-gem);border:1px solid var(--red-gem)}.btn-danger:hover{background:var(--red-gem);color:#fff}
.btn:disabled{opacity:.35;cursor:not-allowed}
.btn-full{width:100%}
.btn-sm{padding:7px 14px;font-size:.78rem}
.input{width:100%;padding:10px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-family:'Cinzel',serif;font-size:1rem;letter-spacing:.1em;outline:none}
.input:focus{border-color:var(--gold)}
`;
