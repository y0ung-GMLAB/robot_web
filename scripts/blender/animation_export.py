"""Blender 애니메이션 → 로봇 애니메이션 파일 (.json) + 속도·가속·리밋 검사. 로봇 무관.

Blender 에서 Text Editor 로 열고 Run Script. 폴더 고르기 창 → 고른 폴더에 출력.
  <이름>.json                 애니메이션 파일 (JSON Lines) · 헤더 1줄 + [frame, time_sec, id, rad, ...]
                              0.02 s 고정 주기 · rotation_unit "rad" · 이름 = .blend 파일 이름
  report/<이름>_limits.json   조인트별 MotorLimit · 클립 최소/최대 · 첫 프레임 (deg)
  report/<이름>_check.json    속도·가속 초과 구간 · MotorLimit 에 걸린 샘플 (deg)

모터 본 = 커스텀 속성 joint_name 이 있는 포즈 본 (README.md 「본 설정」):
  joint_name      조인트 이름 = 각 로봇 PC 웹 「조인트 매핑」의 조인트 이름과 완전히 같게
  motor_axis      본 로컬 회전축 X / Y / Z
  max_vel_deg_s   관절 최대 속도 (deg/s) · 0 = 검사 안 함
  max_acc_deg_s2  관절 최대 가속도 (deg/s²) · 0 = 검사 안 함
  가동범위 = 본의 Limit Rotation 컨스트레인트 "MotorLimit" (LOCAL)

값 = 컨스트레인트까지 반영한 본 회전 (레스트 기준, 관절 각) · 감속기어비·부호·오프셋은
각 PC 조인트 매핑이 적용 · Blender 안 검사·리포트는 deg, 파일만 rad.
Blender 안: 초과 구간마다 타임라인 마커 "ANIM! ..." · Empty "AnimSpeedCheck" 의
<본>_vel_pct / <본>_acc_pct 곡선 (Graph Editor · 100 = 한계).

exec 전에 둘 수 있는 전역: ARMATURE (오브젝트 이름) · EXPORT_NAME · OUT_DIR (창 없이 출력).
blender -b 실행도 창 없이 출력 (OUT_DIR 없으면 기본 폴더).
"""

import json
import math
import os
import re

import bpy

PERIOD = 0.02                 # motion_common/timing.py · 50 fps 고정
WARN_RATIO = 0.8              # 한계의 80% 부터 경고 · 100% 초과 오류
AXIS_INDEX = {'X': 0, 'Y': 1, 'Z': 2}
MARKER_PREFIX = 'ANIM!'
CHECK_OBJECT = 'AnimSpeedCheck'
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


def find_armature():
    name = globals().get('ARMATURE')
    if name:
        return bpy.data.objects[name]
    obj = bpy.context.object
    if obj and obj.type == 'ARMATURE' and any('joint_name' in pb for pb in obj.pose.bones):
        return obj
    found = [o for o in bpy.data.objects
             if o.type == 'ARMATURE' and any('joint_name' in pb for pb in o.pose.bones)]
    if len(found) != 1:
        raise RuntimeError('joint_name 속성 본이 있는 아마추어 %d개 · 대상을 선택하거나 ARMATURE 지정'
                           % len(found))
    return found[0]


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


def motor_bones(arm):
    bones = [pb for pb in arm.pose.bones if 'joint_name' in pb]
    for pb in bones:
        ensure_bone_props(pb)
    errors = []
    for pb in bones:
        if not str(pb['joint_name']).strip():
            errors.append('%s · joint_name 비어 있음' % pb.name)
        if str(pb['motor_axis']).upper() not in AXIS_INDEX:
            errors.append('%s · motor_axis 는 X / Y / Z 중 하나' % pb.name)
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


def sample(scene, bones):
    fps = scene.render.fps / scene.render.fps_base
    start, end = scene.frame_start, scene.frame_end
    n = int(round((end - start) / fps / PERIOD)) + 1
    keep = scene.frame_current
    frames, values, raw = [], {pb.name: [] for pb in bones}, {pb.name: [] for pb in bones}
    for k in range(n):
        f = start + k * PERIOD * fps
        fi = math.floor(f + 1e-9)
        scene.frame_set(fi, subframe=f - fi)
        frames.append(f)
        for pb in bones:
            values[pb.name].append(local_angle(pb))
            raw[pb.name].append(math.degrees(pb.rotation_euler[AXIS_INDEX[axis(pb)]]))
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
                row.extend((jid, round(math.radians(series[k]), 9) + 0.0))
            f.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')


def update_markers(scene, flags):
    for m in [m for m in scene.timeline_markers if m.name.startswith(MARKER_PREFIX)]:
        scene.timeline_markers.remove(m)
    for fl in flags:
        tag = 'ERR' if fl['level'] == 'error' else 'warn'
        name = '%s %s %s %s %d%%' % (MARKER_PREFIX, tag, fl['bone'], fl['kind'], round(fl['peak_ratio'] * 100))
        scene.timeline_markers.new(name, frame=int(math.floor(fl['blender_frame_from'])))


def bake_check_curves(scene, arm, bones, frames, vel_pct, acc_pct):
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
    for pb in bones:
        for key, series in ((pb.name + '_vel_pct', vel_pct[pb.name]), (pb.name + '_acc_pct', acc_pct[pb.name])):
            obj[key] = 0.0
            for f, v in zip(frames, series):
                obj[key] = float(v)
                obj.keyframe_insert(data_path='["%s"]' % key, frame=f)
    return obj


def default_out_dir():
    last = bpy.context.scene.get(DIR_PROP)
    if last and os.path.isdir(last):
        return last
    return os.path.join(os.path.dirname(bpy.data.filepath), 'export') if bpy.data.filepath else ''


def main(out_dir=None):
    scene = bpy.context.scene
    arm = find_armature()
    if bpy.context.object and bpy.context.object.mode == 'EDIT':
        bpy.ops.object.mode_set(mode='POSE')
    bones = motor_bones(arm)
    name = export_name(arm)
    fps, frames, values, raw = sample(scene, bones)
    n = len(frames)
    if abs(fps - 1.0 / PERIOD) > 1e-6:
        print('WARNING: 씬 %.3f fps · 50 아님 → 20 ms 로 재샘플 (50 fps 면 1 프레임 = 1 행)' % fps)
    for pb in bones:   # matrix→euler 잡음 (~1e-6 deg) 이 MotorLimit 을 넘지 않게
        lim = motor_limit(pb)
        if lim:
            values[pb.name] = [min(max(s, lim[0]), lim[1]) if lim[0] - 1e-4 <= s <= lim[1] + 1e-4 else s
                               for s in values[pb.name]]

    out_dir = out_dir or default_out_dir()
    if not out_dir:
        raise RuntimeError('.blend 를 저장하거나 OUT_DIR 지정')
    os.makedirs(out_dir, exist_ok=True)
    ids = [(joint_name(pb), values[pb.name]) for pb in bones]
    path = os.path.join(out_dir, name + '.json')
    write_animation(path, name, ids, n)

    flags, axes_report, limits_report = [], [], []
    vel_pct, acc_pct = {}, {}
    for pb in bones:
        x = values[pb.name]
        jid = joint_name(pb)
        vmax, amax = float(pb['max_vel_deg_s']), float(pb['max_acc_deg_s2'])
        v = [0.0] + [(x[i] - x[i - 1]) / PERIOD for i in range(1, n)]          # 20 ms 차분
        a = [0.0] + [(v[i] - v[i - 1]) / PERIOD for i in range(1, n)]
        vel_pct[pb.name] = [abs(s) / vmax * 100 if vmax > 0 else 0.0 for s in v]
        acc_pct[pb.name] = [abs(s) / amax * 100 if amax > 0 else 0.0 for s in a]
        for kind, series, lim in (('velocity', v, vmax), ('acceleration', a, amax)):
            if lim <= 0:
                continue
            for i0, i1, ratio, peak in segments(series, lim, WARN_RATIO):
                flags.append({'bone': pb.name, 'joint_name': jid, 'kind': kind,
                              'level': 'error' if ratio > 1.0 else 'warn',
                              'file_frame_from': i0 + 1, 'file_frame_to': i1 + 1,
                              'blender_frame_from': round(frames[max(i0 - 1, 0)], 3),
                              'blender_frame_to': round(frames[i1], 3),
                              'peak': round(peak, 3), 'limit': round(lim, 3),
                              'peak_ratio': round(ratio, 3)})

        lim = motor_limit(pb)
        clamped = 0
        if lim and not follows_other_bone(pb):
            clamped = sum(1 for r in raw[pb.name] if r < lim[0] - 1e-6 or r > lim[1] + 1e-6)
        limits_report.append({'bone': pb.name, 'joint_name': jid,
                              'blender_limit_deg': [round(d, 3) for d in lim] if lim else None,
                              'clip_min_deg': round(min(x), 3), 'clip_max_deg': round(max(x), 3),
                              'first_frame_deg': round(x[0], 3)})
        axes_report.append({
            'bone': pb.name, 'joint_name': jid,
            'vel_limit_deg_s': round(vmax, 3) if vmax > 0 else None,
            'acc_limit_deg_s2': round(amax, 3) if amax > 0 else None,
            'clip_peak_vel_deg_s': round(max(abs(s) for s in v), 3),
            'clip_peak_acc_deg_s2': round(max(abs(s) for s in a), 3),
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
    report_dir = os.path.join(out_dir, 'report')
    os.makedirs(report_dir, exist_ok=True)
    base = os.path.join(report_dir, name)
    with open(base + '_limits.json', 'w', encoding='utf-8') as f:
        json.dump(limits_report, f, ensure_ascii=False, indent=1)
    with open(base + '_check.json', 'w', encoding='utf-8') as f:
        json.dump(check, f, ensure_ascii=False, indent=1)

    update_markers(scene, flags)
    bake_check_curves(scene, arm, bones, frames, vel_pct, acc_pct)

    print('exported', path, '| samples', n, '| ids', [i for i, _ in ids])
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
        msg = '내보내기 → %s | errors %d, warnings %d' % (out_dir, check['errors'], check['warnings'])
        if check['not_checked']:
            msg += ' | 검사 안 함: ' + ', '.join(check['not_checked'])
        self.report({'WARNING'} if check['errors'] or check['warnings'] or check['not_checked'] else {'INFO'}, msg)
        return {'FINISHED'}


def run():
    given = globals().get('OUT_DIR')
    if given or bpy.app.background:
        return main(given)
    old = getattr(bpy.types, ROBOT_OT_animation_export.__name__, None)
    if old is not None:      # 스크립트 재실행 → 이 버전 main() 으로 다시 등록
        bpy.utils.unregister_class(old)
    bpy.utils.register_class(ROBOT_OT_animation_export)
    bpy.ops.robot.animation_export('INVOKE_DEFAULT')


if not globals().get('ANIM_NO_MAIN'):
    run()
