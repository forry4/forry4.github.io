// Regenerate the raster favicons from webapp/public/favicon.svg.
// No ImageMagick/sharp on this box, so render via the Playwright Chromium
// that webapp already installs. Run after editing favicon.svg:
//   node scripts/gen-favicons.mjs   (from webapp/)
import { chromium } from 'playwright';
import { readFileSync, writeFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

const here = dirname(fileURLToPath(import.meta.url));
const pub = resolve(here, '..', 'public');
const svg = readFileSync(resolve(pub, 'favicon.svg'), 'utf8');

const targets = [
  { file: 'favicon-32.png', size: 32 },
  { file: 'apple-touch-icon.png', size: 180 },
];

// Use the system Edge channel locally (the bundled headless shell isn't
// downloaded on this box; mirrors webapp/test/smoke.mjs).
const browser = await chromium.launch({ channel: 'msedge' });
try {
  for (const { file, size } of targets) {
    const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
    // Inline the SVG sized to exactly fill the viewport; transparent page bg
    // so the rounded-corner transparency is preserved.
    const html = `<!doctype html><html><head><style>
      html,body{margin:0;padding:0;background:transparent}
      svg{display:block;width:${size}px;height:${size}px}
    </style></head><body>${svg}</body></html>`;
    await page.setContent(html, { waitUntil: 'networkidle' });
    const buf = await page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
    writeFileSync(resolve(pub, file), buf);
    await page.close();
    console.log(`wrote ${file} (${size}x${size})`);
  }
} finally {
  await browser.close();
}
