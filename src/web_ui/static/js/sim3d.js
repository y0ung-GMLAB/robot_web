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
 * 「실물과 같이」(이 구역 체크 · **기본 켬** · 수정 목록 86) · **재생 등록된** 애니메이션의
 * 프레임을 받아 두었다가, 재생 상태가 running 으로 바뀌는 순간 0초부터 틀고
 * stopped/error/completed 면 멈춘다 · 켜 있으면 재생 버튼·슬라이더는 잠긴다(실물이 시계) ·
 * 끄면 목록에서 고른 애니를 직접 재생·슬라이더로 본다 · 전에는 모션 패널의 「MuJoCo 같이
 * 보기」(기본 끔)가 따로 있어, 기본이 「직접 재생」 이라 디지털 트윈으로 쓰는 뜻이 없었다.
 *
 * 「Blender 뷰」(수정 목록 50) · 팩에 `scene.glb` 가 있으면 체크가 보인다 · 켜면 MuJoCo
 * 장면 대신 Blender 가 내보낸 glTF 장면(헤드 4대 · 매장 오브제)을 그린다 · 물리 없음 ·
 * 시각은 실물 따라가기와 같은 시계(running · 회차 · 파일이 바뀌면 0 부터 · 멈추면 멈춤) ·
 * 애니메이션은 `AnimationMixer.setTime(t)` · 계산(.sim.npz) 없이 바로 된다.
 *
 * 「실물 위치」(수정 목록 7-c) · 실제 모터 위치를 서버가 매핑 식으로 되돌린 조인트 각도
 * (`motion_actual_rad` · 화면에는 deg)로 같은 로봇을 주황 반투명으로 겹쳐 그린다 · 계획
 * (MuJoCo 프레임)과 실물의 차이가 보인다 · MuJoCo 뷰에서만(glTF 는 관절을 따로 못 움직인다).
 */
import { exportPreviewScene, fetchPreviewFrames, fetchPreviewScene, fetchPreviewSceneData } from './api.js';
import {
  actualQpos, blenderHoldsAnimation, bodyLocalPose, cameraPosition, followEndSec, followRunKey, frameIndexAt, jointsByBody,
} from './sim3d_math.js';

const THREE_URL = '/static/vendor/three/three.module.js';
const CONTROLS_URL = '/static/vendor/three/OrbitControls.js';
const GLTF_LOADER_URL = '/static/vendor/three/GLTFLoader.js';
const BLENDER_SCENE_URL = '/api/preview/blender-scene';
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
  let follow = true;          // 「실물과 같이」 · 기본 켬 (86)
  let followFile = null;      // 같이 보기 대상 · 재생 등록된 애니메이션
  let lastRunState = '';
  let pollTimer = null;
  let message = '';
  let opened = false;
  // Blender 뷰 · 수정 목록 50
  let view = 'mujoco';        // 'mujoco' | 'blender'
  let blenderInfo = null;     // 서버 · {available, size_bytes, fingerprint}
  let blender = null;         // {scene, camera, controls, mixer, duration, fingerprint, home}
  let blenderLoading = false;
  // 실물 위치 겹쳐 보기 · 수정 목록 7-c
  let showActual = false;
  let actualGroups = [];
  let shownQpos = null;       // 지금 계획 로봇의 자세 · 실물 로봇의 관절 밖 칸(바닥·비틀림)을 여기서 빌린다
  let actualText = '';

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

  function geomMesh(geom, meshes, { ghost = false } = {}) {
    const rgba = geom.rgba || [0.6, 0.6, 0.6, 1];
    const material = new THREE.MeshStandardMaterial({
      color: ghost ? new THREE.Color(1.0, 0.55, 0.15) : new THREE.Color(rgba[0], rgba[1], rgba[2]),
      transparent: ghost || rgba[3] < 1,
      opacity: ghost ? 0.45 : rgba[3],
      depthWrite: !ghost,
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

    jointMap = jointsByBody(json);
    bodyGroups = buildRobot(json);
    actualGroups = [];
    if (showActual) actualGroups = buildRobot(json, { ghost: true });
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

  /** 바디 묶음 하나를 장면에 세운다 · ghost = 실물 위치용 주황 반투명 사본 */
  function buildRobot(json, { ghost = false } = {}) {
    const groups = [];
    for (const body of json.bodies) {
      const group = new THREE.Group();
      group.name = ghost ? `actual:${body.name}` : body.name;
      groups.push(group);
      if (body.parent < 0) scene3.add(group); else groups[body.parent].add(group);
    }
    for (const geom of json.geoms) {
      if (geom.group >= 3) continue;        // MuJoCo 기본 뷰어와 같이 0~2 만
      if (ghost && geom.type === 'plane') continue;   // 바닥은 하나면 된다
      const mesh = geomMesh(geom, json.meshes || {}, { ghost });
      if (mesh) groups[geom.body].add(mesh);
    }
    return groups;
  }

  function removeRobot(groups) {
    for (const group of groups) {
      group.traverse((node) => {
        if (node.geometry) node.geometry.dispose();
        if (node.material) node.material.dispose();
      });
      group.removeFromParent();
    }
  }

  function disposeScene() {
    if (!scene3) return;
    scene3.traverse((node) => {
      if (node.geometry) node.geometry.dispose();
      if (node.material) node.material.dispose();
    });
    scene3 = null;
    bodyGroups = [];
    actualGroups = [];
  }

  function applyPose(qpos, groups = bodyGroups) {
    if (!sceneJson || !groups.length) return;
    if (groups === bodyGroups) shownQpos = qpos;
    for (const body of sceneJson.bodies) {
      if (body.parent < 0) continue;
      const local = bodyLocalPose(body, jointMap.get(body.id), qpos);
      const group = groups[body.id];
      group.position.set(local.pos[0], local.pos[1], local.pos[2]);
      group.quaternion.copy(quatToThree(local.quat));
    }
  }

  /** 실물 로봇 자세 · 매 그림마다 · 받은 축 수를 상태줄에 */
  function applyActualPose() {
    if (!showActual || !actualGroups.length || !sceneJson) return;
    const motors = getLatestState()?.motors || [];
    const { qpos, matched, missing } = actualQpos(sceneJson, motors, shownQpos);
    applyPose(qpos, actualGroups);
    const text = missing.length
      ? `실물 위치 · ${matched}축 · 못 받은 축 ${missing.join(', ')}`
      : `실물 위치 · ${matched}축`;
    if (text !== actualText) {
      actualText = text;
      if (has('sim3dActualToggle')) el.sim3dActualToggle.parentElement.title = text;
    }
  }

  /** 체크 · 「실물 위치」 · 주황 반투명 사본을 세우거나 걷는다 */
  function setShowActual(enabled) {
    showActual = Boolean(enabled);
    if (showActual && sceneJson && scene3 && !actualGroups.length) {
      actualGroups = buildRobot(sceneJson, { ghost: true });
    } else if (!showActual && actualGroups.length) {
      removeRobot(actualGroups);
      actualGroups = [];
    }
    renderControls();
  }

  function ensureRenderer() {
    if (renderer || !has('sim3dCanvasWrap')) return;
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    el.sim3dCanvasWrap.appendChild(renderer.domElement);
    window.addEventListener('resize', resize);
  }

  function resize() {
    if (!renderer || !has('sim3dCanvasWrap')) return;
    const width = Math.max(el.sim3dCanvasWrap.clientWidth, 200);
    const height = Math.max(el.sim3dCanvasWrap.clientHeight, 240);
    renderer.setSize(width, height, false);
    for (const cam of [camera, blender?.camera]) {
      if (!cam) continue;
      cam.aspect = width / height;
      cam.updateProjectionMatrix();
    }
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
    blenderInfo = sceneState?.blender || null;
    if (view === 'blender' && !blenderAllowed()) await setView('mujoco');
    if (view === 'blender' && blender && blenderInfo?.fingerprint !== blender.fingerprint) await loadBlender();
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
      applyPose(frames.qpos[0] || null);
      // Blender 뷰를 보는 중이면 그 시간축(재생 위치)·안내는 건드리지 않는다 · 수정 목록 50
      if (view !== 'blender') {
        playhead = 0;
        setMessage(`${fileId} · ${followEndSec(frames).toFixed(1)}초 · ${frames.t.length}프레임 (${frames.hz} Hz)`);
      }
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
      if (playing && hasTimeline()) {
        playhead += dt * speed;
        const end = playEndSec();
        if (playhead > end) {
          playhead = end;
          playing = false;
          renderControls();
        }
        showTime();
        renderTime();
      }
      if (blenderShown()) {
        blender.controls.update();
        renderer.render(blender.scene, blender.camera);
      } else {
        applyActualPose();
        if (controls) controls.update();
        if (renderer && scene3 && camera) renderer.render(scene3, camera);
      }
    };
    rafId = window.requestAnimationFrame(tick);
  }

  function stopLoop() {
    if (rafId) window.cancelAnimationFrame(rafId);
    rafId = 0;
  }

  /** 지금 보는 뷰에 시간축이 있나 · MuJoCo 는 계산 프레임 · Blender 는 glTF 애니메이션 */
  function hasTimeline() {
    return view === 'blender' ? Boolean(blender) : Boolean(frames);
  }

  /** 재생 · 슬라이더 · 길이 표시 모두 애니메이션 길이 · MuJoCo 끝의 정착 3초는 실물에 없다 · 수정 목록 61
   * 꼬리는 계산 결과 파일·CSV(분석)에만 남는다 · `motion_sec` 없는 옛 결과는 전체 길이 */
  function timelineSec() {
    if (view === 'blender') return blender ? blender.duration : 0;
    return frames ? followEndSec(frames) : 0;
  }

  function playEndSec() {
    return timelineSec();
  }

  /** 지금 시각의 자세를 보는 뷰에 */
  function showTime() {
    if (view === 'blender') {
      if (blender) blender.mixer.setTime(Math.min(playhead, blender.duration));
    } else if (frames) {
      applyPose(frames.qpos[frameIndexAt(frames.t, playhead)]);
    }
  }

  function blenderShown() {
    return view === 'blender' && Boolean(blender && renderer);
  }

  function followRealRun() {
    // MuJoCo 뷰 · Blender 뷰 모두 「실물과 같이」 를 따른다 (86)
    const following = follow && (view === 'blender' ? Boolean(blender) : Boolean(frames));
    if (!following) return;
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
    if (!hasTimeline()) return;
    playhead = Math.min(Math.max(seconds, 0), timelineSec());
    showTime();
    renderTime();
  }

  function renderTime() {
    const total = timelineSec();
    if (has('sim3dSlider') && hasTimeline() && document.activeElement !== el.sim3dSlider) {
      el.sim3dSlider.value = String(Math.round((playhead / Math.max(total, 1e-6)) * 1000));
    }
    if (has('sim3dTime')) {
      el.sim3dTime.textContent = hasTimeline()
        ? `${playhead.toFixed(2)} / ${total.toFixed(2)} s`
        : '-- / -- s';
    }
  }

  // ------------------------------------------------------------------ //
  // Blender 뷰 · 수정 목록 50
  // ------------------------------------------------------------------ //

  /** 장면 전체가 보이게 · glTF 는 Y-up · Blender 의 정면(−Y)은 glTF +Z 쪽 */
  function blenderHome(object) {
    const box = new THREE.Box3().setFromObject(object);
    const center = box.isEmpty() ? new THREE.Vector3() : box.getCenter(new THREE.Vector3());
    const size = box.isEmpty() ? 2 : Math.max(box.getSize(new THREE.Vector3()).length(), 0.5);
    return {
      target: center,
      position: center.clone().add(new THREE.Vector3(0, size * 0.15, size * 0.9)),
      near: size / 1000,
      far: size * 20,
    };
  }

  function placeBlenderCamera() {
    if (!blender) return;
    const { home, camera: cam, controls: orbit } = blender;
    cam.position.copy(home.position);
    orbit.target.copy(home.target);
    orbit.update();
  }

  async function loadBlender() {
    if (!blenderInfo?.available || blenderLoading) return;
    if (blender && blender.fingerprint === blenderInfo.fingerprint) return;
    blenderLoading = true;
    renderControls();
    const sizeMb = (Number(blenderInfo.size_bytes) || 0) / 1e6;
    setMessage(`Blender 장면 받는 중 · ${sizeMb.toFixed(1)} MB`);
    try {
      await ensureThree();
      const { GLTFLoader } = await import(GLTF_LOADER_URL);
      ensureRenderer();
      const url = `${BLENDER_SCENE_URL}?v=${encodeURIComponent(blenderInfo.fingerprint || '')}`;
      const gltf = await new GLTFLoader().loadAsync(url);
      disposeBlender();
      const scene = new THREE.Scene();
      scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.2));
      const sun = new THREE.DirectionalLight(0xffffff, 1.6);
      sun.position.set(2, 4, 3);
      scene.add(sun);
      scene.add(gltf.scene);
      const mixer = new THREE.AnimationMixer(gltf.scene);
      let duration = 0;
      for (const clip of gltf.animations || []) {
        const action = mixer.clipAction(clip);
        action.setLoop(THREE.LoopOnce, 1);
        action.clampWhenFinished = true;
        action.play();
        duration = Math.max(duration, clip.duration);
      }
      const home = blenderHome(gltf.scene);
      const cam = new THREE.PerspectiveCamera(40, 1, home.near, home.far);
      const orbit = new OrbitControls(cam, renderer.domElement);
      orbit.enabled = view === 'blender';
      blender = {
        scene, camera: cam, controls: orbit, mixer, duration, home,
        fingerprint: blenderInfo.fingerprint,
      };
      placeBlenderCamera();
      resize();
      playhead = Math.min(playhead, duration);
      showTime();
      startLoop();
      setMessage(`Blender 뷰 · 애니메이션 ${(gltf.animations || []).length}개 · ${duration.toFixed(1)}초 · ${sizeMb.toFixed(1)} MB`);
    } catch (error) {
      setMessage(`Blender 장면 불러오기 실패: ${error?.message || error}`);
      view = 'mujoco';
      if (has('sim3dBlenderToggle')) el.sim3dBlenderToggle.checked = false;
    } finally {
      blenderLoading = false;
      renderControls();
    }
  }

  function disposeBlender() {
    if (!blender) return;
    blender.mixer.stopAllAction();
    blender.controls.dispose();
    blender.scene.traverse((node) => {
      if (node.geometry) node.geometry.dispose();
      const materials = Array.isArray(node.material) ? node.material : (node.material ? [node.material] : []);
      for (const material of materials) {
        for (const value of Object.values(material)) {
          if (value && value.isTexture) value.dispose();
        }
        material.dispose();
      }
    });
    blender = null;
  }

  /** 체크 · 「Blender 뷰」 ↔ 「MuJoCo 계산」 · 같은 캔버스를 바꿔 그린다 */
  /** 지금 보는(같이 보기면 등록) 애니메이션이 glb 에 들어 있을 때만 · 수정 목록 60 */
  function blenderAllowed() {
    return blenderHoldsAnimation(blenderInfo, currentFile);
  }

  async function setView(next) {
    view = next === 'blender' && blenderAllowed() ? 'blender' : 'mujoco';
    playing = false;
    playhead = 0;
    lastRunState = '';                    // 바꾼 뷰가 지금 도는 재생을 곧바로 따라잡게
    if (controls) controls.enabled = view === 'mujoco';
    if (blender) blender.controls.enabled = view === 'blender';
    if (view === 'blender') {
      await loadBlender();
    } else {
      showTime();
      if (frames) setMessage(`${framesFileId} · ${followEndSec(frames).toFixed(1)}초 · MuJoCo 계산`);
    }
    renderControls();
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
    if (has('sim3dBlenderLabel')) {
      el.sim3dBlenderLabel.classList.toggle('hidden', !blenderInfo?.available);
    }
    if (has('sim3dBlenderToggle')) {
      const allowed = blenderAllowed();
      el.sim3dBlenderToggle.checked = view === 'blender';
      el.sim3dBlenderToggle.disabled = blenderLoading || !allowed;
      const why = !(blenderInfo?.animations || []).length
        ? '로봇 팩에 이 장면이 담은 애니메이션 이름이 없어 Blender 뷰를 끕니다 (pack.yaml scene_glb.animations) · MuJoCo 뷰'
        : `이 애니메이션의 Blender 장면 없음 · MuJoCo 뷰 (장면: ${(blenderInfo.animations || []).join(', ')})`;
      const tip = allowed ? 'Blender 에서 구운 장면으로 봅니다' : why;
      el.sim3dBlenderToggle.title = tip;
      if (has('sim3dBlenderLabel')) el.sim3dBlenderLabel.title = tip;
    }
    if (has('sim3dActualToggle')) {
      el.sim3dActualToggle.checked = showActual;
      el.sim3dActualToggle.disabled = view === 'blender' || !ready;
    }
    if (has('sim3dLoadButton')) {
      el.sim3dLoadButton.disabled = view === 'blender' || !ready || !currentFile;
      el.sim3dLoadButton.title = currentFile ? `${currentFile.id} 의 계산 결과를 불러옵니다` : '애니메이션을 먼저 선택하세요';
    }
    if (has('sim3dFollowToggle')) el.sim3dFollowToggle.checked = follow;
    // 실물과 같이 볼 때는 실물이 시계다 · 직접 재생·끌기는 끄고 나서 (86)
    const followTip = '실물과 같이 보는 중 · 직접 재생하려면 「실물과 같이」 를 끄세요';
    if (has('sim3dPlayButton')) {
      el.sim3dPlayButton.disabled = follow || !hasTimeline();
      el.sim3dPlayButton.textContent = follow ? (playing ? '실물 재생 중' : '실물 대기') : (playing ? '일시정지' : '재생');
      el.sim3dPlayButton.title = follow ? followTip : '고른 애니메이션을 직접 재생합니다';
    }
    if (has('sim3dSlider')) {
      el.sim3dSlider.disabled = follow || !hasTimeline();
      el.sim3dSlider.title = follow ? followTip : '재생 위치';
    }
    renderTime();
  }

  function bind() {
    el.sim3dPrepareButton?.addEventListener('click', () => requestExport());
    el.sim3dLoadButton?.addEventListener('click', () => currentFile && loadFrames(currentFile.id));
    el.sim3dFollowToggle?.addEventListener('change', () => setFollow(el.sim3dFollowToggle.checked, followFile));
    el.sim3dPlayButton?.addEventListener('click', () => {
      if (follow || !hasTimeline()) return;
      if (!playing && playhead >= timelineSec()) playhead = 0;
      playing = !playing;
      renderControls();
    });
    el.sim3dSlider?.addEventListener('input', () => {
      if (follow || !hasTimeline()) return;
      seek((Number(el.sim3dSlider.value) / 1000) * timelineSec());
    });
    el.sim3dActualToggle?.addEventListener('change', () => setShowActual(el.sim3dActualToggle.checked));
    el.sim3dBlenderToggle?.addEventListener('change', () => {
      setView(el.sim3dBlenderToggle.checked ? 'blender' : 'mujoco');
    });
    el.sim3dSpeed?.addEventListener('change', () => { speed = Number(el.sim3dSpeed.value) || 1; });
    el.sim3dResetViewButton?.addEventListener('click', () => {
      if (view === 'blender') {
        placeBlenderCamera();
        return;
      }
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
    const state = file?.preview?.state;
    // 계산 실패여도 옛 결과가 있으면 보기는 허용 · 수정 목록 54
    return Boolean(file) && (state === 'ready' || state === 'stale'
      || (state === 'failed' && file.preview?.has_result === true));
  }

  /** 애니메이션 선택이 바뀌었을 때 · 모션 패널이 그릴 때마다 부른다 (싸다)
   *
   * 같이 보기 중에는 재생 등록된 파일을 붙들고 있는다 · 목록에서 다른 파일을
   * 눌러도 바뀌지 않는다 (실물이 재생할 것은 등록 파일이다)
   */
  function update({ file = null, registeredFile = null } = {}) {
    if (registeredFile && registeredFile.id !== followFile?.id) {
      followFile = registeredFile;           // 등록이 바뀌면 그쪽으로 · 끈 동안도 기억해 둔다
    }
    selectedFile = file;
    const target = follow ? (followFile || registeredFile) : file;
    const changed = (target?.id || '') !== (currentFile?.id || '');
    currentFile = target;
    if (changed) {
      frames = null; framesFileId = '';
      if (view !== 'blender') playing = false;
      // 고른 애니메이션이 장면에 없으면 Blender 뷰를 닫고 MuJoCo 로 · 수정 목록 60
      if (view === 'blender' && !blenderAllowed()) {
        setView('mujoco');
        setMessage('이 애니메이션의 Blender 장면이 없어 MuJoCo 뷰로 돌아갑니다');
      }
      if (opened && sceneJson && usable(target)) loadFrames(target.id);
      // 실물과 같이 볼 것이 없으면 왜 안 움직이는지 말한다 (86)
      if (opened && sceneJson && view !== 'blender' && follow) {
        if (!target) setMessage('실물과 같이 · 재생 등록된 애니메이션이 없습니다 · 「실물과 같이」 를 끄면 고른 애니를 직접 봅니다');
        else if (!usable(target)) setMessage(`실물과 같이 · ${target.id} 의 MuJoCo 계산 결과가 없습니다 · 「MuJoCo 계산」 을 누르거나 「실물과 같이」 를 끄세요`);
      }
    }
    renderControls();
  }

  /** 「실물과 같이」 체크 · 켜면 등록 파일을 실물과 같이 · 끄면 고른 파일을 직접 (86) */
  let selectedFile = null;
  async function setFollow(enabled, registeredFile = null) {
    follow = Boolean(enabled);
    lastRunState = '';
    playing = false;
    if (registeredFile) followFile = registeredFile;
    if (follow && opened) await refreshScene();
    update({ file: selectedFile, registeredFile: followFile });
  }

  function destroy() {
    stopLoop();
    if (pollTimer) window.clearTimeout(pollTimer);
    disposeScene();
    disposeBlender();
    if (renderer) { renderer.dispose(); renderer = null; }
    window.removeEventListener('resize', resize);
  }

  bind();
  renderControls();
  return {
    update, setFollow, refreshScene, loadFrames, seek, destroy, setView,
    get frames() { return frames; }, get framesFileId() { return framesFileId; }, get following() { return follow; },
    get view() { return view; },
  };
}
