# xterm.js · 벤더 사본 · §6-311

| 파일 | 출처 | 버전 |
|---|---|---|
| `xterm.js` · `xterm.css` | npm `@xterm/xterm` (`lib/xterm.js` · `css/xterm.css`) | 5.5.0 |
| `addon-fit.js` | npm `@xterm/addon-fit` (`lib/addon-fit.js`) | 0.10.0 |
| `LICENSE` | `@xterm/xterm` · MIT | |

- 현장 PC 는 인터넷이 없을 수 있다 · CDN 대신 저장소에 둔다
- 수정 금지 · 올릴 때는 `npm pack` 으로 받아 통째로 바꾼다
- 불러오는 곳 · `static/js/terminal_panel.js` (탭을 처음 열 때만 읽는다)
