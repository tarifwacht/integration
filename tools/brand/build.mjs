// Builds all Tarifwacht brand assets (SVG masters + PNG exports) straight into the repo.
// Taken over from Einspeisewacht; tokens, mark and texts changed.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import opentype from 'opentype.js';
import sharp from 'sharp';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../..');
const DEST = {
  ha: path.join(ROOT, 'custom_components/tarifwacht/brand'),
  brand: path.join(ROOT, 'assets/brand'),
  github: path.join(ROOT, 'assets/github'),
};

// ---------- Brand tokens ----------
const C = {
  tile: '#96497D',      // RAL 4006 Verkehrspurpur, from its CIE L*a*b* (D65) values
  amber: '#F5A623',     // Wachlicht (shared with Streckenwacht, Eilwacht, Einspeisewacht)
  paper: '#FBF7EE',     // Balken (warmes Off-White)
  cream: '#FAF7F2',     // heller Hintergrund
  night: '#14181D',     // dunkler Hintergrund
  grey: '#6B6357',      // Tagline hell
  greyDark: '#B9B2A6',  // Tagline dunkel
};
const WORDMARK = 'Tarifwacht';
const TAGLINE = 'Jeder Tarif. Jede Viertelstunde.';
const SUBLINE = 'Home-Assistant-Integration  ·  Festpreis  ·  dynamischer Stromtarif  ·  Viertelstundenpreise';

const fontDir = path.join(HERE, 'node_modules/@fontsource/space-grotesk/files');
const fontBold = opentype.parse(bufToAB(fs.readFileSync(path.join(fontDir, 'space-grotesk-latin-700-normal.woff'))));
const fontMed = opentype.parse(bufToAB(fs.readFileSync(path.join(fontDir, 'space-grotesk-latin-500-normal.woff'))));
function bufToAB(b) { return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); }

// ---------- Mark (viewBox 0 0 100 100) ----------
// Four quarter hours (dynamic prices) against a line (the fixed price): above
// the line a bar is faded (dearer), the Wachlicht marks the one below it.
function mark({ bar = C.paper, accent = C.amber, halo = true } = {}) {
  return `
    <rect x="6" y="14" width="16" height="19" rx="3" fill="${bar}" opacity="0.45"/>
    <rect x="6" y="40" width="16" height="52" rx="3" fill="${bar}"/>
    <rect x="29" y="22" width="16" height="11" rx="3" fill="${bar}" opacity="0.45"/>
    <rect x="29" y="40" width="16" height="52" rx="3" fill="${bar}"/>
    <rect x="52" y="72" width="16" height="20" rx="3" fill="${bar}"/>
    <rect x="75" y="18" width="16" height="15" rx="3" fill="${bar}" opacity="0.45"/>
    <rect x="75" y="40" width="16" height="52" rx="3" fill="${bar}"/>
    <rect x="2" y="35" width="96" height="3" fill="${bar}"/>
    ${halo ? `<circle cx="60" cy="56" r="13" fill="none" stroke="${accent}" stroke-width="2.5" opacity="0.35"/>` : ''}
    <circle cx="60" cy="56" r="7.5" fill="${accent}"/>`;
}
// Simplified mark for tiny sizes (<= 32 px): three wider bars, thicker line,
// bigger dot, no faded parts or halo
function markMini({ bar = C.paper, accent = C.amber } = {}) {
  return `
    <rect x="8" y="42" width="24" height="50" rx="4" fill="${bar}"/>
    <rect x="38" y="74" width="24" height="18" rx="4" fill="${bar}"/>
    <rect x="68" y="42" width="24" height="50" rx="4" fill="${bar}"/>
    <rect x="2" y="30" width="96" height="6" fill="${bar}"/>
    <circle cx="50" cy="56" r="10" fill="${accent}"/>`;
}

// Tile: rounded square, mark at 68.75 % (same proportions as Streckenwacht)
function tileGroup(size, { mini = false, radiusRatio = 72 / 320, fullBleed = false } = {}) {
  const r = fullBleed ? 0 : size * radiusRatio;
  const inner = mini ? size * 0.86 : size * 0.6875;
  const off = (size - inner) / 2;
  const s = inner / 100;
  return `<rect width="${size}" height="${size}" rx="${r}" fill="${C.tile}"/>
    <g transform="translate(${off},${off}) scale(${s})">${mini ? markMini() : mark()}</g>`;
}

function svg(w, h, body, { vbW = w, vbH = h, bg } = {}) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${vbW} ${vbH}">${bg ? `<rect width="${vbW}" height="${vbH}" fill="${bg}"/>` : ''}${body}</svg>`;
}

// ---------- Text as outlined paths ----------
function serialize(cmds) {
  const n = (v) => { if (!Number.isFinite(v)) throw new Error('bad coord ' + v); return (+v.toFixed(3)).toString(); };
  return cmds.map((c) => {
    switch (c.type) {
      case 'M': case 'L': return `${c.type}${n(c.x)} ${n(c.y)}`;
      case 'Q': return `Q${n(c.x1)} ${n(c.y1)} ${n(c.x)} ${n(c.y)}`;
      case 'C': return `C${n(c.x1)} ${n(c.y1)} ${n(c.x2)} ${n(c.y2)} ${n(c.x)} ${n(c.y)}`;
      case 'Z': return 'Z';
      default: throw new Error('unknown cmd ' + c.type);
    }
  }).join('');
}
// Manual glyph-by-glyph layout (opentype.js 2.0 font.getPath() emits NaN for this font)
function textPath(font, text, fontSize) {
  const scale = fontSize / font.unitsPerEm;
  const parts = [];
  const bb = { x1: Infinity, y1: Infinity, x2: -Infinity, y2: -Infinity };
  let x = 0, prev = null;
  for (const ch of text) {
    const g = font.charToGlyph(ch);
    if (prev) { const k = font.getKerningValue(prev, g); if (Number.isFinite(k)) x += k * scale; }
    const gp = g.getPath(x, 0, fontSize);
    const gd = serialize(gp.commands); // own serializer: opentype.js' toPathData() emits NaN for some coordinates
    if (gd) {
      parts.push(gd);
      const b = gp.getBoundingBox();
      bb.x1 = Math.min(bb.x1, b.x1); bb.y1 = Math.min(bb.y1, b.y1);
      bb.x2 = Math.max(bb.x2, b.x2); bb.y2 = Math.max(bb.y2, b.y2);
    }
    x += g.advanceWidth * scale;
    prev = g;
  }
  const d = parts.join(' ');
  if (d.includes('NaN')) throw new Error('NaN in path for ' + text);
  return { d, bb, adv: x };
}
function placedText(font, text, fontSize, x, baselineY, fill) {
  const { d } = textPath(font, text, fontSize);
  return `<path transform="translate(${x},${baselineY})" d="${d}" fill="${fill}"/>`;
}

// ---------- Compositions ----------
// Horizontal logo (tile + wordmark), trimmed, for HA logo.png & general use
function logoSVG(textColor, outH) {
  const T = 140, gap = 36, fs = 64;
  const w = textPath(fontBold, WORDMARK, fs);
  const textH = w.bb.y2 - w.bb.y1;
  const baseline = T / 2 + textH / 2 - w.bb.y2; // center glyph bbox on tile center
  const textX = T + gap - w.bb.x1;
  const W = Math.ceil(T + gap + (w.bb.x2 - w.bb.x1) + 2);
  const body = `<g>${tileGroup(T, { radiusRatio: 31 / 140 })}</g>` + placedText(fontBold, WORDMARK, fs, textX, baseline, textColor);
  const scale = outH / T;
  return svg(Math.round(W * scale), outH, body, { vbW: W, vbH: T });
}

// README header banner 960x220 (tile + wordmark + tagline)
function headerSVG({ bg, text, tag }, scale = 1) {
  const W = 960, H = 220, T = 140, pad = 48, gap = 36;
  const wm = textPath(fontBold, WORDMARK, 48);
  const tg = textPath(fontMed, TAGLINE, 20);
  const wmH = -wm.bb.y1; // cap height above baseline
  const tgH = -tg.bb.y1;
  const lineGap = 16;
  const blockH = wmH + lineGap + tgH + tg.bb.y2; // include descenders of tagline
  const top = (H - blockH) / 2;
  const x = pad + T + gap;
  const body = `<g transform="translate(${pad},${(H - T) / 2})">${tileGroup(T, { radiusRatio: 31 / 140 })}</g>`
    + placedText(fontBold, WORDMARK, 48, x - wm.bb.x1, top + wmH, text)
    + placedText(fontMed, TAGLINE, 20, x - tg.bb.x1, top + wmH + lineGap + tgH, tag);
  return svg(W * scale, H * scale, body, { vbW: W, vbH: H, bg });
}

// GitHub social preview 1280x640
function socialSVG() {
  const W = 1280, H = 640, T = 220, gap = 52;
  const wm = textPath(fontBold, WORDMARK, 92);
  const tg = textPath(fontMed, TAGLINE, 36);
  const sub = textPath(fontMed, SUBLINE, 24);
  const blockW = T + gap + Math.max(wm.bb.x2 - wm.bb.x1, tg.bb.x2 - tg.bb.x1);
  const x0 = (W - blockW) / 2;
  const tileY = 170;
  const wmBase = tileY + 108;
  const tgBase = wmBase + 62;
  const subW = sub.bb.x2 - sub.bb.x1;
  const body = `<g transform="translate(${x0},${tileY})">${tileGroup(T)}</g>`
    + placedText(fontBold, WORDMARK, 92, x0 + T + gap - wm.bb.x1, wmBase, C.tile)
    + placedText(fontMed, TAGLINE, 36, x0 + T + gap - tg.bb.x1, tgBase, C.grey)
    + `<rect x="${(W - subW) / 2 - 24}" y="496" width="${subW + 48}" height="52" rx="26" fill="${C.tile}" opacity="0.08"/>`
    + placedText(fontMed, SUBLINE, 24, (W - subW) / 2 - sub.bb.x1, 530, C.tile);
  return svg(W, H, body, { bg: C.cream });
}

// ---------- Writers ----------
function write(file, content) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content);
}
async function png(svgStr, file) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  await sharp(Buffer.from(svgStr), { density: 72 }).png({ compressionLevel: 9, progressive: true }).toFile(file);
}
// ICO with embedded PNG images (supported since Windows Vista and by all browsers)
function ico(pngFiles, file) {
  const images = pngFiles.map((f) => fs.readFileSync(f));
  const header = Buffer.alloc(6 + 16 * images.length);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2); // type: icon
  header.writeUInt16LE(images.length, 4);
  let offset = header.length;
  images.forEach((img, i) => {
    const size = img.readUInt32BE(16); // PNG IHDR width
    const e = 6 + 16 * i;
    header.writeUInt8(size >= 256 ? 0 : size, e);
    header.writeUInt8(size >= 256 ? 0 : size, e + 1);
    header.writeUInt16LE(1, e + 4); // colour planes
    header.writeUInt16LE(32, e + 6); // bits per pixel
    header.writeUInt32LE(img.length, e + 8);
    header.writeUInt32LE(offset, e + 12);
    offset += img.length;
  });
  write(file, Buffer.concat([header, ...images]));
}

// Size-parametrised icon SVGs
const iconAt = (n, opts = {}) => svg(n, n, tileGroup(100, opts), { vbW: 100, vbH: 100 });
const markTrim = { x: 1, y: 13, w: 98, h: 80 };
const markSVG = (bar, h = 890) => svg(Math.round(h * markTrim.w / markTrim.h), h,
  `<g transform="translate(${-markTrim.x},${-markTrim.y})">${mark({ bar })}</g>`, { vbW: markTrim.w, vbH: markTrim.h });

// ---------- Build ----------
for (const dir of Object.values(DEST)) fs.rmSync(dir, { recursive: true, force: true });
const B = (rel) => path.join(DEST.brand, rel);

// SVG masters
write(B('svg/icon.svg'), iconAt(512));
write(B('svg/icon-mini.svg'), iconAt(512, { mini: true }));
write(B('svg/icon-square-fullbleed.svg'), iconAt(512, { fullBleed: true }));
write(B('svg/mark-on-light.svg'), markSVG(C.tile));
write(B('svg/mark-on-dark.svg'), markSVG(C.paper));
write(B('svg/logo-on-light.svg'), logoSVG(C.tile, 280));
write(B('svg/logo-on-dark.svg'), logoSVG(C.paper, 280));
write(B('svg/readme-header-light.svg'), headerSVG({ bg: C.cream, text: C.tile, tag: C.grey }));
write(B('svg/readme-header-dark.svg'), headerSVG({ bg: C.night, text: C.paper, tag: C.greyDark }));
write(B('svg/social-preview.svg'), socialSVG());

// Home Assistant brand images (loaded from the integration folder since HA 2026.3)
const HA = (rel) => path.join(DEST.ha, rel);
await png(iconAt(256), HA('icon.png'));
await png(iconAt(512), HA('icon@2x.png'));
await png(iconAt(256), HA('dark_icon.png'));
await png(iconAt(512), HA('dark_icon@2x.png'));
await png(logoSVG(C.tile, 128), HA('logo.png'));
await png(logoSVG(C.tile, 256), HA('logo@2x.png'));
await png(logoSVG(C.paper, 128), HA('dark_logo.png'));
await png(logoSVG(C.paper, 256), HA('dark_logo@2x.png'));

// Icon size ladder (mini artwork for <= 32 px)
for (const n of [16, 24, 32]) await png(iconAt(n, { mini: true }), B(`png/icon/icon-${n}.png`));
for (const n of [48, 64, 96, 128, 192, 256, 384, 512, 1024, 2048]) await png(iconAt(n), B(`png/icon/icon-${n}.png`));
// Mark only (transparent)
for (const h of [128, 256, 512, 1024]) {
  await png(markSVG(C.tile, h), B(`png/mark/mark-on-light-${h}h.png`));
  await png(markSVG(C.paper, h), B(`png/mark/mark-on-dark-${h}h.png`));
}
// Logo
for (const h of [64, 128, 256, 512]) {
  await png(logoSVG(C.tile, h), B(`png/logo/logo-on-light-${h}h.png`));
  await png(logoSVG(C.paper, h), B(`png/logo/logo-on-dark-${h}h.png`));
}

// GitHub
const G = (rel) => path.join(DEST.github, rel);
await png(headerSVG({ bg: C.cream, text: C.tile, tag: C.grey }, 1), G('readme-header-light.png'));
await png(headerSVG({ bg: C.cream, text: C.tile, tag: C.grey }, 2), G('readme-header-light@2x.png'));
await png(headerSVG({ bg: C.night, text: C.paper, tag: C.greyDark }, 1), G('readme-header-dark.png'));
await png(headerSVG({ bg: C.night, text: C.paper, tag: C.greyDark }, 2), G('readme-header-dark@2x.png'));
await png(socialSVG(), G('social-preview-1280x640.png'));
await png(iconAt(500, { fullBleed: true }), G('org-avatar-500.png'));
await png(iconAt(1024, { fullBleed: true }), G('org-avatar-1024.png'));

// Web / Favicons
for (const n of [16, 32, 48]) await png(iconAt(n, { mini: n <= 32 }), B(`favicon/favicon-${n}.png`));
ico([16, 32, 48].map((n) => B(`favicon/favicon-${n}.png`)), B('favicon/favicon.ico'));
await png(iconAt(180, { fullBleed: true }), B('favicon/apple-touch-icon-180.png'));
await png(iconAt(192), B('favicon/android-chrome-192.png'));
await png(iconAt(512), B('favicon/android-chrome-512.png'));
write(B('favicon/favicon.svg'), iconAt(64, { mini: true }));

console.log('done');
