/** UI v2 · 폴더 → zip (압축 없이 담기만 · STORE) · 로봇 팩 폴더를 브라우저가 묶어 올린다 (설계안 2026-10-09)
 *
 * 서버는 zip 만 받는다(PUT /api/robot-pack · application/zip). 팩은 메쉬·모델 몇 MB 라 압축 없이도 된다.
 * 숨김 파일(.으로 시작)과 맥의 __MACOSX 는 뺀다 · 경로는 / 로 · UTF-8 이름(플래그 0x0800).
 */

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

export function crc32(bytes) {
  let crc = 0xFFFFFFFF;
  for (let i = 0; i < bytes.length; i += 1) crc = CRC_TABLE[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
  return (crc ^ 0xFFFFFFFF) >>> 0;
}

/** 담을 것인가 · 숨김 · __MACOSX 빼기 */
export function keepPath(path) {
  const parts = String(path || '').split('/').filter(Boolean);
  return parts.length > 0 && !parts.some((part) => part.startsWith('.') || part === '__MACOSX');
}

function dosTime(date) {
  const time = (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
  const day = ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  return { time, day };
}

/**
 * entries [{path, bytes: Uint8Array}] → Uint8Array (zip)
 * 시험에서도 쓰려고 바이트만 다룬다 · 파일 읽기는 zipFiles 가 한다
 */
export function buildZip(entries, now = new Date()) {
  const encoder = new TextEncoder();
  const { time, day } = dosTime(now);
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const entry of entries) {
    const name = encoder.encode(entry.path);
    const data = entry.bytes;
    const crc = crc32(data);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034B50, true);
    local.setUint16(4, 20, true);
    local.setUint16(6, 0x0800, true);
    local.setUint16(8, 0, true);
    local.setUint16(10, time, true);
    local.setUint16(12, day, true);
    local.setUint32(14, crc, true);
    local.setUint32(18, data.length, true);
    local.setUint32(22, data.length, true);
    local.setUint16(26, name.length, true);
    local.setUint16(28, 0, true);
    locals.push(new Uint8Array(local.buffer), name, data);
    const central = new DataView(new ArrayBuffer(46));
    central.setUint32(0, 0x02014B50, true);
    central.setUint16(4, 20, true);
    central.setUint16(6, 20, true);
    central.setUint16(8, 0x0800, true);
    central.setUint16(10, 0, true);
    central.setUint16(12, time, true);
    central.setUint16(14, day, true);
    central.setUint32(16, crc, true);
    central.setUint32(20, data.length, true);
    central.setUint32(24, data.length, true);
    central.setUint16(28, name.length, true);
    central.setUint32(42, offset, true);
    centrals.push(new Uint8Array(central.buffer), name);
    offset += 30 + name.length + data.length;
  }
  const centralSize = centrals.reduce((sum, part) => sum + part.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054B50, true);
  end.setUint16(8, entries.length, true);
  end.setUint16(10, entries.length, true);
  end.setUint32(12, centralSize, true);
  end.setUint32(16, offset, true);
  const parts = [...locals, ...centrals, new Uint8Array(end.buffer)];
  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let at = 0;
  for (const part of parts) { out.set(part, at); at += part.length; }
  return out;
}

/** [{path, file}] → Blob(zip) */
export async function zipFiles(items) {
  const entries = [];
  for (const item of items) {
    if (!keepPath(item.path)) continue;
    entries.push({ path: item.path, bytes: new Uint8Array(await item.file.arrayBuffer()) });
  }
  if (!entries.length) throw new Error('담을 파일이 없습니다');
  return new Blob([buildZip(entries)], { type: 'application/zip' });
}

/** 끌어 놓은 폴더 · 안의 파일을 모두 [{path, file}] 로 */
export async function filesFromDrop(dataTransfer) {
  const roots = [...(dataTransfer?.items || [])].map((item) => item.webkitGetAsEntry?.()).filter(Boolean);
  const out = [];
  async function walk(entry, prefix) {
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      out.push({ path: `${prefix}${entry.name}`, file });
      return;
    }
    const reader = entry.createReader();
    for (;;) {
      const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
      if (!batch.length) break;
      for (const child of batch) await walk(child, `${prefix}${entry.name}/`);
    }
  }
  for (const root of roots) await walk(root, '');
  return out;
}
