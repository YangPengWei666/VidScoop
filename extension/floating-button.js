/**
 * floating-button.js —— 悬浮按钮（B站/YouTube 视频页自动出现）
 * 真·Obsidian 图标（exe 里抠出来的 3D 宝石），无底、可拖动、位置记忆。
 * 状态机（全部带过渡动画）：
 *   idle 待机（安静） → charging 充能（宝石变暗，单色紫水位 0→100% 自下而上，
 *   百分比全程跟随，辉光越来越亮）→ 成功：满水位回亮后平滑回归待机；失败：变灰停到下次点击。
 * 进度/结果由 background 通过 tabs.sendMessage 转发（localbot_progress / localbot_done）。
 */
(() => {
  if (window.__localbotFloatBtn) return;
  window.__localbotFloatBtn = true;

  const W = 80;                    // 横版宽（图形 2.65:1）
  const H = 30;                    // 横版高
  const KEY = "localbot_btn_pos";
  const IMG = {
    idle: chrome.runtime.getURL("icon-obsidian.png"),
  };

  // ---- 显示开关：与弹窗共用 chrome.storage.local.floatVisible ----
  let floatVisible = true;
  try {
    chrome.storage.local.get({ floatVisible: true }, function (r) {
      floatVisible = r.floatVisible !== false;
      applyVisible();
    });
  } catch (e) {}
  chrome.runtime.onMessage.addListener(function (m) {
    if (m && m.type === "localbot-float-visible") {
      floatVisible = m.visible !== false;
      applyVisible();
    }
  });
  function applyVisible() {
    const el = document.getElementById("localbot-float-btn");
    if (el) el.style.display = floatVisible ? "" : "none";
  }

  /*__P5_PURE__ 纯函数区：自检脚本 vm 提取，勿依赖 DOM/chrome */
  /* 总进度预算 0–100：页面真实下载百分比占 0–55，之后按 worker 阶段目标位缓涨 */
  const STAGE_TARGET = { started: 6, download: 55, retry: 55,
                         transcribe: 72, polish: 82, summarize: 92, write: 98 };
  function mapDownloadPct(n) {
    n = Math.min(100, Math.max(0, n));
    return Math.round(n * 0.55 * 10) / 10;
  }
  function parsePct(msg) {
    const mm = String(msg == null ? "" : msg).match(/(\d{1,3})\s*%/);
    return mm ? Math.min(100, Math.max(0, parseInt(mm[1], 10))) : null;
  }
  function toastText(r) {
    if (r && r.ok) return { kind: "ok", main: "✓ 搞定" };
    return { kind: "bad", main: "✗ " + ((r && r.error) || "写入失败") };
  }
  /*__/P5_PURE__*/

  const style = document.createElement("style");
  style.textContent = `
    #localbot-float-btn{position:fixed;top:30%;right:16px;z-index:2147483647;
      width:${W}px;height:${H}px;cursor:grab;
      user-select:none;-webkit-user-select:none;touch-action:none;}
    /* 整张长条图（波形 + 三条横杠） */
    #localbot-float-btn img{position:absolute;inset:0;width:100%;height:100%;
      pointer-events:none;display:block;
      filter:drop-shadow(0 1px 5px rgba(0,0,0,.35));
      transition:opacity .7s ease,transform .25s ease;}
    #localbot-float-btn.charging img{filter:brightness(.42) saturate(.75);}
    #localbot-float-btn.failed img{filter:grayscale(1) brightness(.6);}
    #localbot-float-btn.success img{filter:brightness(1.15);}
    /* 充能水位：自下而上 */
    #localbot-float-btn .fill-clip{position:absolute;inset:0;pointer-events:none;
      opacity:0;clip-path:inset(100% 0 0 0);
      transition:clip-path .3s linear,opacity .25s ease;}
    #localbot-float-btn.charging .fill-clip,
    #localbot-float-btn.success .fill-clip{opacity:1;}
    #localbot-float-btn .fill{position:absolute;inset:0;
      -webkit-mask-image:var(--waveMask);mask-image:var(--waveMask);
      -webkit-mask-size:contain;mask-size:contain;
      -webkit-mask-repeat:no-repeat;mask-repeat:no-repeat;
      -webkit-mask-position:center;mask-position:center;
      background:linear-gradient(155deg,#fff 0%,#d9c2ff 34%,#9b6dff 68%,#6a3ee0 100%);}
    /* 百分比 */
    #localbot-float-btn .pct{position:absolute;inset:0;display:flex;
      align-items:center;justify-content:center;pointer-events:none;
      font:700 11px/1 system-ui,-apple-system,sans-serif;color:#fff;
      -webkit-text-stroke:.5px rgba(0,0,0,.72);paint-order:stroke fill;
      text-shadow:0 1px 2px rgba(0,0,0,.55);
      opacity:0;transition:opacity .2s ease;}
    #localbot-float-btn.charging .pct,
    #localbot-float-btn.success .pct{opacity:1;}
    /* 辉光 */
    #localbot-float-btn .glow{position:absolute;inset:0;
      pointer-events:none;opacity:0;mix-blend-mode:screen;
      background:radial-gradient(circle at 42% 38%,
        rgba(255,255,255,.95) 0%, rgba(196,140,255,.85) 34%,
        rgba(150,70,255,.5) 62%, rgba(120,50,240,0) 100%);
      -webkit-mask-image:var(--waveMask);mask-image:var(--waveMask);
      -webkit-mask-size:contain;mask-size:contain;
      -webkit-mask-repeat:no-repeat;mask-repeat:no-repeat;
      -webkit-mask-position:center;mask-position:center;
      transition:opacity .3s ease;}
    #localbot-float-btn.charging .glow{opacity:var(--lb-glow,.12);}
    #localbot-float-btn.success .glow{opacity:.82;}

    /* 结果气泡（独立容器，setState 重绘碰不到） */
    #localbot-toast{position:fixed;z-index:2147483647;max-width:min(280px,72vw);
      pointer-events:none;padding:9px 12px;border-radius:12px;
      background:rgba(20,16,32,.88);border:1px solid rgba(155,109,255,.55);
      box-shadow:0 6px 24px rgba(0,0,0,.42);
      visibility:hidden;opacity:0;transform:translateY(4px) scale(.96);
      transition:opacity .22s ease,transform .22s ease;}
    #localbot-toast.show{visibility:visible;opacity:1;transform:none;}
    #localbot-toast.bad{border-color:rgba(255,107,107,.62)}
    #localbot-toast .t-main{font:600 13px/1.42 system-ui,-apple-system,sans-serif;color:#f2efff;
      display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
    #localbot-toast.bad .t-main{color:#ffd5d5}
    @media (prefers-reduced-motion:reduce){
      #localbot-float-btn *,#localbot-toast{
        animation-duration:.01ms!important;animation-iteration-count:1!important;
        transition-duration:.08s!important;}}
  `;
  (document.head || document.documentElement).appendChild(style);

  const btn = document.createElement("div");
  btn.id = "localbot-float-btn";
  btn.title = "存入 Obsidian 知识库";
  btn.innerHTML =
    `<img class="base" src="${IMG.idle}" alt="">` +
    `<div class="fill-clip"><div class="fill"></div></div>` +
    `<div class="glow"></div>` +
    `<span class="pct"></span>`;
  document.documentElement.appendChild(btn);
  applyVisible();
  const baseImg = btn.querySelector(".base");
  if (baseImg) btn.style.setProperty("--waveMask",
    "url(\"" + chrome.runtime.getURL("icon-obsidian.png") + "\")");
  const fillClip = btn.querySelector(".fill-clip");
  const pctEl = btn.querySelector(".pct");

  // ---- 状态机 ----
  let state = "idle";
  let succeeded = false; // 本轮是否已收到成功 done：成功后迟到的假失败（host 正常退出误报）整支吞掉
  function setState(next) {
    if (state === next) return;
    btn.classList.remove("charging", "success", "failed");
    state = next;
    if (next === "idle") {
      btn.title = "存入 Obsidian 知识库";
      resetFill(); // 成功动画结束后复位充能层（此时不可见，无闪烁）
    } else if (next === "charging") {
      // 失败(灰图)→充能：failed 类移除后灰图靠 .7s transition 自行淡出，填充层即刻接管
      btn.classList.add("charging");
      btn.title = "存知识库 · 处理中…";
      startDrift(); // 无真实数字时水位也朝阶段目标位缓慢爬升
    } else if (next === "success") {
      stopDrift();
      btn.classList.add("success");
      // 满水位停留 1.9s 后回待机（水位/辉光随类移除平滑淡出）
      setTimeout(() => { if (state === "success") setState("idle"); }, 1900);
    } else if (next === "failed") {
      stopDrift();
      btn.classList.add("failed");
    }
  }

  // ---- 提示音（短促、轻量；成功上行双音，失败下行单音）----
  function chime(ok) {
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      const ctx = new AC();
      const t0 = ctx.currentTime;
      const notes = ok ? [660, 880] : [233, 175];
      notes.forEach((f, i) => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = "sine"; o.frequency.value = f;
        const ts = t0 + i * 0.16;
        g.gain.setValueAtTime(0.0001, ts);
        g.gain.exponentialRampToValueAtTime(0.09, ts + 0.03);
        g.gain.exponentialRampToValueAtTime(0.0001, ts + 0.5);
        o.connect(g); g.connect(ctx.destination);
        o.start(ts); o.stop(ts + 0.55);
      });
      setTimeout(() => { try { ctx.close(); } catch (e) {} }, 1500);
    } catch (e) { /* 静音环境不打扰 */ }
  }

  // ---- P5R 充能：单色水位 0→100% 贯穿全程，辉光随进度越来越亮 ----
  let cur = 0;         // 当前水位（只增不减，reset 除外）
  let aim = 6;         // 当前目标位（页面真实下载百分比 / worker 阶段抬高）
  let driftTimer = 0;  // 无新消息时朝 aim 缓涨的节拍器（yt-dlp 等无百分比链路也不停摆）
  function renderFill() {
    fillClip.style.clipPath = "inset(" + (100 - cur) + "% 0 0 0)";
    pctEl.textContent = Math.round(cur) + "%";
    btn.style.setProperty("--lb-glow", (0.12 + (cur / 100) * 0.70).toFixed(3));
  }
  function growTo(v) { // 水位只升不降
    v = Math.max(0, Math.min(100, v));
    if (v <= cur) return;
    cur = v;
    renderFill();
  }
  function startDrift() {
    if (driftTimer) return;
    driftTimer = setInterval(() => {
      if (cur < aim) growTo(cur + Math.max(0.6, (aim - cur) * 0.12));
    }, 600);
  }
  function stopDrift() {
    if (driftTimer) { clearInterval(driftTimer); driftTimer = 0; }
  }
  function resetFill() {
    stopDrift();
    cur = 0;
    aim = 6;
    btn.style.removeProperty("--lb-glow");
    fillClip.style.clipPath = "inset(100% 0 0 0)";
    pctEl.textContent = "";
  }
  function applyDownloadPct(n) { // 页面分块真实百分比 → 总进度 0–55
    const v = mapDownloadPct(n);
    if (v > aim) aim = v;
    growTo(v);
  }
  function applyStage(stage) { // worker 阶段：只抬高目标位，水位交给驱动器缓涨
    const t = STAGE_TARGET[stage];
    if (t != null && t > aim) aim = t;
  }
  function enterSuccessFill() {
    stopDrift();
    aim = 100;
    growTo(100); // .3s 平滑补满，数字停在 100%
  }

  // ---- P5 结果气泡（独立容器，setState 重绘永远碰不到它）----
  let toastHideTimer = 0;
  let toastRemoveTimer = 0;
  function showToast(kind, main) {
    clearTimeout(toastHideTimer);
    clearTimeout(toastRemoveTimer);
    const old = document.getElementById("localbot-toast");
    if (old) old.remove();
    const el = document.createElement("div");
    el.id = "localbot-toast";
    if (kind === "bad") el.classList.add("bad");
    const mainEl = document.createElement("div");
    mainEl.className = "t-main";
    mainEl.textContent = main;
    el.appendChild(mainEl);
    document.documentElement.appendChild(el); // 无 show 类时 visibility:hidden，可测量
    const r = btn.getBoundingClientRect();
    const w = el.offsetWidth, h = el.offsetHeight;
    let left;
    if (r.left + r.width / 2 > window.innerWidth / 2) {
      left = Math.max(8, r.left - w - 8);           // 按钮在右半屏：气泡出左侧
    } else {
      left = Math.min(r.right + 8, window.innerWidth - w - 8);
    }
    const top = Math.max(8, Math.min(r.top + (r.height - h) / 2, window.innerHeight - h - 8));
    el.style.left = left + "px";
    el.style.top = top + "px";
    requestAnimationFrame(() => el.classList.add("show"));
    toastHideTimer = setTimeout(() => {
      el.classList.remove("show");
      toastRemoveTimer = setTimeout(() => { el.remove(); }, 260);
    }, 4000);
  }
  function hideToast() {
    const el = document.getElementById("localbot-toast");
    if (!el) return;
    clearTimeout(toastHideTimer);
    el.classList.remove("show");
    clearTimeout(toastRemoveTimer);
    toastRemoveTimer = setTimeout(() => { el.remove(); }, 260);
  }

  // ---- 接收 background 转发的进度/结果 ----
  // 页面内下载器（同帧隔离世界）直接调这个钩子报进度，不必绕 background
  window.__localbotProgress = (msg) => {
    if (state !== "charging") setState("charging");
    btn.title = "存知识库 · " + msg;
    const n = parsePct(msg);
    if (n !== null) applyDownloadPct(n);
  };
  chrome.runtime.onMessage.addListener((m) => {
    if (!m) return;
    if (m.localbot_progress) {
      if (state !== "charging") setState("charging");
      const p = m.localbot_progress;
      btn.title = "存知识库 · " + (p.msg || "处理中…");
      if (p.stage) applyStage(p.stage);
    } else if (m.localbot_done) {
      const r = m.localbot_done;
      const t = toastText(r);
      if (r.ok) {
        succeeded = true; // 终态锁定：后面 onDisconnect 迟到的假失败到这里直接吞
        enterSuccessFill();
        setState("success");
        chime(true);
        btn.title = (r.skipped ? "✓ 已入库过 · " : "✓ 已入库 · ") + (r.title || "");
        showToast(t.kind, t.main); // 成功统一一句话「✓ 搞定」
      } else {
        if (succeeded) return; // 成功后迟到的失败（host 正常退出被误报）：不翻案、不响失败音、不弹红气泡
        setState("failed");
        chime(false);
        btn.title = "✗ 失败 · " + (r.error || "未知原因");
        showToast(t.kind, t.main);
      }
    } else if (m.localbot_started === false && m.error) {
      setState("failed");
      btn.title = "✗ " + m.error;
      showToast("bad", "✗ " + m.error);
    } else if (m.localbot_host_exit && state === "charging") {
      // 本地进程意外退出且没发过结果（崩溃被漏掉）→ 不能永远卡在充能态
      setState("failed");
      const exitMsg = "✗ 本地处理中断（退出码 " + (m.localbot_host_exit.code ?? "?") + "）";
      btn.title = exitMsg;
      showToast("bad", exitMsg);
    }
  });

  // ---- 点击与拖动 ----
  btn.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    let moved = false;
    const sx = e.clientX, sy = e.clientY;
    const rect = btn.getBoundingClientRect();
    const ox = rect.left, oy = rect.top;
    btn.setPointerCapture(e.pointerId);
    btn.classList.add("dragging");

    const onMove = (ev) => {
      const dx = ev.clientX - sx, dy = ev.clientY - sy;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) moved = true;
      if (!moved) return;
      const cur = btn.getBoundingClientRect();
      const L = Math.min(Math.max(0, ox + dx), window.innerWidth - cur.width);
      const T = Math.min(Math.max(0, oy + dy), window.innerHeight - cur.height);
      btn.style.left = L + "px";
      btn.style.top = T + "px";
      btn.style.right = "auto";
    };
    const onUp = () => {
      btn.classList.remove("dragging");
      btn.removeEventListener("pointermove", onMove);
      btn.removeEventListener("pointerup", onUp);
      if (moved) {
        const r = btn.getBoundingClientRect();
        try { localStorage.setItem(KEY, JSON.stringify({ left: r.left + "px", top: r.top + "px" })); } catch (e) {}
      } else {
        doIngest();
      }
    };
    btn.addEventListener("pointermove", onMove);
    btn.addEventListener("pointerup", onUp);
  });

  function doIngest() {
    if (state === "charging") return; // 处理中防连点：重复点击会开出多个重复任务
    resetFill();  // 新一轮：水位/辉光/节拍器全部归零，防上一轮状态串扰
    succeeded = false; // 新一轮放行真实失败（上一轮的成功锁必须解除）
    hideToast();
    setState("charging"); // 点击瞬间进入充能态，进度消息会持续刷新提示
    chrome.runtime.sendMessage({ type: "localbot-ingest", url: location.href });
  }

  // 恢复上次拖动的位置
  try {
    const p = JSON.parse(localStorage.getItem(KEY) || "null");
    if (p && p.left) { btn.style.left = p.left; btn.style.top = p.top; btn.style.right = "auto"; }
  } catch (e) { /* 无记录用默认位置 */ }
})();
