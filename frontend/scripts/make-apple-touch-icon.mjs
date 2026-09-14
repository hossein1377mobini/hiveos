import { deflateSync } from "node:zlib";
import { writeFileSync } from "node:fs";

/* Rasterises the favicon geometry into a 180x180 PNG for apple-touch-icon.
   Done in-process with zlib rather than a new dependency: an air-gapped on-prem
   install must not need an image toolchain to build the frontend. */

const SIZE = 180;
const SCALE = SIZE / 32; // favicon viewBox is 32x32
const NAVY = [0x26, 0x31, 0x5c];
const AMBER = [0xf2, 0xa9, 0x3b];

// Pointy-top hexagon, same vertices as public/favicon.svg.
const OUTER = [[16, 2.5], [27.7, 9.25], [27.7, 22.75], [16, 29.5], [4.3, 22.75], [4.3, 9.25]];

function scaled(points, factor) {
  return points.map(([x, y]) => [
    16 + (x - 16) * factor,
    16 + (y - 16) * factor,
  ]);
}
const INNER = scaled(OUTER, 0.66);

function inPolygon(px, py, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function sample(x, y) {
  // supersample 3x3 for a clean edge on iOS at 180px
  let r = 0, g = 0, b = 0, n = 0;
  for (let sy = 0; sy < 3; sy++) {
    for (let sx = 0; sx < 3; sx++) {
      const px = (x + (sx + 0.5) / 3) / SCALE;
      const py = (y + (sy + 0.5) / 3) / SCALE;
      // iOS masks the corners itself, so the icon is a full-bleed square.
      let c = NAVY;
      if (inPolygon(px, py, OUTER)) c = NAVY;
      if (inPolygon(px, py, INNER)) c = [255, 255, 255];
      const inCircle = (px - 16) ** 2 + (py - 16) ** 2 <= 3.4 ** 2;
      if (inCircle) c = AMBER;
      if (inPolygon(px, py, OUTER) && !inPolygon(px, py, INNER) && !inCircle) {
        // thin ring between the two hexagons
        c = [255, 255, 255];
      }
      r += c[0]; g += c[1]; b += c[2]; n++;
    }
  }
  return [Math.round(r / n), Math.round(g / n), Math.round(b / n), 255];
}

const raw = Buffer.alloc(SIZE * (SIZE * 4 + 1));
let o = 0;
for (let y = 0; y < SIZE; y++) {
  raw[o++] = 0; // filter type 0 (None)
  for (let x = 0; x < SIZE; x++) {
    const [r, g, b, a] = sample(x, y);
    raw[o++] = r; raw[o++] = g; raw[o++] = b; raw[o++] = a;
  }
}

function crc32(buf) {
  let c, crc = 0xffffffff;
  for (let i = 0; i < buf.length; i++) {
    c = (crc ^ buf[i]) & 0xff;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crc = (crc >>> 8) ^ c;
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

const ihdr = Buffer.alloc(13);
ihdr.writeUInt32BE(SIZE, 0);
ihdr.writeUInt32BE(SIZE, 4);
ihdr[8] = 8;  // bit depth
ihdr[9] = 6;  // colour type RGBA
ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;

const png = Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  chunk("IHDR", ihdr),
  chunk("IDAT", deflateSync(raw, { level: 9 })),
  chunk("IEND", Buffer.alloc(0)),
]);

const target = process.argv[2];
writeFileSync(target, png);
console.log("wrote " + target + " (" + png.length + " bytes)");
