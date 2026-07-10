// gen-og-image.mjs - render the social share (Open Graph) cover image.
//
// Link-preview cards (KakaoTalk, Slack, Discord, iMessage, Facebook, X)
// read `og:image` plus its declared `og:image:width` / `og:image:height`.
// FDAI ships a 4:3 cover (1200x900) so the preview renders as a 4:3 card
// instead of the default 1.91:1 letterbox. The meta tags are wired in
// astro.config.mjs; this script only rasterizes the committed PNG.
//
// The image is a static asset committed at site/public/og-cover.png. Run
// `npm run gen-og` to regenerate it after editing the design below; the
// output is deterministic so a regenerated PNG only changes when the SVG
// does. sharp (an Astro transitive dependency) does the SVG -> PNG raster.

import { fileURLToPath } from "node:url";
import path from "node:path";
import sharp from "sharp";

const WIDTH = 1200;
const HEIGHT = 900; // 4:3

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(scriptDir, "..", "public", "og-cover.png");

// Brand palette mirrors site/src/styles/custom.css and CustomHero.astro:
//   deep-space bg  #05070f, Azure accent #0078D4, cyan #50E6FF.
const svg = `<svg width="${WIDTH}" height="${HEIGHT}" viewBox="0 0 ${WIDTH} ${HEIGHT}"
     xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#05070f"/>
      <stop offset="55%" stop-color="#070b18"/>
      <stop offset="100%" stop-color="#0a1226"/>
    </linearGradient>
    <radialGradient id="glow" cx="26%" cy="32%" r="60%">
      <stop offset="0%" stop-color="#0078D4" stop-opacity="0.45"/>
      <stop offset="60%" stop-color="#0078D4" stop-opacity="0.10"/>
      <stop offset="100%" stop-color="#0078D4" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="wordmark" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#4aa8ff"/>
      <stop offset="100%" stop-color="#50E6FF"/>
    </linearGradient>
  </defs>

  <rect width="${WIDTH}" height="${HEIGHT}" fill="url(#bg)"/>
  <rect width="${WIDTH}" height="${HEIGHT}" fill="url(#glow)"/>

  <!-- decorative node graph, echoing the landing hero -->
  <g stroke="#0078D4" stroke-opacity="0.35" stroke-width="2" fill="none">
    <path d="M120 760 L300 690 L470 730 L640 650"/>
    <path d="M1080 150 L960 240 L1010 360 L900 430"/>
  </g>
  <g fill="#50E6FF">
    <circle cx="120" cy="760" r="6" fill-opacity="0.9"/>
    <circle cx="300" cy="690" r="5" fill-opacity="0.7"/>
    <circle cx="470" cy="730" r="6" fill-opacity="0.85"/>
    <circle cx="640" cy="650" r="4" fill-opacity="0.6"/>
    <circle cx="1080" cy="150" r="6" fill-opacity="0.85"/>
    <circle cx="960" cy="240" r="4" fill-opacity="0.6"/>
    <circle cx="1010" cy="360" r="5" fill-opacity="0.7"/>
    <circle cx="900" cy="430" r="6" fill-opacity="0.9"/>
  </g>

  <g font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" text-anchor="middle">
    <!-- wordmark -->
    <text x="600" y="420" font-size="220" font-weight="700"
          letter-spacing="8" fill="url(#wordmark)">FDAI</text>
    <!-- full name, small caps -->
    <text x="600" y="500" font-size="42" font-weight="600" letter-spacing="14"
          fill="#c7d3e6">FORWARD DEPLOYED AGENTS</text>
    <!-- tagline -->
    <text x="600" y="600" font-size="34" font-weight="400" fill="#8ea0bd">
      Deterministic-first, event-driven, risk-gated cloud operations.
    </text>
  </g>

  <!-- footer url -->
  <text x="600" y="820" text-anchor="middle"
        font-family="'DejaVu Sans Mono', 'Courier New', monospace"
        font-size="26" letter-spacing="2" fill="#5a6b86">dotnetpower.github.io/fdai</text>
</svg>`;

await sharp(Buffer.from(svg)).png().toFile(OUT);
// eslint-disable-next-line no-console
console.log(`[gen-og-image] wrote ${path.relative(process.cwd(), OUT)} (${WIDTH}x${HEIGHT})`);
