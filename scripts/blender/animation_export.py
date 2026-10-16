"""Blender 애니메이션 → 로봇 애니메이션 파일 (.json) + 속도·가속·리밋 검사. 로봇 무관.

Blender 에서 Text Editor 로 열고 Run Script → 3D 뷰 사이드바(N) 「Robot」 탭에 버튼 2개:
  속도 검사   파일 안 쓰고 검사만 (아래 마커·곡선·창 그대로) · 저장 안 한 .blend 도 됨
  내보내기    폴더 고르기 창 → 고른 폴더에 출력
Text 블록 「Register」 는 켜지 말 것 (Auto Run 이 켜져 있으면 파일 열 때 실행 · -b 로 열면 바로 내보냄) ·
탭을 늘 띄우려면 Blender 시작 스크립트에서 ANIM_NO_MAIN=True 로 읽고 register() (README).
  <이름>.json                 애니메이션 파일 (JSON Lines) · 헤더 1줄 + [frame, time_sec, id, rad, ...]
                              0.02 s 고정 주기 · rotation_unit "rad" · 이름 = .blend 파일 이름
  report/<이름>_limits.json   조인트별 MotorLimit · 클립 최소/최대 · 첫 프레임 (deg)
  report/<이름>_check.json    속도·가속 초과 구간 · MotorLimit 에 걸린 샘플 (deg)
속도·가속이 한계의 100% 를 넘는 곳이 하나라도 있으면 <이름>.json 을 쓰지 않는다 (리포트·마커만) ·
끝나면 조인트별 최대 % 와 넘은 구간(Blender 프레임)을 창으로 보여 준다.

모터 본 = 커스텀 속성 joint_name 이 있는 포즈 본 (README.md 「본 설정」) · 아마추어 여러 개(로봇 여러 대) 가능
  → 한 파일에 모두 · joint_name 은 전체에서 겹치면 안 됨 · 리포트·검사 곡선 이름은 「리그:본」:
  joint_name      조인트 이름 = 각 로봇 PC 웹 「조인트 매핑」의 조인트 이름과 완전히 같게
  motor_axis      본 로컬 회전축 X / Y / Z
  max_vel_deg_s   관절 최대 속도 (deg/s) · 0 = 검사 안 함
  max_acc_deg_s2  관절 최대 가속도 (deg/s²) · 0 = 검사 안 함
  가동범위 = 본의 Limit Rotation 컨스트레인트 "MotorLimit" (LOCAL)

값 = 컨스트레인트까지 반영한 본 회전 (레스트 기준, 관절 각) · 감속기어비·부호·오프셋은
각 PC 조인트 매핑이 적용 · Blender 안 검사·리포트는 deg, 파일만 rad.
Blender 안: 초과 구간마다 타임라인 마커 "ANIM! ..." (ERR 마커만 선택 상태 = 밝게) · Empty "AnimSpeedCheck" 의
<본>_vel_pct / <본>_acc_pct 곡선 (Graph Editor · 100 = 한계 · 필요한 점만 베지어로, 오차 1%) · ANIM_issue 채널
(키 종류 Extreme = 100% 초과 · Jitter = 80% 이상 · Empty 선택하면 타임라인·도프시트에 보임).
문제 구간을 만든 본 애니메이션 키(앞 키 ~ 뒤 키)도 같은 키 종류로 칠함 → 그 본 선택하면 어느 키 사이인지 보임
(복사 본은 원본 키에 · 다시 검사하면 지난 표시는 일반 키로 되돌림 · 평소 Extreme / Jitter 키 종류는 쓰지 말 것).

exec 전에 둘 수 있는 전역: ARMATURE (오브젝트 이름 또는 이름 목록 · 없으면 joint_name 본이 있는 아마추어 전부) · EXPORT_NAME · OUT_DIR (창 없이 출력).
blender -b 실행도 창 없이 출력 (OUT_DIR 없으면 기본 폴더).
"""

import json
import math
import os
import re

import bpy

PERIOD = 0.02                 # motion_common/timing.py · 50 fps 고정
WARN_RATIO = 0.8              # 한계의 80% 부터 경고 · 100% 초과 오류
ZERO_SNAP_RAD = 1e-6          # 파일 값 · 이보다 작으면 정확히 0 (Blender 행렬 float32 → 키 0 이어도 ~1e-7 rad 잡음)
AXIS_INDEX = {'X': 0, 'Y': 1, 'Z': 2}
MARKER_PREFIX = 'ANIM!'
CHECK_OBJECT = 'AnimSpeedCheck'
ISSUE_PROP = 'ANIM_issue'          # AnimSpeedCheck 의 문제 구간 채널 (키 종류: Extreme = 100% 초과 · Jitter = 80% 이상)
CURVE_TOL = 1.0                    # 검사 곡선(%) 단순화 오차 · 프레임마다 굽지 않음
DIR_PROP = 'anim_export_dir'

BONE_PROPS = {
    'joint_name': ('', '조인트 이름 · 각 로봇 PC 웹 「조인트 매핑」의 조인트 이름과 완전히 같게 '
                       '(애니메이션 파일의 id)'),
    'motor_axis': ('', '이 본이 도는 로컬 축 · X / Y / Z 중 하나'),
    'max_vel_deg_s': (0.0, '관절 최대 속도 (deg/s) · 0 = 검사 안 함\n'
                           '= 모터 최대 rpm × 6 ÷ 감속기어비 (감속기 + 추가 기어·링크까지 합친 전체 비)'),
    'max_acc_deg_s2': (0.0, '관절 최대 가속도 (deg/s²) · 0 = 검사 안 함\n'
                            '= 모터 가속도 (deg/s²) ÷ 감속기어비 (감속기 + 추가 기어·링크까지 합친 전체 비)'),
}


def find_armatures():
    """every armature that has joint_name bones (one .blend may hold several robots) · ARMATURE = name or list"""
    given = globals().get('ARMATURE')
    if given:
        names = [given] if isinstance(given, str) else list(given)
        return [bpy.data.objects[n] for n in names]
    found = [o for o in bpy.data.objects
             if o.type == 'ARMATURE' and any('joint_name' in pb for pb in o.pose.bones)]
    if not found:
        raise RuntimeError('joint_name 속성 본이 있는 아마추어 없음')
    return sorted(found, key=lambda o: o.name)


LABEL_WITH_RIG = False


def label(pb):
    """report / curve name of a bone · 'rig:bone' when the file holds several rigs"""
    return '%s:%s' % (pb.id_data.name, pb.name) if LABEL_WITH_RIG else pb.name


def ensure_bone_props(pb):
    """빠진 속성은 기본값으로 추가 · 모든 속성에 툴팁 (마우스 올리면 설명)."""
    for key, (default, desc) in BONE_PROPS.items():
        if key not in pb:
            pb[key] = default
        ui = pb.id_properties_ui(key)
        if isinstance(default, float):
            ui.update(description=desc, min=0.0, soft_min=0.0)
        else:
            ui.update(description=desc)


def motor_bones(arms):
    bones = [pb for arm in arms for pb in arm.pose.bones if 'joint_name' in pb]
    for pb in bones:
        ensure_bone_props(pb)
    errors = []
    for pb in bones:
        if not str(pb['joint_name']).strip():
            errors.append('%s · joint_name 비어 있음' % label(pb))
        if str(pb['motor_axis']).upper() not in AXIS_INDEX:
            errors.append('%s · motor_axis 는 X / Y / Z 중 하나' % label(pb))
    names = [str(pb['joint_name']).strip() for pb in bones]
    errors += ['joint_name 중복 · %s' % n for n in sorted({n for n in names if n and names.count(n) > 1})]
    if not bones:
        errors.append('joint_name 속성 본 없음')
    if errors:
        raise RuntimeError(' / '.join(errors))
    return bones


def joint_name(pb):
    return str(pb['joint_name']).strip()


def axis(pb):
    return str(pb['motor_axis']).upper()


def export_name(arm):
    name = globals().get('EXPORT_NAME')
    if not name and bpy.data.filepath:
        name = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    if not name:
        action = arm.animation_data.action if arm.animation_data else None
        name = action.name if action else bpy.context.scene.name
    return re.sub(r'[^0-9A-Za-z가-힣_\-]+', '_', name).strip('_') or 'animation'


def local_angle(pb):
    """컨스트레인트 반영 후 레스트 대비 회전 · motor_axis 성분 (deg)."""
    if pb.parent:
        rest = pb.parent.matrix @ pb.parent.bone.matrix_local.inverted() @ pb.bone.matrix_local
    else:
        rest = pb.bone.matrix_local
    euler = (rest.inverted() @ pb.matrix).to_euler('XYZ')
    return math.degrees(euler[AXIS_INDEX[axis(pb)]])


def motor_limit(pb):
    c = pb.constraints.get('MotorLimit')
    if not c:
        return None
    a = axis(pb).lower()
    return math.degrees(getattr(c, 'min_' + a)), math.degrees(getattr(c, 'max_' + a))


def follows_other_bone(pb):
    """다른 본 회전을 복사하는 본 · 자기 키 값은 의미 없음 (MotorLimit 걸림 수 제외)."""
    return any(c.type in {'COPY_ROTATION', 'COPY_TRANSFORMS'} and not c.mute for c in pb.constraints)


def _exclude_others(arms):
    """리그 없는 컬렉션을 잠깐 뺀다 (배경·메쉬까지 프레임마다 계산하면 ~10배 느림).
    빼고 다시 넣으면 Blender 가 오브젝트별 숨김(눈 아이콘)·선택을 지우므로 전부 기록 → _restore 로 되돌림."""
    vl = bpy.context.view_layer
    state = {'objects': {o.name: (o.hide_get(), o.select_get()) for o in vl.objects},
             'active': vl.objects.active.name if vl.objects.active else None, 'lc': [], 'off': []}

    def record(lc):
        for c in lc.children:
            state['lc'].append((c, c.exclude, c.hide_viewport, c.holdout, c.indirect_only))
            record(c)
    record(vl.layer_collection)

    def walk(lc):
        for c in lc.children:
            if c.exclude:
                continue
            if any(o in arms for o in c.collection.all_objects):
                walk(c)
            else:
                state['off'].append(c)
                c.exclude = True
    walk(vl.layer_collection)
    return state


def _restore(state):
    vl = bpy.context.view_layer
    for c in state['off']:
        c.exclude = False
    for c, exc, hid, hold, ind in state['lc']:
        if c.exclude != exc: c.exclude = exc
        if c.hide_viewport != hid: c.hide_viewport = hid
        if c.holdout != hold: c.holdout = hold
        if c.indirect_only != ind: c.indirect_only = ind
    for o in vl.objects:
        st = state['objects'].get(o.name)
        if st is None:
            continue
        if o.hide_get() != st[0]: o.hide_set(st[0])
        if o.select_get() != st[1]: o.select_set(st[1])
    if state['active'] and state['active'] in vl.objects:
        vl.objects.active = vl.objects[state['active']]


def sample(scene, bones):
    arms = {pb.id_data for pb in bones}
    state = _exclude_others(arms)
    try:
        return _sample(scene, bones)
    finally:
        _restore(state)


def _sample(scene, bones):
    fps = scene.render.fps / scene.render.fps_base
    start, end = scene.frame_start, scene.frame_end
    n = int(round((end - start) / fps / PERIOD)) + 1
    keep = scene.frame_current
    frames, values, raw = [], {label(pb): [] for pb in bones}, {label(pb): [] for pb in bones}
    for k in range(n):
        f = start + k * PERIOD * fps
        fi = math.floor(f + 1e-9)
        scene.frame_set(fi, subframe=f - fi)
        frames.append(f)
        for pb in bones:
            values[label(pb)].append(local_angle(pb))
            raw[label(pb)].append(math.degrees(pb.rotation_euler[AXIS_INDEX[axis(pb)]]))
    scene.frame_set(keep)
    return fps, frames, values, raw


def segments(series, limit, warn_ratio):
    """|x|/limit >= warn_ratio 연속 구간 → [(i0, i1, peak_ratio, peak_abs)]."""
    out, cur = [], None
    for i, x in enumerate(series):
        ratio = abs(x) / limit if limit else 0.0
        if ratio >= warn_ratio:
            if cur is None:
                cur = [i, i, ratio, abs(x)]
            else:
                cur[1] = i
                if ratio > cur[2]:
                    cur[2], cur[3] = ratio, abs(x)
        elif cur is not None:
            out.append(tuple(cur))
            cur = None
    if cur is not None:
        out.append(tuple(cur))
    return out


def write_animation(path, title, ids, n):
    header = {'title': title, 'type': 'motion_header', 'rotation_mode': 'relative',
              'rotation_unit': 'rad', 'fields': ['frame', 'time_sec', 'id', 'value'],
              'file_title': title}
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(header, ensure_ascii=False) + '\n')
        for k in range(n):
            row = [k + 1, round((k + 1) * PERIOD, 9)]
            for jid, series in ids:
                v = round(math.radians(series[k]), 9)
                row.extend((jid, 0.0 if abs(v) < ZERO_SNAP_RAD else v + 0.0))
            f.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')


def _key_sources(pb):
    """이 본 값을 정하는 키가 있는 본들 · 다른 본을 복사(Copy Rotation)하면 그 본도 (예: Eye_Yaw_R → Eye_Yaw_L)"""
    out = [pb]
    for c in pb.constraints:
        if c.type in {'COPY_ROTATION', 'COPY_TRANSFORMS'} and not c.mute and c.target == pb.id_data and c.subtarget:
            src = pb.id_data.pose.bones.get(c.subtarget)
            if src is not None:
                out.append(src)
    return out


def _axis_fcurve(pb):
    ad = pb.id_data.animation_data
    act = ad.action if ad else None
    if act is None:
        return None
    dp = 'pose.bones["%s"].rotation_euler' % pb.name
    idx = AXIS_INDEX[axis(pb)]
    for l in act.layers:
        for st in l.strips:
            for cb in st.channelbags:
                if getattr(ad, 'action_slot', None) is not None and cb.slot != ad.action_slot:
                    continue
                fc = cb.fcurves.find(dp, index=idx)
                if fc is not None:
                    return fc
    return None


def mark_keys(bones, flags):
    """문제 구간을 만든 애니메이션 키에 색 · 키 종류 Extreme(빨강) = 100% 초과 · Jitter(분홍) = 80% 이상.
    지난 검사 표시(Extreme / Jitter)는 먼저 일반 키로 되돌림 · 키 사이 구간 = 앞 키 ~ 뒤 키."""
    fcs = {}
    for pb in bones:
        for src in _key_sources(pb):
            fc = _axis_fcurve(src)
            if fc is not None:
                fcs[(src.id_data.name, src.name)] = fc
    for fc in fcs.values():
        for k in fc.keyframe_points:
            if k.type in {'EXTREME', 'JITTER'}:
                k.type = 'KEYFRAME'
    by_label = {label(pb): pb for pb in bones}
    marked = 0
    for fl in sorted(flags, key=lambda f: f['level'] == 'error'):      # 에러가 나중에 칠해져 우선
        pb = by_label.get(fl['bone'])
        if pb is None:
            continue
        f0, f1 = (fl['over_blender_frames'] if fl.get('over_blender_frames') else
                  (fl['blender_frame_from'], fl['blender_frame_to']))
        for src in _key_sources(pb):
            fc = fcs.get((src.id_data.name, src.name))
            if fc is None or not len(fc.keyframe_points):
                continue
            xs = sorted(k.co.x for k in fc.keyframe_points)
            lo = max([x for x in xs if x <= f0 + 2] or [xs[0]])      # ±2 프레임: 20 ms 차분이 구간 끝을 1~2 프레임 늦게 잡음
            hi = min([x for x in xs if x >= f1 - 2] or [xs[-1]])
            if hi <= lo:
                hi = min([x for x in xs if x > lo] or [lo])
            for k in fc.keyframe_points:
                if lo - 1e-6 <= k.co.x <= hi + 1e-6:
                    k.type = 'EXTREME' if fl['level'] == 'error' else 'JITTER'
                    marked += 1
    for fc in fcs.values():
        fc.update()
    return marked


def update_markers(scene, flags):
    """마커는 색을 따로 못 줌 → ERR 마커만 선택 상태로 둬서 밝게 (다른 마커는 선택 해제)."""
    for m in [m for m in scene.timeline_markers if m.name.startswith(MARKER_PREFIX)]:
        scene.timeline_markers.remove(m)
    for m in scene.timeline_markers:
        m.select = False
    for fl in flags:
        tag = 'ERR' if fl['level'] == 'error' else 'warn'
        name = '%s %s %s %s %d%%' % (MARKER_PREFIX, tag, fl['bone'], fl['kind'], round(fl['peak_ratio'] * 100))
        at = fl['over_blender_frames'][0] if fl.get('over_blender_frames') else fl['blender_frame_from']
        m = scene.timeline_markers.new(name, frame=int(math.floor(at)))
        m.select = fl['level'] == 'error'


def _simplify(xs, ys, tol):
    """Ramer–Douglas–Peucker · 남길 인덱스 (처음·끝·꺾이는 점) · 직선에서 tol 이상 벗어나는 점만"""
    n = len(xs)
    if n <= 2:
        return list(range(n))
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        x0, y0, x1, y1 = xs[i0], ys[i0], xs[i1], ys[i1]
        dx = (x1 - x0) or 1e-9
        worst, wi = tol, -1
        for i in range(i0 + 1, i1):
            d = abs(ys[i] - (y0 + (y1 - y0) * (xs[i] - x0) / dx))
            if d > worst:
                worst, wi = d, i
        if wi >= 0:
            keep[wi] = True
            stack.append((i0, wi))
            stack.append((wi, i1))
    return [i for i in range(n) if keep[i]]


def bake_check_curves(scene, arm, bones, frames, vel_pct, acc_pct, flags=()):
    obj = bpy.data.objects.get(CHECK_OBJECT)
    if obj is None:
        obj = bpy.data.objects.new(CHECK_OBJECT, None)
        obj.empty_display_size = 0.05
        col = arm.users_collection[0] if arm.users_collection else scene.collection
        col.objects.link(obj)
    if obj.animation_data and obj.animation_data.action:
        old = obj.animation_data.action
        obj.animation_data.action = None
        if old.users == 0:
            bpy.data.actions.remove(old)
    keys = []
    for pb in bones:
        for key, series in ((label(pb) + '_vel_pct', vel_pct[label(pb)]), (label(pb) + '_acc_pct', acc_pct[label(pb)])):
            obj[key] = 0.0
            obj.keyframe_insert(data_path='["%s"]' % key, frame=frames[0])     # 곡선 만들기 (키 1개)
            keys.append((key, series))
    fcs = {fc.data_path: fc for fc in obj.animation_data.action.fcurves} if hasattr(obj.animation_data.action, 'fcurves')         else {fc.data_path: fc for l in obj.animation_data.action.layers for st in l.strips for cb in st.channelbags for fc in cb.fcurves}
    for key, series in keys:      # 프레임마다 굽지 않고 모양에 필요한 점만 (오차 CURVE_TOL %) · 베지어로 이음
        fc = fcs['["%s"]' % key]
        idx = _simplify(frames, series, CURVE_TOL)
        fc.keyframe_points.clear()
        fc.keyframe_points.add(len(idx))
        co = [0.0] * (2 * len(idx))
        co[0::2] = [frames[i] for i in idx]
        co[1::2] = [float(series[i]) for i in idx]
        fc.keyframe_points.foreach_set('co', co)
        for kp in fc.keyframe_points:
            kp.interpolation = 'BEZIER'
            kp.handle_left_type = kp.handle_right_type = 'AUTO_CLAMPED'
        fc.update()
    # 문제 구간 채널 · 키 색 = 종류 (100% 초과 = Extreme 빨강 · 80% 이상 = Breakdown 파랑) · 값 = 최대 %
    if ISSUE_PROP in obj:
        del obj[ISSUE_PROP]
    pts = {}
    for fl in flags:
        f0, f1 = (fl['over_blender_frames'] if fl.get('over_blender_frames') else
                  (fl['blender_frame_from'], fl['blender_frame_to']))
        err = fl['level'] == 'error'
        for f in (int(math.floor(f0)), int(math.ceil(f1))):
            old = pts.get(f)
            if old is None or (err and not old[1]) or (err == old[1] and fl['peak_ratio'] > old[0]):
                pts[f] = (fl['peak_ratio'], err)
    if pts:
        obj[ISSUE_PROP] = 0.0
        obj.keyframe_insert(data_path='["%s"]' % ISSUE_PROP, frame=min(pts))
        fcs = {fc.data_path: fc for l in obj.animation_data.action.layers for st in l.strips
               for cb in st.channelbags for fc in cb.fcurves}
        fc = fcs['["%s"]' % ISSUE_PROP]
        fc.keyframe_points.clear()
        fc.keyframe_points.add(len(pts))
        for kp, f in zip(fc.keyframe_points, sorted(pts)):
            ratio, err = pts[f]
            kp.co = (f, round(ratio * 100, 1))
            kp.interpolation = 'CONSTANT'
            kp.type = 'EXTREME' if err else 'JITTER'
        fc.update()
    return obj


def default_out_dir():
    last = bpy.context.scene.get(DIR_PROP)
    if last and os.path.isdir(last):
        return last
    return os.path.join(os.path.dirname(bpy.data.filepath), 'export') if bpy.data.filepath else ''


def main(out_dir=None, write=True):
    """write=False → 검사만 (애니메이션 파일·리포트 안 씀 · 마커·검사 곡선·요약은 그대로)"""
    scene = bpy.context.scene
    global LABEL_WITH_RIG
    arms = find_armatures()
    arm = arms[0]
    LABEL_WITH_RIG = len(arms) > 1
    if bpy.context.object and bpy.context.object.mode == 'EDIT':
        bpy.ops.object.mode_set(mode='POSE')
    bones = motor_bones(arms)
    name = export_name(arm)
    chk = bpy.data.objects.get(CHECK_OBJECT)      # 지난 검사 곡선은 읽는 동안 떼어 둠 (프레임마다 같이 계산돼 느려짐)
    if chk and chk.animation_data and chk.animation_data.action:
        old = chk.animation_data.action
        chk.animation_data.action = None
        if old.users == 0:
            bpy.data.actions.remove(old)
    fps, frames, values, raw = sample(scene, bones)
    n = len(frames)
    if abs(fps - 1.0 / PERIOD) > 1e-6:
        print('WARNING: 씬 %.3f fps · 50 아님 → 20 ms 로 재샘플 (50 fps 면 1 프레임 = 1 행)' % fps)
    for pb in bones:   # matrix→euler 잡음 (~1e-6 deg) 이 MotorLimit 을 넘지 않게
        lim = motor_limit(pb)
        if lim:
            values[label(pb)] = [min(max(s, lim[0]), lim[1]) if lim[0] - 1e-4 <= s <= lim[1] + 1e-4 else s
                                 for s in values[label(pb)]]

    out_dir = (out_dir or default_out_dir()) if write else ''
    if write and not out_dir:
        raise RuntimeError('.blend 를 저장하거나 OUT_DIR 지정')
    if write:
        os.makedirs(out_dir, exist_ok=True)
    ids = [(joint_name(pb), values[label(pb)]) for pb in bones]
    path = os.path.join(out_dir, name + '.json')

    flags, axes_report, limits_report = [], [], []
    vel_pct, acc_pct = {}, {}
    for pb in bones:
        x = values[label(pb)]
        jid = joint_name(pb)
        vmax, amax = float(pb['max_vel_deg_s']), float(pb['max_acc_deg_s2'])
        v = [0.0] + [(x[i] - x[i - 1]) / PERIOD for i in range(1, n)]          # 20 ms 차분
        a = [0.0] + [(v[i] - v[i - 1]) / PERIOD for i in range(1, n)]
        vel_pct[label(pb)] = [abs(s) / vmax * 100 if vmax > 0 else 0.0 for s in v]
        acc_pct[label(pb)] = [abs(s) / amax * 100 if amax > 0 else 0.0 for s in a]
        for kind, series, lim in (('velocity', v, vmax), ('acceleration', a, amax)):
            if lim <= 0:
                continue
            for i0, i1, ratio, peak in segments(series, lim, WARN_RATIO):
                over = [i for i in range(i0, i1 + 1) if abs(series[i]) > lim]   # 100% 넘는 샘플만
                flags.append({'bone': label(pb), 'joint_name': jid, 'kind': kind,
                              'level': 'error' if ratio > 1.0 else 'warn',
                              'file_frame_from': i0 + 1, 'file_frame_to': i1 + 1,
                              'blender_frame_from': round(frames[max(i0 - 1, 0)], 3),
                              'blender_frame_to': round(frames[i1], 3),
                              'peak': round(peak, 3), 'limit': round(lim, 3),
                              'peak_ratio': round(ratio, 3),
                              'over_blender_frames': [round(frames[max(over[0] - 1, 0)], 3),
                                                      round(frames[over[-1]], 3)] if over else None})

        lim = motor_limit(pb)
        clamped = 0
        if lim and not follows_other_bone(pb):
            clamped = sum(1 for r in raw[label(pb)] if r < lim[0] - 1e-6 or r > lim[1] + 1e-6)
        limits_report.append({'bone': label(pb), 'joint_name': jid,
                              'blender_limit_deg': [round(d, 3) for d in lim] if lim else None,
                              'clip_min_deg': round(min(x), 3), 'clip_max_deg': round(max(x), 3),
                              'first_frame_deg': round(x[0], 3)})
        axes_report.append({
            'bone': label(pb), 'joint_name': jid,
            'vel_limit_deg_s': round(vmax, 3) if vmax > 0 else None,
            'acc_limit_deg_s2': round(amax, 3) if amax > 0 else None,
            'clip_peak_vel_deg_s': round(max(abs(s) for s in v), 3),
            'clip_peak_acc_deg_s2': round(max(abs(s) for s in a), 3),
            'peak_vel_pct': round(max(vel_pct[label(pb)]), 1) if vmax > 0 else None,
            'peak_acc_pct': round(max(acc_pct[label(pb)]), 1) if amax > 0 else None,
            'clamped_by_MotorLimit_samples': clamped,
            'start_end_diff_deg': round(abs(x[-1] - x[0]), 3)})

    unchecked = [ax['bone'] for ax in axes_report if ax['vel_limit_deg_s'] is None or ax['acc_limit_deg_s2'] is None]
    check = {'animation_file': os.path.basename(path), 'samples': n, 'period_sec': PERIOD,
             'blender_fps': fps, 'blender_frames': [scene.frame_start, scene.frame_end],
             'warn_ratio': WARN_RATIO,
             'errors': sum(1 for f in flags if f['level'] == 'error'),
             'warnings': sum(1 for f in flags if f['level'] == 'warn'),
             'not_checked': unchecked,
             'axes': axes_report, 'segments': flags}
    check['exported'] = write and check['errors'] == 0      # 100% 넘는 곳이 있으면 애니메이션 파일을 쓰지 않는다
    if check['exported']:
        write_animation(path, name, ids, n)
    if write:
        report_dir = os.path.join(out_dir, 'report')
        os.makedirs(report_dir, exist_ok=True)
        base = os.path.join(report_dir, name)
        with open(base + '_limits.json', 'w', encoding='utf-8') as f:
            json.dump(limits_report, f, ensure_ascii=False, indent=1)
        with open(base + '_check.json', 'w', encoding='utf-8') as f:
            json.dump(check, f, ensure_ascii=False, indent=1)

    update_markers(scene, flags)
    mark_keys(bones, flags)
    bake_check_curves(scene, arm, bones, frames, vel_pct, acc_pct, flags)

    print(('exported' if check['exported'] else 'NOT exported (100% 초과)') if write else 'check only (파일 안 씀)',
          path if write else name, '| samples', n, '| ids', [i for i, _ in ids])
    for line in summary_lines(check):
        print('  ' + line)
    for ax in axes_report:
        print('  %-12s %-12s peak %8.2f deg/s of %8s | acc %10.1f of %10s | clamp %d' % (
            ax['bone'], ax['joint_name'], ax['clip_peak_vel_deg_s'], ax['vel_limit_deg_s'] or '-',
            ax['clip_peak_acc_deg_s2'], ax['acc_limit_deg_s2'] or '-', ax['clamped_by_MotorLimit_samples']))
    if unchecked:
        print('  검사 안 함 (max_vel_deg_s / max_acc_deg_s2 = 0):', ', '.join(unchecked))
    print('  errors %d, warnings %d' % (check['errors'], check['warnings']))
    for fl in flags:
        print('   %-5s %-12s %-12s file frames %d-%d  blender %.1f-%.1f  peak %.1f / %.1f (%d%%)' % (
            fl['level'], fl['bone'], fl['kind'], fl['file_frame_from'], fl['file_frame_to'],
            fl['blender_frame_from'], fl['blender_frame_to'], fl['peak'], fl['limit'], round(fl['peak_ratio'] * 100)))
    return check


def summary_lines(check):
    """조인트별 최대 % · 100% 넘는 구간 (Blender 프레임) · 끝나면 창으로 보여 준다."""
    pct = lambda p: '-' if p is None else '%.0f%%' % p
    lines = ['%s  속도 %s · 가속 %s' % (ax['bone'], pct(ax['peak_vel_pct']), pct(ax['peak_acc_pct']))
             for ax in check['axes']]
    for fl in check['segments']:
        if fl['level'] == 'error':
            f0, f1 = fl['over_blender_frames']
            lines.append('너무 빠름  %s %s %d%% · 프레임 %.0f–%.0f' % (
                fl['bone'], '속도' if fl['kind'] == 'velocity' else '가속', round(fl['peak_ratio'] * 100), f0, f1))
    if check['not_checked']:
        lines.append('검사 안 함 (한계 0): ' + ', '.join(check['not_checked']))
    return lines


class ROBOT_OT_animation_export(bpy.types.Operator):
    """출력 폴더 고르기 → 애니메이션 내보내기"""
    bl_idname = 'robot.animation_export'
    bl_label = 'Export here'

    directory: bpy.props.StringProperty(subtype='DIR_PATH')
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, context, event):
        self.directory = default_out_dir()
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        out_dir = bpy.path.abspath(self.directory)
        try:
            check = main(out_dir)
        except Exception as exc:
            self.report({'ERROR'}, '내보내기 실패: %s' % exc)
            raise
        context.scene[DIR_PROP] = out_dir
        lines = summary_lines(check)
        if check['exported']:
            title = '내보내기 완료 · 경고 %d' % check['warnings']
            self.report({'WARNING'} if check['warnings'] or check['not_checked'] else {'INFO'},
                        '내보내기 → %s | warnings %d' % (out_dir, check['warnings']))
        else:
            title = '추출 안 함 · 100%% 넘는 구간 %d곳 (타임라인 ANIM! ERR)' % check['errors']
            self.report({'ERROR'}, title)

        def draw(menu, _context):
            for line in lines:
                menu.layout.label(text=line)

        context.window_manager.popup_menu(draw, title=title, icon='INFO' if check['exported'] else 'ERROR')
        return {'FINISHED'}


class ROBOT_OT_animation_check(bpy.types.Operator):
    """파일 안 쓰고 속도·가속·리밋 검사만 (마커 ANIM! · AnimSpeedCheck 곡선 · 요약 창)"""
    bl_idname = 'robot.animation_check'
    bl_label = '속도 검사'

    def execute(self, context):
        try:
            check = main(write=False)
        except Exception as exc:
            self.report({'ERROR'}, '검사 실패: %s' % exc)
            raise
        lines = summary_lines(check)
        if check['errors']:
            title = '100%% 넘는 구간 %d곳 · 경고 %d (타임라인 ANIM!)' % (check['errors'], check['warnings'])
            self.report({'ERROR'}, title)
        else:
            title = '통과 · 경고 %d (80%% 이상)' % check['warnings']
            self.report({'WARNING'} if check['warnings'] else {'INFO'}, title)

        def draw(menu, _context):
            for line in lines:
                menu.layout.label(text=line)

        context.window_manager.popup_menu(draw, title=title, icon='ERROR' if check['errors'] else 'INFO')
        return {'FINISHED'}


class ROBOT_PT_animation(bpy.types.Panel):
    bl_label = '애니메이션 검사 · 내보내기'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Robot'

    def draw(self, context):
        col = self.layout.column(align=True)
        col.scale_y = 1.4
        col.operator(ROBOT_OT_animation_check.bl_idname, icon='VIEWZOOM')
        col.operator(ROBOT_OT_animation_export.bl_idname, text='내보내기', icon='EXPORT')
        self.layout.label(text='50 fps · 80% 경고 · 100% 넘으면 안 내보냄')


CLASSES = (ROBOT_OT_animation_export, ROBOT_OT_animation_check, ROBOT_PT_animation)


def register():
    for cls in CLASSES:      # 스크립트 재실행 → 이 버전으로 다시 등록
        old = getattr(bpy.types, cls.__name__, None)
        if old is not None:
            bpy.utils.unregister_class(old)
        bpy.utils.register_class(cls)


def run():
    given = globals().get('OUT_DIR')
    if given or bpy.app.background:
        return main(given)
    register()
    print('3D 뷰 사이드바(N) 「Robot」 탭 → 속도 검사 / 내보내기')


if not globals().get('ANIM_NO_MAIN'):
    if __name__ == '__main__':
        run()
    else:                    # Text 「Register」 로 파일 열 때 실행 → 탭만 등록
        register()
