// Files written byte by byte, for the downloads of figures and tables: a ZIP archive (a Word document is one), a PNG that
// says its resolution (pHYs: 300 or 600 dpi, so that a journal's system reads the figure at its printed size) and a TIFF
// (RGB, PackBits — the format many journals ask for, with its resolution).  No library: these are small, fixed formats.

let CRC_TABLE = null;

/** CRC-32 (IEEE 802.3) of bytes, as PNG and ZIP use it. */
export function crc32(bytes, crc = 0) {
  if (!CRC_TABLE) {
    CRC_TABLE = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      CRC_TABLE[n] = c >>> 0;
    }
  }
  let c = (crc ^ 0xffffffff) >>> 0;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

const utf8 = (s) => new TextEncoder().encode(s);

/** A ZIP archive of [{name, data (string or bytes)}], stored (not compressed), names in UTF-8. */
export function zip(files, date = new Date()) {
  const time = ((date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1)) & 0xffff;
  const day = (((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate()) & 0xffff;
  const parts = [];
  const central = [];
  let offset = 0;
  for (const f of files) {
    const name = utf8(f.name);
    const data = typeof f.data === "string" ? utf8(f.data) : f.data;
    const crc = crc32(data);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true);
    local.setUint16(6, 0x0800, true); // the name is UTF-8
    local.setUint16(8, 0, true); // stored
    local.setUint16(10, time, true);
    local.setUint16(12, day, true);
    local.setUint32(14, crc, true);
    local.setUint32(18, data.length, true);
    local.setUint32(22, data.length, true);
    local.setUint16(26, name.length, true);
    local.setUint16(28, 0, true);
    parts.push(new Uint8Array(local.buffer), name, data);
    const c = new DataView(new ArrayBuffer(46));
    c.setUint32(0, 0x02014b50, true);
    c.setUint16(4, 20, true);
    c.setUint16(6, 20, true);
    c.setUint16(8, 0x0800, true);
    c.setUint16(10, 0, true);
    c.setUint16(12, time, true);
    c.setUint16(14, day, true);
    c.setUint32(16, crc, true);
    c.setUint32(20, data.length, true);
    c.setUint32(24, data.length, true);
    c.setUint16(28, name.length, true);
    c.setUint32(42, offset, true);
    central.push(new Uint8Array(c.buffer), name);
    offset += 30 + name.length + data.length;
  }
  const size = central.reduce((a, b) => a + b.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, files.length, true);
  end.setUint16(10, files.length, true);
  end.setUint32(12, size, true);
  end.setUint32(16, offset, true);
  return concat([...parts, ...central, new Uint8Array(end.buffer)]);
}

export function concat(chunks) {
  const out = new Uint8Array(chunks.reduce((a, b) => a + b.length, 0));
  let at = 0;
  for (const c of chunks) { out.set(c, at); at += c.length; }
  return out;
}

/** A PNG's bytes with its resolution set (a pHYs chunk after IHDR, any other one dropped). */
export function pngWithDpi(bytes, dpi) {
  const ppm = Math.round(dpi / 0.0254);
  const chunk = new Uint8Array(21);
  const v = new DataView(chunk.buffer);
  v.setUint32(0, 9);
  chunk.set(utf8("pHYs"), 4);
  v.setUint32(8, ppm);
  v.setUint32(12, ppm);
  chunk[16] = 1; // the unit is the metre
  v.setUint32(17, crc32(chunk.subarray(4, 17)));
  const out = [bytes.subarray(0, 33), chunk]; // the signature and IHDR, then pHYs
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  for (let at = 33; at + 8 <= bytes.length;) {
    const len = view.getUint32(at);
    const type = String.fromCharCode(...bytes.subarray(at + 4, at + 8));
    if (type !== "pHYs") out.push(bytes.subarray(at, at + 12 + len));
    at += 12 + len;
  }
  return concat(out);
}

/** PackBits (TIFF compression 32773) of one row. */
export function packBits(src) {
  const out = [];
  let i = 0;
  const n = src.length;
  while (i < n) {
    let j = i;
    while (j + 1 < n && src[j + 1] === src[i] && j - i < 127) j++;
    if (j > i) { // a run of the same byte
      out.push(257 - (j - i + 1), src[i]);
      i = j + 1;
      continue;
    }
    let k = i;
    while (k < n && k - i < 128 && !(k + 1 < n && src[k] === src[k + 1])) k++;
    out.push(k - i - 1);
    for (let x = i; x < k; x++) out.push(src[x]);
    i = k;
  }
  return Uint8Array.from(out);
}

/** The bytes PackBits came from (for the tests). */
export function unpackBits(src, size) {
  const out = new Uint8Array(size);
  let i = 0, o = 0;
  while (i < src.length && o < size) {
    const n = src[i] > 127 ? src[i] - 256 : src[i];
    i++;
    if (n >= 0) { out.set(src.subarray(i, i + n + 1), o); o += n + 1; i += n + 1; } else if (n !== -128) { out.fill(src[i], o, o + 1 - n); o += 1 - n; i++; }
  }
  return out;
}

/** A TIFF (RGB, 8 bits a sample, PackBits, 16 rows a strip) of an image's pixels ({width, height, data: RGBA}) at a
 * resolution in dots per inch; transparent pixels on white. */
export function tiff({ width, height, data }, dpi) {
  const rowsPerStrip = 16;
  const strips = [];
  const row = new Uint8Array(width * 3);
  for (let y0 = 0; y0 < height; y0 += rowsPerStrip) {
    const packed = [];
    for (let y = y0; y < Math.min(height, y0 + rowsPerStrip); y++) {
      for (let x = 0; x < width; x++) {
        const s = (y * width + x) * 4, a = data[s + 3] / 255;
        row[x * 3] = Math.round(data[s] * a + 255 * (1 - a));
        row[x * 3 + 1] = Math.round(data[s + 1] * a + 255 * (1 - a));
        row[x * 3 + 2] = Math.round(data[s + 2] * a + 255 * (1 - a));
      }
      packed.push(packBits(row));
    }
    strips.push(concat(packed));
  }
  const tags = 13;
  const ifd = 8, extra = ifd + 2 + tags * 12 + 4;
  const bits = extra, xres = bits + 6, yres = xres + 8, offs = yres + 8, counts = offs + 4 * strips.length;
  let data0 = counts + 4 * strips.length;
  const head = new DataView(new ArrayBuffer(data0));
  head.setUint16(0, 0x4949, true); // II: little-endian
  head.setUint16(2, 42, true);
  head.setUint32(4, ifd, true);
  head.setUint16(ifd, tags, true);
  const entries = [
    [256, 4, 1, width], [257, 4, 1, height], [258, 3, 3, bits], [259, 3, 1, 32773], [262, 3, 1, 2],
    [273, 4, strips.length, strips.length === 1 ? data0 : offs], [277, 3, 1, 3], [278, 4, 1, rowsPerStrip],
    [279, 4, strips.length, strips.length === 1 ? strips[0].length : counts], [282, 5, 1, xres], [283, 5, 1, yres],
    [284, 3, 1, 1], [296, 3, 1, 2],
  ];
  entries.forEach(([tag, type, count, value], k) => {
    const at = ifd + 2 + k * 12;
    head.setUint16(at, tag, true);
    head.setUint16(at + 2, type, true);
    head.setUint32(at + 4, count, true);
    if (type === 3 && count === 1) head.setUint16(at + 8, value, true); else head.setUint32(at + 8, value, true);
  });
  head.setUint32(ifd + 2 + tags * 12, 0, true); // no next directory
  for (let k = 0; k < 3; k++) head.setUint16(bits + k * 2, 8, true);
  head.setUint32(xres, Math.round(dpi), true); head.setUint32(xres + 4, 1, true);
  head.setUint32(yres, Math.round(dpi), true); head.setUint32(yres + 4, 1, true);
  strips.forEach((s, k) => {
    head.setUint32(offs + 4 * k, data0, true);
    head.setUint32(counts + 4 * k, s.length, true);
    data0 += s.length;
  });
  return concat([new Uint8Array(head.buffer), ...strips]);
}
