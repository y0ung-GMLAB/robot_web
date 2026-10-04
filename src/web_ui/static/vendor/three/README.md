# three.js 벤더 사본 · r160 (npm `three@0.160.0`) · MIT

- `three.module.js` · `build/three.module.js` 그대로
- `OrbitControls.js` · `examples/jsm/controls/OrbitControls.js` · import 경로만 `'three'` → `'./three.module.js'`
- 쓰는 곳 · `static/js/sim3d.js` (웹 3D 표시 · 수정 목록 7-a) · 탭을 열 때만 동적 import
- CDN 을 쓰지 않는다 · 매장 PC 는 외부망이 없을 수 있다 · 갱신은 같은 버전 파일을 통째로 바꾼다
