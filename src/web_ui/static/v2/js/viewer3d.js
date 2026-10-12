/** UI v2 · 공연 3D · 실물 재생과 같이 · MuJoCo 계산 뷰 · Blender 뷰 (설계안 2026-10-09)
 *
 * 화면 코드는 새로 · 계산(정기구학 · 실물 시계 · json 값 → 노드 회전)은 기존 화면과 **같은 함수**
 * (`static/js/sim3d_math.js` · 순수 계산)를 쓴다 · 두 화면이 같은 시각에 같은 자세를 보이게(수정 목록 92 · 98).
 *
 * 칸(node)은 한 번 만들고 계속 같은 것을 끼운다 · 페이지가 0.5초마다 다시 그려도 WebGL 은 그대로.
 * 보이는 동안만 그린다(requestAnimationFrame) · 칸이 화면에서 빠지면 멈춘다.
 */
import { h } from './dom.js';
import { api } from './net.js';
import {
  blenderUsesJoints, blenderViewAllowed, bodyLocalPose, cameraPosition, followEndSec, followPlayheadSec,
  frameIndexAt, jointNodeRotation, jointsByBody, nextClockOffset, sampleJointValues,
} from '../../js/sim3d_math.js';

const THREE_URL = '/static/vendor/three/three.module.js';
const CONTROLS_URL = '/static/vendor/three/OrbitControls.js';
const GLTF_URL = '/static/vendor/three/GLTFLoader.js';
const VIEW_KEY = 'robot_web.v2.view3d';
const SCENE_RECHECK_MS = 10000;

let THREE = null;
let OrbitControls = null;
let viewer = null;

export function getViewer3d() {
  if (!viewer) viewer = createViewer3d();
  return viewer;
}

function createViewer3d() {
  const status = h('span', { class: 'muted small grow', text: '3D 준비 중' });
  const timeLabel = h('span', { class: 'mono muted small', text: '' });
  const viewButtons = {
    mujoco: h('button', { class: 'seg', type: 'button', 'aria-pressed': 'true', onclick: () => setView('mujoco') }, 'MuJoCo'),
    blender: h('button', { class: 'seg', type: 'button', 'aria-pressed': 'false', onclick: () => setView('blender') }, 'Blender'),
  };
  const canvasWrap = h('div', { class: 'view3d-canvas' });
  const node = h('div', { class: 'view3d' },
    h('div', { class: 'row view3d-bar' },
      h('div', { class: 'segmented', role: 'group', 'aria-label': '3D 보기' }, viewButtons.mujoco, viewButtons.blender),
      status, timeLabel),
    canvasWrap);

  let view = 'mujoco';
  try { if (localStorage.getItem(VIEW_KEY) === 'blender') view = 'blender'; } catch { /* 기본 */ }
  let renderer = null;
  let sceneInfo = null;
  let sceneCheckedAt = 0;
  let exportAsked = false;
  // MuJoCo
  let mj = null;               // {json, scene, camera, controls, groups, joints}
  let frames = null;
  let framesFor = '';
  let framesLoading = '';
  let framesFailedAt = 0;      // 계산 결과가 없으면 15초마다 다시 본다(그사이 계산이 끝날 수 있다)
  // Blender
  let bl = null;               // {scene, camera, controls, mixer, duration, rig, jointMode, fingerprint}
  let blLoading = false;
  let values = null;
  let valuesFor = '';
  let valuesLoading = '';
  // 시계 · 상태
  let clock = { samples: [], offset: 0 };
  let lastServerTime = 0;
  let latest = { status: {}, fileId: '' };
  let raf = 0;

  function say(text) { if (status.textContent !== text) status.textContent = text; }

  async function ensureThree() {
    if (THREE) return;
    THREE = await import(THREE_URL);
    ({ OrbitControls } = await import(CONTROLS_URL));
  }

  function ensureRenderer() {
    if (renderer) return;
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    canvasWrap.append(renderer.domElement);
    if (globalThis.ResizeObserver) new ResizeObserver(resize).observe(canvasWrap);
  }

  function resize() {
    if (!renderer) return;
    const width = Math.max(canvasWrap.clientWidth, 200);
    const height = Math.max(canvasWrap.clientHeight, 240);
    renderer.setSize(width, height, false);
    for (const cam of [mj?.camera, bl?.camera]) {
      if (cam) { cam.aspect = width / height; cam.updateProjectionMatrix(); }
    }
  }

  /* ---------- MuJoCo ---------- */

  function quat(q) { return new THREE.Quaternion(q[1], q[2], q[3], q[0]); }

  function geomMesh(geom, meshes) {
    const rgba = geom.rgba || [0.6, 0.6, 0.6, 1];
    const material = new THREE.MeshStandardMaterial({
      color: new THREE.Color(rgba[0], rgba[1], rgba[2]), transparent: rgba[3] < 1, opacity: rgba[3],
      metalness: 0.1, roughness: 0.7, side: THREE.DoubleSide,
    });
    const [sx, sy, sz] = geom.size;
    let geometry = null;
    if (geom.type === 'box') geometry = new THREE.BoxGeometry(sx * 2, sy * 2, sz * 2);
    else if (geom.type === 'sphere') geometry = new THREE.SphereGeometry(sx, 24, 16);
    else if (geom.type === 'ellipsoid') geometry = new THREE.SphereGeometry(1, 24, 16);
    else if (geom.type === 'capsule') geometry = new THREE.CapsuleGeometry(sx, sy * 2, 6, 16);
    else if (geom.type === 'cylinder') geometry = new THREE.CylinderGeometry(sx, sx, sy * 2, 24);
    else if (geom.type === 'plane') {
      geometry = new THREE.PlaneGeometry(sx > 0 ? sx * 2 : 20, sy > 0 ? sy * 2 : 20);
      material.transparent = true;
      material.opacity = Math.min(material.opacity, 0.35);
    } else if (geom.type === 'mesh') {
      const data = meshes[geom.mesh];
      if (!data) return null;
      geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(data.vertices, 3));
      geometry.setIndex(data.faces);
      geometry.computeVertexNormals();
    } else return null;
    const mesh = new THREE.Mesh(geometry, material);
    // MuJoCo 캡슐·원기둥은 z 축 · three.js 는 y 축
    const q = quat(geom.quat || [1, 0, 0, 0]);
    if (geom.type === 'capsule' || geom.type === 'cylinder') q.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2));
    if (geom.type === 'ellipsoid') mesh.scale.set(sx, sy, sz);
    mesh.quaternion.copy(q);
    mesh.position.set(geom.pos[0], geom.pos[1], geom.pos[2]);
    return mesh;
  }

  async function loadMujoco() {
    if (mj) return;
    const data = await api('GET', '/api/preview/scene/data', { timeoutMs: 60000 });
    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 1.1));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(1.5, -2.0, 3.0);
    scene.add(sun);
    const grid = new THREE.GridHelper(4, 20, 0x5aa2ff, 0x3a4652);
    grid.rotation.x = Math.PI / 2;
    scene.add(grid);
    const groups = data.bodies.map((body) => { const g = new THREE.Group(); g.name = body.name; return g; });
    data.bodies.forEach((body, i) => { if (body.parent < 0) scene.add(groups[i]); else groups[body.parent].add(groups[i]); });
    for (const geom of data.geoms) {
      if (geom.group >= 3) continue;
      const mesh = geomMesh(geom, data.meshes || {});
      if (mesh) groups[geom.body].add(mesh);
    }
    const cam = data.camera || {};
    const position = cameraPosition(cam);
    const lookat = cam.lookat || [0, 0, 0];
    const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 100);
    camera.up.set(0, 0, 1);
    camera.position.set(...position);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(...lookat);
    controls.update();
    mj = { json: data, scene, camera, controls, groups, joints: jointsByBody(data) };
    poseMujoco(null);
    resize();
  }

  function poseMujoco(qpos) {
    if (!mj) return;
    for (const body of mj.json.bodies) {
      if (body.parent < 0) continue;
      const local = bodyLocalPose(body, mj.joints.get(body.id), qpos);
      mj.groups[body.id].position.set(...local.pos);
      mj.groups[body.id].quaternion.copy(quat(local.quat));
    }
  }

  async function loadFrames(fileId) {
    if (!fileId || framesLoading === fileId) return;
    if (framesFor === fileId && (frames || Date.now() - framesFailedAt < 15000)) return;
    framesLoading = fileId;
    try {
      const payload = await api('GET', `/api/motion-files/${encodeURIComponent(fileId)}/preview-frames`, { timeoutMs: 60000 });
      // 모양이 맞아야 쓴다(시각 · 자세 줄이 있고 같은 길이)
      if (!Array.isArray(payload?.t) || !Array.isArray(payload?.qpos) || !payload.t.length || payload.t.length !== payload.qpos.length) {
        throw new Error(payload?.message || '계산 결과 형식이 맞지 않습니다');
      }
      frames = payload;
      framesFor = fileId;
    } catch (error) {
      frames = null;
      framesFor = fileId;
      framesFailedAt = Date.now();
      say(`${fileId} · MuJoCo 계산 결과가 없습니다. 애니메이션 화면에서 「3D 계산 시작」을 누르세요 (${error.message})`);
    } finally {
      framesLoading = '';
    }
  }

  /* ---------- Blender ---------- */

  async function loadBlender() {
    const info = sceneInfo?.blender;
    if (!info?.available || blLoading || (bl && bl.fingerprint === info.fingerprint)) return;
    blLoading = true;
    say(`Blender 장면 다운로드 중 · ${((Number(info.size_bytes) || 0) / 1e6).toFixed(1)} MB`);
    try {
      const { GLTFLoader } = await import(GLTF_URL);
      const gltf = await new GLTFLoader().loadAsync(`/api/preview/blender-scene?v=${encodeURIComponent(info.fingerprint || '')}`);
      const scene = new THREE.Scene();
      scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.2));
      const sun = new THREE.DirectionalLight(0xffffff, 1.6);
      sun.position.set(2, 4, 3);
      scene.add(sun);
      scene.add(gltf.scene);
      const jointMode = blenderUsesJoints(info);
      const mixer = new THREE.AnimationMixer(gltf.scene);
      let duration = 0;
      const rig = [];
      if (jointMode) {
        for (const [name, entry] of Object.entries(info.joints || {})) {
          const target = gltf.scene.getObjectByName(entry.node) || gltf.scene.getObjectByName(THREE.PropertyBinding.sanitizeNodeName(entry.node));
          if (target) rig.push({ name, node: target, axis: entry.axis, base: [target.quaternion.x, target.quaternion.y, target.quaternion.z, target.quaternion.w] });
        }
      } else {
        for (const clip of gltf.animations || []) {
          const action = mixer.clipAction(clip);
          action.setLoop(THREE.LoopOnce, 1);
          action.clampWhenFinished = true;
          action.play();
          duration = Math.max(duration, clip.duration);
        }
      }
      // 장면 전체가 보이게 · glTF 는 Y-up · 정면은 +Z
      const box = new THREE.Box3().setFromObject(gltf.scene);
      const center = box.getCenter(new THREE.Vector3());
      const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.5);
      const camera = new THREE.PerspectiveCamera(40, 1, radius / 100, radius * 50);
      camera.position.set(center.x, center.y + radius * 0.3, center.z + radius * 2.4);
      const controls = new OrbitControls(camera, renderer.domElement);
      controls.target.copy(center);
      controls.update();
      bl = { scene, camera, controls, mixer, duration, rig, jointMode, fingerprint: info.fingerprint };
      resize();
    } catch (error) {
      say(`Blender 장면 불러오기 실패 · ${error.message || error}`);
    } finally {
      blLoading = false;
    }
  }

  async function loadValues(fileId) {
    if (!bl?.jointMode || !fileId || valuesFor === fileId || valuesLoading === fileId) return;
    valuesLoading = fileId;
    try {
      values = await api('GET', `/api/motion-files/${encodeURIComponent(fileId)}/joint-values`, { timeoutMs: 30000 });
      valuesFor = fileId;
    } catch (error) {
      values = null;
      valuesFor = fileId;
      say(`${fileId} · 값을 받지 못함 · ${error.message}`);
    } finally {
      valuesLoading = '';
    }
  }

  function poseBlender(seconds, fileId) {
    if (!bl) return;
    if (bl.jointMode) {
      const sample = values && valuesFor === fileId ? sampleJointValues(values, seconds) : {};
      for (const joint of bl.rig) {
        const [x, y, z, w] = jointNodeRotation(joint.base, joint.axis, sample, joint.name);
        joint.node.quaternion.set(x, y, z, w);
      }
    } else {
      bl.mixer.setTime(Math.min(seconds, bl.duration));
    }
  }

  /* ---------- 고르기 · 그리기 ---------- */

  function blenderAllowed() {
    return blenderViewAllowed(sceneInfo?.blender, latest.fileId ? { id: latest.fileId } : null);
  }

  function setView(next) {
    view = next;
    try { localStorage.setItem(VIEW_KEY, next); } catch { /* 기억 못 해도 된다 */ }
    paintButtons();
    prepare();
  }

  function paintButtons() {
    const allowed = blenderAllowed();
    viewButtons.blender.disabled = !sceneInfo?.blender?.available;
    viewButtons.blender.title = !sceneInfo?.blender?.available ? '로봇 팩에 Blender 장면(scene.glb)이 없습니다'
      : allowed ? '' : '이 애니메이션은 Blender 장면에 없습니다(이전 버전 팩)';
    const shown = view === 'blender' && allowed ? 'blender' : 'mujoco';
    viewButtons.mujoco.setAttribute('aria-pressed', String(shown === 'mujoco'));
    viewButtons.blender.setAttribute('aria-pressed', String(shown === 'blender'));
  }

  async function prepare() {
    try {
      await ensureThree();
      ensureRenderer();
      if (!sceneInfo || Date.now() - sceneCheckedAt > SCENE_RECHECK_MS) {
        sceneInfo = await api('GET', '/api/preview/scene');
        sceneCheckedAt = Date.now();
      }
      paintButtons();
      if (view === 'blender' && blenderAllowed()) {
        await loadBlender();
        await loadValues(latest.fileId);
      } else if (sceneInfo.state === 'ready') {
        await loadMujoco();
        await loadFrames(latest.fileId);
      } else if (sceneInfo.state === 'missing' && !exportAsked) {
        exportAsked = true;
        await api('POST', '/api/preview/scene/export').catch(() => null);
        say('3D 장면을 처음 만드는 중 · 몇 초 걸립니다');
      } else if (sceneInfo.state !== 'ready') {
        say(sceneInfo.message || (sceneInfo.state === 'unavailable' ? '로봇 팩이 없어 3D를 표시할 수 없습니다' : `3D 장면 · ${sceneInfo.state}`));
      }
    } catch (error) {
      say(`3D 준비 실패 · ${error.message || error}`);
    }
  }

  function frame() {
    raf = 0;
    if (!node.isConnected) return;   // 화면에서 빠지면 멈춘다 · 다시 붙으면 update 가 깨운다
    const st = latest.status || {};
    const running = String(st.state || '') === 'running';
    const playhead = followPlayheadSec(st, Date.now() / 1000, clock.offset) ?? 0;
    const blenderShown = view === 'blender' && blenderAllowed() && bl;
    let duration = 0;
    if (blenderShown) {
      duration = bl.jointMode ? Number(values?.duration_sec) || 0 : bl.duration;
      poseBlender(Math.min(playhead, duration || playhead), latest.fileId);
      bl.controls.update();
      renderer.render(bl.scene, bl.camera);
      say(`Blender · ${latest.fileId || '애니메이션 없음'}${bl.jointMode ? ' · json 값' : ' · 구운 장면'}${running ? ' · 동시 재생 중' : ' · 대기 상태(초기 위치)'}`);
    } else if (mj) {
      const ok = frames && framesFor === latest.fileId;
      duration = ok ? followEndSec(frames) : 0;
      poseMujoco(ok ? frames.qpos[frameIndexAt(frames.t, Math.min(playhead, duration))] : null);
      mj.controls.update();
      renderer.render(mj.scene, mj.camera);
      if (ok) say(`MuJoCo · ${latest.fileId}${running ? ' · 동시 재생 중' : ' · 대기 상태(초기 위치)'}`);
    }
    timeLabel.textContent = duration ? `${Math.min(playhead, duration).toFixed(1)} / ${duration.toFixed(1)} s` : '';
    raf = requestAnimationFrame(frame);
  }

  /** 페이지가 그릴 때마다 · 상태와 볼 애니메이션만 넘긴다(싸다) */
  function update(state, { fileId = '' } = {}) {
    const snap = state.snap || {};
    latest = { status: snap.motion_run_status || snap.motion_state?.motion_run_status || {}, fileId };
    const serverTime = Number(snap.server_time);
    if (serverTime && serverTime !== lastServerTime) {
      lastServerTime = serverTime;
      clock = nextClockOffset(clock.samples, serverTime, Date.now() / 1000);
    }
    if ((fileId && fileId !== framesFor && fileId !== valuesFor) || !sceneInfo || Date.now() - sceneCheckedAt > SCENE_RECHECK_MS) prepare();
    if (!raf) raf = requestAnimationFrame(frame);
    return node;
  }

  return { node, update };
}
