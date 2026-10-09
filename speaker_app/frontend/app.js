"use strict";

const $ = (id) => document.getElementById(id);

let toastTimer = null;

// 사용자가 입력 중인 필드는 폴링으로 덮어쓰지 않는다
function setValue(el, value) {
  if (document.activeElement === el) return;
  if (el.value !== String(value)) el.value = value;
}

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2200);
}

async function api(path, body) {
  const opts = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : { method: "POST" };
  try {
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (data.ok === false && data.message) toast(data.message);
    return data.ok !== false;
  } catch (err) {
    toast("서버에 연결할 수 없습니다");
    return false;
  }
}

const DDS_LABEL = {
  connected: ["연결됨", "on"],
  connecting: ["연결 대기 중", "wait"],
  off: ["꺼짐", ""],
  error: ["오류", "err"],
};

const PLAYBACK_LABEL = { idle: "대기", playing: "재생 중", paused: "일시정지" };

function fmtSec(sec) {
  const n = Number(sec) || 0;
  if (n < 60) return n + "초";
  const m = Math.floor(n / 60);
  return m + "분 " + (n % 60) + "초";
}

// 첫 시작이 성공했는지와, 모션 PC가 보이는지는 서로 다른 문제다.
// 부팅 직후 랜이 늦어 시작 자체가 실패한 경우를 "신호 대기"와 구분해서 보여준다.
function ddsState(s) {
  if (s.mode !== "dds") return ["단독 모드입니다. 트리거는 받지 않습니다.", ""];
  const init = s.dds_init || {};
  const target = "도메인 " + init.domain_id + " / 그룹 " + init.group_id;
  const where = init.iface && init.ip ? " · " + init.iface + " " + init.ip : "";
  if (init.ok === false) {
    return ["시작 실패 — " + (init.error || s.dds_error || "원인 미확인") +
            " → [다시 연결]을 누르세요", "err"];
  }
  if (init.ok !== true) {
    return ["연동을 시작하는 중입니다… (" + target + ")", "wait"];
  }
  if (s.dds_status === "error") {
    return ["시작 후 오류 — " + (s.dds_error || "원인 미확인"), "err"];
  }
  if (s.dds_status === "connected") {
    return ["시작 성공 · 모션 PC 연결됨 — " + target + where, "on"];
  }
  return ["시작 성공 · 모션 PC 신호 대기 중 (" + fmtSec(init.elapsed) + " 경과) — " +
          target + where, "wait"];
}

function render(s) {
  const cfg = s.config;
  const isDds = s.mode === "dds";

  // 헤더 배지
  const info = DDS_LABEL[s.dds_status] || ["-", ""];
  const badge = $("dds-badge");
  badge.className = "badge " + info[1];
  const initFailed = isDds && s.dds_init && s.dds_init.ok === false;
  if (initFailed) badge.className = "badge err";
  badge.textContent = isDds
    ? (initFailed ? "DDS 시작 실패" : "DDS " + info[0]) +
      " (도메인 " + cfg.domain_id + " / " + cfg.group_id + ")"
    : "단독 모드";

  // 모드
  document.querySelectorAll("input[name=mode]").forEach((el) => {
    el.checked = el.value === s.mode;
  });
  let modeHint = isDds
    ? "모션 PC의 시작 트리거를 받아 자동 재생합니다. 이 PC 이름·주소를 2초마다 알려 로봇 PC 화면에 보이게 합니다."
    : "DDS와 무관하게 직접 재생합니다. 트리거는 받지 않습니다.";
  if (isDds && s.dds_status === "error" && s.dds_error) {
    modeHint = "DDS 오류: " + s.dds_error;
  }
  $("mode-hint").textContent = modeHint;

  const st = ddsState(s);
  const stEl = $("dds-state");
  stEl.className = "dds-state " + st[1];
  stEl.textContent = st[0];

  // 설정
  setValue($("domain_id"), cfg.domain_id);
  setValue($("group_id"), cfg.group_id);
  setValue($("pc_name"), cfg.pc_name || "");
  setValue($("offset_sec"), cfg.offset_sec);
  const stopChk = $("stop_on_motion_stop");
  if (document.activeElement !== stopChk) stopChk.checked = !!cfg.stop_on_motion_stop;
  setValue($("repeat"), cfg.repeat);
  setValue($("dwell_sec"), cfg.dwell_sec);
  $("sounds_dir").textContent = cfg.sounds_dir;

  // 기본 음원 · 음원 목록 · 애니메이션별 음원
  const hasFile = !!cfg.file_name;
  $("cur_file").textContent = hasFile ? cfg.file_name : "(없음 — 추가해 주세요)";
  $("btn-test").disabled = !hasFile;
  renderSounds(s);

  // 볼륨
  const vol = s.volume;
  const slider = $("volume");
  if (vol && vol.percent != null) {
    if (document.activeElement !== slider && !slider.dataset.dragging) {
      slider.value = vol.percent;
    }
    slider.disabled = false;
    $("volume_val").textContent = slider.value + "%" + (vol.muted ? " (음소거)" : "");
  } else {
    slider.disabled = true;
    $("volume_val").textContent = "조절 불가";
  }

  // 재생 상태
  const playing = s.playback === "playing";
  const paused = s.playback === "paused";
  let statusText = PLAYBACK_LABEL[s.playback] || s.playback;
  if (s.standalone_running && (playing || paused)) statusText += " (단독 반복)";
  $("playback").textContent = statusText;

  $("btn-play").disabled = isDds;
  $("btn-pause").disabled = !playing;
  $("btn-resume").disabled = !paused;
  $("btn-stop").disabled = !(playing || paused);
  $("standalone-opts").style.display = isDds ? "none" : "flex";

  let hint = "";
  if (isDds) {
    const t = s.last_trigger;
    hint = t
      ? "최근 트리거: cycle " + t.cycle_number + " / " + t.at +
        (t.motion_file_id ? " / " + t.motion_file_id : "") +
        (t.file_name ? " → " + t.file_name : "")
      : "아직 트리거를 받지 못했습니다.";
  }
  $("play-hint").textContent = hint;

  // 시스템 정보
  renderInfo(s);

  // 로그
  const list = $("logs");
  list.innerHTML = "";
  const logs = s.logs || [];
  if (logs.length === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "기록 없음";
    list.appendChild(li);
  } else {
    logs.forEach((entry) => {
      const li = document.createElement("li");
      const time = document.createElement("span");
      time.className = "t";
      time.textContent = entry.at;
      const text = document.createElement("span");
      text.textContent = entry.text;
      li.appendChild(time);
      li.appendChild(text);
      list.appendChild(li);
    });
  }
}

function button(label, cls, onClick) {
  const b = document.createElement("button");
  b.textContent = label;
  if (cls) b.className = cls;
  b.addEventListener("click", onClick);
  return b;
}

function fileSelect(files, selected, defaultLabel) {
  const sel = document.createElement("select");
  const none = document.createElement("option");
  none.value = "";
  none.textContent = defaultLabel;
  sel.appendChild(none);
  files.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  });
  sel.value = files.includes(selected) ? selected : "";
  return sel;
}

// 1초마다 다시 그리면 펼친 선택 상자가 닫힌다 · 내용이 바뀔 때만, 표 안을 만지는 중이 아닐 때만 그린다
let soundsKey = "";

function renderSounds(s) {
  const cfg = s.config;
  const files = s.files || [];
  const byMotion = cfg.by_motion || {};
  const seen = s.seen_motions || [];
  const key = JSON.stringify([files, cfg.file_name, byMotion, seen.map((m) => m.motion_file_id)]);
  const active = document.activeElement;
  const editing = active && (active.closest("#motion-map") || active.closest("#sound-list") ||
    active.id === "new_motion_file");
  if (key === soundsKey || editing) return;
  soundsKey = key;

  const list = $("sound-list");
  list.innerHTML = "";
  if (files.length === 0) {
    list.insertRow().insertCell().outerHTML = '<td class="empty">음원이 없습니다</td>';
  }
  files.forEach((name) => {
    const tr = list.insertRow();
    const td = tr.insertCell();
    td.className = "name";
    td.textContent = name;
    if (name === cfg.file_name) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = "기본";
      td.appendChild(tag);
    }
    const act = tr.insertCell();
    act.className = "act";
    if (name !== cfg.file_name) {
      act.appendChild(button("기본으로", "ghost", async () => {
        if (await api("/api/sound/default", { name })) toast("기본 음원: " + name);
        poll();
      }));
    }
    act.appendChild(button("다운로드", "ghost", () => {
      window.location.href = "/api/sound/download?name=" + encodeURIComponent(name);
    }));
    act.appendChild(button("삭제", "danger", async () => {
      const users = Object.keys(byMotion).filter((m) => byMotion[m] === name);
      const note = users.length ? "\n이 음원을 쓰는 애니메이션(" + users.join(", ") + ")은 기본 음원으로 돌아갑니다." : "";
      if (!window.confirm(name + " 을(를) 삭제할까요?" + note)) return;
      if (await api("/api/sound/delete", { name })) toast("삭제했습니다: " + name);
      poll();
    }));
  });

  const seenAt = {};
  seen.forEach((m) => { seenAt[m.motion_file_id] = m.at; });
  const motions = seen.map((m) => m.motion_file_id);
  Object.keys(byMotion).sort().forEach((m) => { if (!motions.includes(m)) motions.push(m); });
  const defaultLabel = "기본 음원" + (cfg.file_name ? " (" + cfg.file_name + ")" : "");
  const table = $("motion-map");
  table.innerHTML = "";
  if (motions.length === 0) {
    table.insertRow().insertCell().outerHTML =
      '<td class="empty">아직 받은 애니메이션이 없습니다 · 모두 기본 음원을 틉니다</td>';
  }
  motions.forEach((motion) => {
    const tr = table.insertRow();
    const name = tr.insertCell();
    name.className = "name";
    name.textContent = motion;
    const pick = tr.insertCell();
    const sel = fileSelect(files, byMotion[motion] || "", defaultLabel);
    sel.addEventListener("change", async () => {
      sel.blur();
      if (await api("/api/motion-sound", { motion_file_id: motion, file_name: sel.value })) {
        toast(motion + " → " + (sel.value || "기본 음원"));
      }
      poll();
    });
    pick.appendChild(sel);
    const when = tr.insertCell();
    when.className = "when";
    when.textContent = seenAt[motion] ? "최근 " + seenAt[motion] : "";
  });

  const add = $("new_motion_file");
  const keep = add.value;
  add.replaceWith(Object.assign(fileSelect(files, keep, "음원 선택"), { id: "new_motion_file" }));
}

function renderInfo(s) {
  const sys = s.system || {};
  const st = s.stats || {};
  const wav = s.wav || {};
  const rows = [
    ["group", "접속"],
    ["웹 주소", sys.web_url, true],
    ["컴퓨터 이름", sys.hostname],
    ["IP 주소", (sys.ip || "-") + " (" + (sys.interface || "-") + ")", true],
    ["group", "폴더"],
    ["프로그램", sys.app_dir, true],
    ["음원 폴더", sys.sounds_dir, true],
    ["설정 파일", sys.config_path, true],
    ["ROS 워크스페이스", sys.ros_workspace, true],
    ["group", "음원"],
    ["파일", s.config.file_name || "(없음)"],
    ["길이", wav.duration_text || "-"],
    ["포맷", wav.sample_rate
      ? wav.sample_rate + "Hz / " + (wav.channels === 1 ? "모노" : "스테레오")
        + " / " + wav.bit_depth + "bit / " + wav.size_mb + "MB"
        + (s.stereo_converted ? "  →  스테레오로 변환 재생 (양쪽 출력)" : "")
      : "-"],
    ["출력 장치", s.config.device, true],
    ["group", "DDS"],
    ["구독 토픽", sys.subscribe, true],
    ["발행 토픽", sys.publish],
    ["ROS / RMW", (sys.ros_distro || "-") + " / " + (sys.rmw || "-"), true],
    ["group", "동작 현황"],
    ["가동 시간", st.uptime || "-"],
    ["트리거 누적", (st.trigger_count != null ? st.trigger_count : 0) + "회"],
    ["평균 사이클", st.avg_interval != null ? st.avg_interval + "초" : "-"],
    ["group", "시스템"],
    ["OS", sys.os],
    ["Python", sys.python],
    ["소스 코드", sys.git_url, true],
    ["커밋", sys.git_head, true],
  ];
  const dl = $("info");
  dl.innerHTML = "";
  rows.forEach((row) => {
    if (row[0] === "group") {
      const head = document.createElement("div");
      head.className = "group";
      head.textContent = row[1];
      dl.appendChild(head);
      return;
    }
    const dt = document.createElement("dt");
    dt.textContent = row[0];
    const dd = document.createElement("dd");
    dd.textContent = row[1] == null || row[1] === "" ? "-" : row[1];
    if (row[2]) dd.className = "mono";
    dl.appendChild(dt);
    dl.appendChild(dd);
  });
}

async function poll() {
  try {
    const res = await fetch("/api/state");
    render(await res.json());
  } catch (err) {
    const badge = $("dds-badge");
    badge.className = "badge err";
    badge.textContent = "서버 연결 끊김";
  }
}

// ---- 이벤트 -----------------------------------------------------------
document.querySelectorAll("input[name=mode]").forEach((el) => {
  el.addEventListener("change", async () => {
    if (await api("/api/mode", { mode: el.value })) toast("모드를 전환했습니다");
    poll();
  });
});

$("btn-apply-dds").addEventListener("click", async () => {
  const ok = await api("/api/config", {
    domain_id: $("domain_id").value,
    group_id: $("group_id").value,
    pc_name: $("pc_name").value,
  });
  if (ok) toast("연동 설정을 저장했습니다");
  poll();
});

$("btn-reconnect-dds").addEventListener("click", async () => {
  if (await api("/api/dds/restart")) toast("연동을 다시 연결합니다");
  poll();
});

$("btn-upload").addEventListener("click", async () => {
  const input = $("file_input");
  const file = input.files && input.files[0];
  if (!file) { toast("업로드할 wav 파일을 선택하세요"); return; }
  if (!file.name.toLowerCase().endsWith(".wav")) { toast("wav 파일만 업로드할 수 있습니다"); return; }
  const btn = $("btn-upload");
  btn.disabled = true;
  toast("업로드 중... (" + Math.round(file.size / 1048576) + "MB)");
  try {
    const res = await fetch("/api/sound/upload?name=" + encodeURIComponent(file.name), {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    });
    const data = await res.json().catch(() => ({}));
    toast(data.ok ? "업로드 완료: " + file.name : (data.message || "업로드 실패"));
    if (data.ok) input.value = "";
  } catch (err) {
    toast("업로드 실패");
  }
  btn.disabled = false;
  poll();
});

$("btn-add-motion").addEventListener("click", async () => {
  const motion = $("new_motion").value.trim();
  const file = $("new_motion_file").value;
  if (!motion) { toast("애니메이션 이름을 넣으세요"); return; }
  if (!file) { toast("음원을 고르세요"); return; }
  if (await api("/api/motion-sound", { motion_file_id: motion, file_name: file })) {
    toast(motion + " → " + file);
    $("new_motion").value = "";
  }
  poll();
});

const volSlider = $("volume");
volSlider.addEventListener("input", () => {
  volSlider.dataset.dragging = "1";
  $("volume_val").textContent = volSlider.value + "%";
});
volSlider.addEventListener("change", async () => {
  await api("/api/volume", { percent: volSlider.value });
  delete volSlider.dataset.dragging;
  poll();
});

$("btn-apply-offset").addEventListener("click", async () => {
  if (await api("/api/config", { offset_sec: $("offset_sec").value })) toast("오프셋을 저장했습니다");
  poll();
});

$("btn-apply-standalone").addEventListener("click", async () => {
  const ok = await api("/api/config", {
    repeat: $("repeat").value,
    dwell_sec: $("dwell_sec").value,
  });
  if (ok) toast("반복 설정을 저장했습니다");
  poll();
});

$("stop_on_motion_stop").addEventListener("change", async (ev) => {
  const ok = await api("/api/config", { stop_on_motion_stop: ev.target.checked });
  if (ok) toast(ev.target.checked ? "모션 정지 시 소리도 정지합니다" : "모션이 정지해도 소리는 계속됩니다");
  poll();
});

$("btn-test").addEventListener("click", async () => { await api("/api/test"); poll(); });
$("btn-play").addEventListener("click", async () => { await api("/api/play"); poll(); });
$("btn-pause").addEventListener("click", async () => { await api("/api/pause"); poll(); });
$("btn-resume").addEventListener("click", async () => { await api("/api/resume"); poll(); });
$("btn-stop").addEventListener("click", async () => { await api("/api/stop"); poll(); });

// ---- PC 관리 · 로봇 PC 와 같은 것 · 수정 목록 89 (2026-10-09) ----------------
// 결과 JSON 을 그대로 받는 요청 · api() 는 ok 만 돌려준다
async function call(path, body) {
  const opts = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) };
  try {
    const res = await fetch(path, opts);
    return await res.json().catch(() => ({}));
  } catch (err) {
    return { success: false, message: "서버에 연결할 수 없습니다" };
  }
}

function sayResult(data, fallback) {
  const text = (data && data.message) || fallback || "";
  if (text) toast(text);
}

const host = window.location.hostname;
$("link-terminal").href = "http://" + host + ":8081";
$("link-btop").href = "http://" + host + ":8080";

$("btn-docs").addEventListener("click", async () => {
  const box = $("docs");
  if (!box.classList.contains("hidden")) { box.classList.add("hidden"); return; }
  const data = await call("/api/docs");
  box.textContent = data.text || "사용법을 불러오지 못했습니다";
  box.classList.remove("hidden");
});

$("btn-restart-app").addEventListener("click", async () => {
  if (!confirm("스피커 앱을 다시 시작합니다. 재생 중이면 소리가 끊깁니다. 계속할까요?")) return;
  sayResult(await call("/api/system/restart", {}));
});

const UPDATE_TEXT = { idle: "대기", running: "업데이트 중", done: "완료", failed: "실패" };
async function refreshUpdate() {
  const data = await call("/api/system/update");
  const state = UPDATE_TEXT[data.state] || data.state || "-";
  const version = data.state === "done" && data.before_hash && data.after_hash && data.before_hash !== data.after_hash
    ? data.before_hash + " → " + data.after_hash
    : (data.git_hash || "-");
  $("update-state").textContent = state + " · " + version + (data.message ? " · " + data.message : "");
  $("btn-update").disabled = data.state === "running";
}
$("btn-update").addEventListener("click", async () => {
  if (!confirm("이 PC 를 최신 코드로 업데이트합니다 (몇 분 · 그동안 스피커 앱이 다시 뜹니다). 계속할까요?")) return;
  sayResult(await call("/api/system/update", {}), "업데이트 시작");
  refreshUpdate();
});

async function refreshTime() {
  const data = await call("/api/system/time");
  const clock = data.clock || {};
  const local = String(clock.local_time || "").slice(0, 19).replace("T", " ");
  $("tz-now").textContent = (clock.timezone || "-") + " · " + local;
  const list = $("tz-list");
  if (!list.children.length && Array.isArray(data.timezones)) {
    data.timezones.forEach((zone) => {
      const option = document.createElement("option");
      option.value = zone;
      list.appendChild(option);
    });
  }
}
$("btn-tz").addEventListener("click", async () => {
  const zone = $("tz-pick").value.trim();
  if (!zone) { toast("시간대를 고르세요 (예 Asia/Seoul)"); return; }
  sayResult(await call("/api/system/timezone", { zone }));
  refreshTime();
});

async function refreshWifi() {
  const data = await call("/api/system/wifi");
  if (data.available === false) {
    $("wifi-now").textContent = data.message || "Wi-Fi 장치 없음";
  } else {
    $("wifi-now").textContent = (data.ssid || "(연결 안 됨)")
      + (data.signal != null ? " · 신호 " + data.signal : "")
      + (data.address ? " · " + data.address : "")
      + (data.method ? " · " + data.method : "")
      + (data.powersave ? " · 절전 " + data.powersave : "");
  }
  const pending = data.pending;
  $("wifi-pending").classList.toggle("hidden", !pending);
  if (pending) {
    const left = Math.max(0, Math.round(Number(pending.deadline || 0) - Date.now() / 1000));
    $("wifi-pending-text").textContent = pending.ssid + " 로 바꿈 · " + left + "초 안에 「유지」 를 누르세요";
  }
}
$("btn-wifi-scan").addEventListener("click", async () => {
  toast("Wi-Fi 찾는 중");
  const data = await call("/api/system/wifi/scan", {});
  const select = $("wifi-ssid");
  select.innerHTML = "";
  (data.networks || []).forEach((net) => {
    const option = document.createElement("option");
    option.value = net.ssid;
    option.dataset.security = net.security || "";
    option.textContent = net.ssid + " · " + (net.signal != null ? net.signal : "-")
      + (net.security ? " · " + net.security : " · 열림") + (net.in_use ? " · 지금" : "");
    select.appendChild(option);
  });
  if (!select.children.length) select.innerHTML = '<option value="">찾은 Wi-Fi 없음</option>';
  sayResult(data);
});
$("wifi-static-on").addEventListener("change", (ev) => {
  $("wifi-static").classList.toggle("hidden", !ev.target.checked);
});
$("btn-wifi-connect").addEventListener("click", async () => {
  const select = $("wifi-ssid");
  const ssid = select.value;
  if (!ssid) { toast("먼저 「찾기」 로 Wi-Fi 를 고르세요"); return; }
  if (!confirm(ssid + " 로 바꿉니다. 60초 안에 「유지」 를 눌러야 남습니다. 계속할까요?")) return;
  const option = select.selectedOptions[0];
  const body = {
    ssid,
    password: $("wifi-password").value,
    security: option ? option.dataset.security : "",
    static: $("wifi-static-on").checked ? {
      address: $("wifi-static-address").value.trim(),
      gateway: $("wifi-static-gateway").value.trim(),
      dns: $("wifi-static-dns").value.trim(),
    } : null,
  };
  sayResult(await call("/api/system/wifi/connect", body));
  $("wifi-password").value = "";
  refreshWifi();
});
$("btn-wifi-keep").addEventListener("click", async () => { sayResult(await call("/api/system/wifi/confirm", {})); refreshWifi(); });
$("btn-wifi-back").addEventListener("click", async () => { sayResult(await call("/api/system/wifi/rollback", {})); refreshWifi(); });

function refreshPcCard() {
  refreshUpdate();
  refreshTime();
  refreshWifi();
}
refreshPcCard();
setInterval(refreshPcCard, 5000);

poll();
setInterval(poll, 1000);
