/** 웹 3D 표시 · MuJoCo 계산 결과를 브라우저가 그린다 · 수정 목록 7-a (2026-10-04)
 *
 * 네이티브 뷰어 창은 서버 PC 모니터에만 뜬다 · 원격 접속자도 보려면 브라우저가
 * 그려야 한다 · 물리 계산은 그대로 MuJoCo(`.sim.npz`) · 여기는 **그리기만** 한다.
 *
 *   장면      GET /api/preview/scene (상태) → POST /api/preview/scene/export (팩마다 1회)
 *             → GET /api/preview/scene/data (바디·관절·지옴·메쉬 JSON)
 *   프레임    GET /api/motion-files/{id}/preview-frames (t · qpos · 60 Hz 이하)
 *   자세      static/js/sim3d_math.js · MuJoCo 와 같은 순방향 운동학
 *
 * three.js 는 탭을 열 때 처음 한 번만 동적으로 받는다(1.2 MB · 벤더 사본 ·
 * `static/vendor/three/`) · 초기 화면 무게에 얹지 않는다.
 *
 * 「MuJoCo 같이 보기」(모션 패널 체크) · 켜면 이 구역을 열고 **재생 등록된**
 * 애니메이션의 프레임을 받아 두었다가, 재생 상태가 running 으로 바뀌는 순간
 * 0초부터 틀고 stopped/error/completed 면 멈춘다 · 시작 동기의 정밀도는
 * 8번(별도) · 여기선 같은 순간에 출발만 한다 · 네이티브 뷰어 창은 없앴다(7).
 */
import { exportPreviewScene, fetchPreviewFrames, fetchPreviewScene, fetchPreviewSceneData } from './api.js';
import {
  bodyLocalPose, cameraPosition, followEndSec, followRunKey, frameIndexAt, jointsByBody,
} from './sim3d_math.js';

const THREE_URL = '/static/vendor/three/three.module.js';
const CONTROLS_URL = '/static/vendor/three/OrbitControls.js';
const SCENE_POLL_MS = 3000;

/** 재생 상태 → 「실물 따라가기」 동작 · 한 곳에만 적는다 */
const FOLLOW_START_STATES = new Set(['running']);
const FOLLOW_STOP_STATES = new Set(['stopped', 'error', 'completed', 'idle', 'ready']);

export function createSim3dViewer({ el, getLatestState = () => null }) {
  let THREE = null;
  let OrbitControls = null;
  let renderer = null;
  let scene3 = null;
  let camera = null;
  let controls = null;
  let bodyGroups = [];
  let jointMap = new Map();
  let sceneJson = null;
  let sceneState = null;
  let frames = null;          // {t, qpos, duration_sec, nq}
  let framesFileId = '';
  let currentFile = null;     // 선택된 애니메이션 (목록 항목)
  let playing = false;
  let playhead = 0;           // 초
  let speed = 1;
  let lastTick = 0;
  let rafId = 0;
  let follow = false;
  let followFile = null;      // 같이 보기 대상 · 재생 등록된 애니메이션
  let lastRunState = '';
  let pollTimer = null;
  let message = '';
  let opened = false;

  const has = (name) => Boolean(el[name]);

  function setMessage(text) {
    message = text || '';
    if (has('sim3dStatus')) el.sim3dStatus.textContent = message;
  }

  // ------------------------------------------------------------------ //
  // three.js · 장면 세우기
  // ------------------------------------------------------------------ //

  async function ensureThree() {
    if (THREE) return;
    THREE = await import(THREE_URL);
    ({ OrbitControls } = await import(CONTROLS_URL));
  }

  function quatToThree(q) {
    return new THREE.Quaternion(q[1], q[2], q[3], q[0]);
  }

  function geomMesh(geom, meshes) {
    const rgba = geom.rgba || [0.6, 0.6, 0.6, 1];
    const material = new THREE.MeshStandardMaterial({
      color: new THREE.Color(rgba[0], rgba[1], rgba[2]),
      transparent: rgba[3] < 1,
      opacity: rgba[3],
      metalness: 0.1,
      roughness: 0.7,
      side: THREE.DoubleSide,
    });
    const [sx, sy, sz] = geom.size;
    let geometry = null;
    switch (geom.type) {
      case 'box': geometry = new THREE.BoxGeometry(sx * 2, sy * 2, sz * 2); break;
      case 'sphere': geometry = new THREE.SphereGeometry(sx, 24, 16); break;
      case 'ellipsoid': geometry = new THREE.SphereGeometry(1, 24, 16); break;
      case 'capsule': geometry = new THREE.CapsuleGeometry(sx, sy * 2, 6, 16); break;
      case 'cylinder': geometry = new THREE.CylinderGeometry(sx, sx, sy * 2, 24); break;
      case 'plane': {
        const w = sx > 0 ? sx * 2 : 20;
        const h = sy > 0 ? sy * 2 : 20;
        geometry = new THREE.PlaneGeometry(w, h);
        material.opacity = Math.min(material.opacity, 0.35);
        material.transparent = true;
        break;
      }
      case 'mesh': {
        const data = meshes[geom.mesh];
        if (!data) return null;
        geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(data.vertices, 3));
        geometry.setIndex(data.faces);
        geometry.computeVertexNormals();
        break;
      }
      default: return null;
    }
    const mesh = new THREE.Mesh(geometry, material);
    // MuJoCo 캡슐·원기둥은 z 축 · three.js 는 y 축 → 지옴 자세에 x 축 90° 를 먼저 곱한다
    const q = quatToThree(geom.quat || [1, 0, 0, 0]);
    if (geom.type === 'capsule' || geom.type === 'cylinder') {
      q.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2));
    }
    if (geom.type === 'ellipsoid') mesh.scale.set(sx, sy, sz);
    mesh.quaternion.copy(q);
    mesh.position.set(geom.pos[0], geom.pos[1], geom.pos[2]);
    return mesh;
  }

  function buildScene(json) {
    disposeScene();
    scene3 = new THREE.Scene();
    scene3.background = null;
    scene3.add(new THREE.HemisphereLight(0xffffff, 0x334455, 1.1));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(1.5, -2.0, 3.0);
    scene3.add(sun);
    const grid = new THREE.GridHelper(4, 20, 0x5aa2ff, 0x3a4652);
    grid.rotation.x = Math.PI / 2;      // z-up
    grid.position.z = 0.0005;
    scene3.add(grid);

    bodyGroups = [];
    jointMap = jointsByBody(json);
    for (const body of json.bodies) {
      const group = new THREE.Group();
      group.name = body.name;
      bodyGroups.push(group);
      if (body.parent < 0) scene3.add(group); else bodyGroups[body.parent].add(group);
    }
    for (const geom of json.geoms) {
      if (geom.group >= 3) continue;        // MuJoCo 기본 뷰어와 같이 0~2 만
      const mesh = geomMesh(geom, json.meshes || {});
      if (mesh) bodyGroups[geom.body].add(mesh);
    }
    applyPose(null);

    const cam = json.camera || {};
    const position = cameraPosition(cam);
    const lookat = cam.lookat || [0, 0, 0];
    camera = new THREE.PerspectiveCamera(45, 1, 0.01, 100);
    camera.up.set(0, 0, 1);
    camera.position.set(position[0], position[1], position[2]);
    camera.lookAt(lookat[0], lookat[1], lookat[2]);
    if (controls) controls.dispose();
    controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(lookat[0], lookat[1], lookat[2]);
    controls.update();
    resize();
  }

  function disposeScene() {
    if (!scene3) return;
    scene3.traverse((node) => {
      if (node.geometry) node.geometry.dispose();
      if (node.material) node.material.dispose();
    });
    scene3 = null;
    bodyGroups = [];
  }

  function applyPose(qpos) {
    if (!sceneJson || !bodyGroups.length) return;
    for (const body of sceneJson.bodies) {
      if (body.parent < 0) continue;
      const local = bodyLocalPose(body, jointMap.get(body.id), qpos);
      const group = bodyGroups[body.id];
      group.position.set(local.pos[0], local.pos[1], local.pos[2]);
      group.quaternion.copy(quatToThree(local.quat));
    }
  }

  function ensureRenderer() {
    if (renderer || !has('sim3dCanvasWrap')) return;
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    el.sim3dCanvasWrap.appendChild(renderer.domElement);
    window.addEventListener('resize', resize);
  }

  function resize() {
    if (!renderer || !camera || !has('sim3dCanvasWrap')) return;
    const width = Math.max(el.sim3dCanvasWrap.clientWidth, 200);
    const height = Math.max(el.sim3dCanvasWrap.clientHeight, 240);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  // ------------------------------------------------------------------ //
  // 장면 상태 · 서버
  // ------------------------------------------------------------------ //

  async function refreshScene({ allowExport = false } = {}) {
    try {
      sceneState = await fetchPreviewScene();
    } catch (error) {
      setMessage(`3D 장면 상태 확인 실패: ${error?.message || error}`);
      return;
    }
    const state = sceneState?.state || '';
    if (state === 'ready') {
      if (!sceneJson) await loadSceneData();
    } else if (state === 'missing' && allowExport) {
      await requestExport();
    } else {
      setMessage(sceneState?.message || `3D 장면 · ${state}`);
      if (state === 'computing') schedulePoll();
    }
    renderControls();
  }

  async function requestExport() {
    try {
      const result = await exportPreviewScene();
      setMessage(result?.message || '3D 장면을 만들기 시작했습니다');
      schedulePoll();
    } catch (error) {
      setMessage(`3D 장면 준비 실패: ${error?.message || error}`);
    }
  }

  function schedulePoll() {
    if (pollTimer) return;
    pollTimer = window.setTimeout(async () => {
      pollTimer = null;
      if (opened) await refreshScene();
    }, SCENE_POLL_MS);
  }

  async function loadSceneData() {
    try {
      await ensureThree();
      sceneJson = await fetchPreviewSceneData();
      ensureRenderer();
      buildScene(sceneJson);
      setMessage(`3D 장면 준비됨 · 바디 ${sceneJson.bodies.length} · 관절 ${sceneJson.joints.length}`);
      startLoop();
      if (currentFile) await loadFrames(currentFile.id);
    } catch (error) {
      setMessage(`3D 장면 불러오기 실패: ${error?.message || error}`);
    }
  }

  async function loadFrames(fileId) {
    if (!fileId) return;
    try {
      const payload = await fetchPreviewFrames(fileId);
      if (payload?.success === false) {
        frames = null; framesFileId = '';
        setMessage(payload.message || '계산 결과가 없습니다');
        renderControls();
        return;
      }
      frames = payload;
      framesFileId = fileId;
      playhead = 0;
      applyPose(frames.qpos[0] || null);
      setMessage(`${fileId} · ${frames.duration_sec.toFixed(1)}초 · ${frames.t.length}프레임 (${frames.hz} Hz)`);
    } catch (error) {
      frames = null; framesFileId = '';
      setMessage(`프레임 불러오기 실패: ${error?.message || error}`);
    }
    renderControls();
  }

  // ------------------------------------------------------------------ //
  // 재생
  // ------------------------------------------------------------------ //

  function startLoop() {
    if (rafId) return;
    lastTick = performance.now();
    const tick = (now) => {
      rafId = window.requestAnimationFrame(tick);
      const dt = Math.min((now - lastTick) / 1000, 0.25);
      lastTick = now;
      followRealRun();
      if (playing && frames) {
        playhead += dt * speed;
        // 따라가기는 애니메이션 길이에서 멈춘다 · 끝의 정착 3초는 실물에 없다
        const end = follow ? followEndSec(frames) : frames.duration_sec;
        if (playhead > end) {
          playhead = end;
          playing = false;
          renderControls();
        }
        applyPose(frames.qpos[frameIndexAt(frames.t, playhead)]);
        renderTime();
      }
      if (controls) controls.update();
      if (renderer && scene3 && camera) renderer.render(scene3, camera);
    };
    rafId = window.requestAnimationFrame(tick);
  }

  function stopLoop() {
    if (rafId) window.cancelAnimationFrame(rafId);
    rafId = 0;
  }

  function followRealRun() {
    if (!follow || !frames) return;
    const status = getLatestState()?.motion_run_status || {};
    const state = String(status.state || '');
    // 상태만이 아니라 회차·파일까지 · 바로 다음 반복도 회차마다 처음부터 (수정 목록 8)
    const key = followRunKey(status);
    if (key === lastRunState) return;
    if (FOLLOW_START_STATES.has(state)) {
      playhead = 0;
      playing = true;
      renderControls();
    } else if (FOLLOW_STOP_STATES.has(state) && playing) {
      playing = false;
      renderControls();
    }
    lastRunState = key;
  }

  function seek(seconds) {
    if (!frames) return;
    playhead = Math.min(Math.max(seconds, 0), frames.duration_sec);
    applyPose(frames.qpos[frameIndexAt(frames.t, playhead)]);
    renderTime();
  }

  function renderTime() {
    if (has('sim3dSlider') && frames && document.activeElement !== el.sim3dSlider) {
      el.sim3dSlider.value = String(Math.round((playhead / Math.max(frames.duration_sec, 1e-6)) * 1000));
    }
    if (has('sim3dTime')) {
      el.sim3dTime.textContent = frames
        ? `${playhead.toFixed(2)} / ${frames.duration_sec.toFixed(2)} s`
        : '-- / -- s';
    }
  }

  // ------------------------------------------------------------------ //
  // 화면
  // ------------------------------------------------------------------ //

  function renderControls() {
    const state = sceneState?.state || '';
    const ready = state === 'ready' && Boolean(sceneJson);
    if (has('sim3dPrepareButton')) {
      el.sim3dPrepareButton.disabled = state === 'unavailable' || state === 'computing' || ready;
      el.sim3dPrepareButton.textContent = state === 'failed' ? '3D 장면 다시 만들기' : '3D 장면 준비';
    }
    if (has('sim3dLoadButton')) {
      el.sim3dLoadButton.disabled = !ready || !currentFile;
      el.sim3dLoadButton.title = currentFile ? `${currentFile.id} 의 계산 결과를 불러옵니다` : '애니메이션을 먼저 선택하세요';
    }
    if (has('sim3dPlayButton')) {
      el.sim3dPlayButton.disabled = !frames;
      el.sim3dPlayButton.textContent = playing ? '일시정지' : '재생';
    }
    if (has('sim3dSlider')) el.sim3dSlider.disabled = !frames;
    renderTime();
  }

  function bind() {
    el.sim3dPrepareButton?.addEventListener('click', () => requestExport());
    el.sim3dLoadButton?.addEventListener('click', () => currentFile && loadFrames(currentFile.id));
    el.sim3dPlayButton?.addEventListener('click', () => {
      if (!frames) return;
      if (!playing && playhead >= frames.duration_sec) playhead = 0;
      playing = !playing;
      renderControls();
    });
    el.sim3dSlider?.addEventListener('input', () => {
      if (!frames) return;
      seek((Number(el.sim3dSlider.value) / 1000) * frames.duration_sec);
    });
    el.sim3dSpeed?.addEventListener('change', () => { speed = Number(el.sim3dSpeed.value) || 1; });
    el.sim3dResetViewButton?.addEventListener('click', () => {
      if (sceneJson && camera && controls) {
        const p = cameraPosition(sceneJson.camera);
        camera.position.set(p[0], p[1], p[2]);
        const l = sceneJson.camera?.lookat || [0, 0, 0];
        controls.target.set(l[0], l[1], l[2]);
        controls.update();
      }
    });
    el.sim3dSection?.addEventListener('toggle', () => {
      opened = Boolean(el.sim3dSection.open);
      if (opened) { refreshScene({ allowExport: false }); resize(); } else { playing = false; }
    });
  }

  function usable(file) {
    return Boolean(file) && (file.preview?.state === 'ready' || file.preview?.state === 'stale');
  }

  /** 애니메이션 선택이 바뀌었을 때 · 모션 패널이 그릴 때마다 부른다 (싸다)
   *
   * 같이 보기 중에는 재생 등록된 파일을 붙들고 있는다 · 목록에서 다른 파일을
   * 눌러도 바뀌지 않는다 (실물이 재생할 것은 등록 파일이다)
   */
  function update({ file = null, registeredFile = null } = {}) {
    if (follow && followFile && registeredFile && registeredFile.id !== followFile.id) {
      followFile = registeredFile;           // 등록이 바뀌면 그쪽으로
    }
    const target = follow ? (followFile || registeredFile) : file;
    const changed = (target?.id || '') !== (currentFile?.id || '');
    currentFile = target;
    if (changed) {
      frames = null; framesFileId = ''; playing = false;
      if (opened && sceneJson && usable(target)) loadFrames(target.id);
    }
    renderControls();
  }

  /** 「MuJoCo 같이 보기」 체크 · 켜면 구역을 열고 등록 파일 프레임을 받아 둔다 */
  async function setFollow(enabled, registeredFile = null) {
    follow = Boolean(enabled);
    lastRunState = '';
    followFile = follow ? registeredFile : null;
    if (!follow) { playing = false; renderControls(); return; }
    if (has('sim3dSection') && !el.sim3dSection.open) {
      el.sim3dSection.open = true;             // toggle 이벤트가 refreshScene 을 부른다
    } else if (opened) {
      await refreshScene();
    }
    update({ file: currentFile, registeredFile });
  }

  function destroy() {
    stopLoop();
    if (pollTimer) window.clearTimeout(pollTimer);
    disposeScene();
    if (renderer) { renderer.dispose(); renderer = null; }
    window.removeEventListener('resize', resize);
  }

  bind();
  renderControls();
  return {
    update, setFollow, refreshScene, loadFrames, seek, destroy,
    get frames() { return frames; }, get framesFileId() { return framesFileId; }, get following() { return follow; },
  };
}
