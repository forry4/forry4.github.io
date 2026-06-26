"""Assemble the self-contained browser-N userscript.

Inlines the wasm-pack (--target no-modules) glue + the variant-N wasm (base64) into
browser_n.template.user.js, producing wwsd_browser_n.user.js — a single file the user installs in
Tampermonkey. No hosting / CORS / fetch: the WASM is embedded. Re-run after rebuilding the wasm
(wasm-pack build --release --target no-modules --out-dir pkg-nomod in the spender-core crate).
"""
from __future__ import annotations
import base64
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
PKG = pathlib.Path(r"C:/Users/Forrest/forrestm_projects-wwsd-wasm/spender-core/pkg-nomod")

glue = (PKG / "spender_core.js").read_text(encoding="utf-8")
wasm_b64 = base64.b64encode((PKG / "spender_core_bg.wasm").read_bytes()).decode("ascii")
tpl = (HERE / "browser_n.template.user.js").read_text(encoding="utf-8")

if "//__GLUE__" not in tpl or "__WASM_B64__" not in tpl:
    raise SystemExit("template missing //__GLUE__ or __WASM_B64__ placeholder")

out = tpl.replace("//__GLUE__", glue).replace('"__WASM_B64__"', '"' + wasm_b64 + '"')
dst = HERE / "wwsd_browser_n.user.js"
dst.write_text(out, encoding="utf-8")
print(f"wrote {dst}  ({len(out):,} bytes; wasm {len(wasm_b64):,} b64 chars)")
