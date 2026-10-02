/** 상태 목록은 한 곳에서만 적는다 · §6-167
 *
 * **같은 목록을 두 곳에 적으면 언젠가 한쪽만 고친다.**
 *
 * 화면에 이런 것들이 흩어져 있었다.
 *
 *   ['initializing', 'playing', 'recording', 'stopping']   editor_math.js
 *        ↑ 같은 것인데 **순서가 달라** 한눈에 안 보였다
 *   ['playing', 'recording']                               playback.js ×2
 *   ['failure', 'timeout', 'cancelled']                    main.js ×2
 *        ↑ restart_tracking.js 에 이미 이름이 있었는데도
 *
 * 새 상태가 하나 생기면 전부 고쳐야 하고, 빠뜨린 곳만 조용히 틀린다 ·
 * 터지지 않으니 한참 모른다.
 */

import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import test from 'node:test';

const JS_DIR = new URL('../static/js/', import.meta.url);

function sources() {
  return readdirSync(JS_DIR)
    .filter((name) => name.endsWith('.js'))
    .map((name) => [name, readFileSync(new URL(name, JS_DIR), 'utf8')]);
}

/** 이 목록들이 다시 손으로 적히면 안 된다 · 순서를 바꿔 적어도 잡는다. */
const OWNED_LISTS = [
  { owner: 'TERMINAL_FAILURES', members: ['failure', 'timeout', 'cancelled'] },
];

/** 그 목록을 정의한 파일 · 여기 한 번만 적혀 있어야 한다. */
const OWNER_FILES = new Set(['restart_tracking.js']);

for (const { owner, members } of OWNED_LISTS) {
  test(`${owner} 목록을 다시 손으로 적은 곳이 없다`, () => {
    // 순서를 바꿔 적어도 잡는다 · 실제로 한 곳이 그랬다
    const quoted = members.map((m) => `'${m}'`);
    const offenders = [];
    for (const [name, text] of sources()) {
      if (OWNER_FILES.has(name)) continue;
      for (const match of text.matchAll(/[[{]\s*('[a-z_-]+'\s*(?:,\s*'[a-z_-]+'\s*)+)[\]}]/g)) {
        const found = match[1].split(',').map((s) => s.trim());
        if (found.length !== quoted.length) continue;
        if ([...found].sort().join() === [...quoted].sort().join()) {
          offenders.push(`${name}: ${match[0]}`);
        }
      }
    }
    assert.deepEqual(offenders, [], (
      `${owner} 의 목록을 직접 적고 있습니다 · 주인을 가져다 쓰세요:\n  `
      + offenders.join('\n  ')
    ));
  });
}
