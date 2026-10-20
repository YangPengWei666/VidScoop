const HOST = "com.localbot.ingest";
const KEY_HIDDEN = "localbot_btn_hidden";   // 与浮标共用同一个键
let url = "";

// ---- 当前页链接 ----
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  url = tabs[0] ? (tabs[0].url || "") : "";
  document.getElementById("url").textContent = url || "（拿不到当前页链接）";
});

// ---- 浮标显示开关 ----
const sw = document.getElementById("swFloat");

// 读取当前状态：localStorage 在扩展页与内容脚本之间不共享，
// 所以用 chrome.storage.local 作为唯一真源，浮标侧同步读取。
chrome.storage.local.get({ floatVisible: true }, (r) => {
  sw.checked = r.floatVisible;
});

sw.addEventListener("change", () => {
  const visible = sw.checked;
  chrome.storage.local.set({ floatVisible: visible }, () => {
    // 立刻通知所有已打开的标签页
    chrome.tabs.query({}, (tabs) => {
      for (const t of tabs) {
        if (t.id == null) continue;
        chrome.tabs.sendMessage(t.id, {
          type: "localbot-float-visible",
          visible: visible,
        }, () => void chrome.runtime.lastError);
      }
    });
  });
});

// ---- 转换按钮 ----
document.getElementById("go").addEventListener("click", () => {
  if (!url) return;
  const btn = document.getElementById("go");
  const st = document.getElementById("status");
  btn.disabled = true;
  btn.textContent = "已发起…";
  chrome.runtime.sendMessage({ type: "localbot-ingest", url: url }, (resp) => {
    if (chrome.runtime.lastError) {
      st.textContent = "失败：" + chrome.runtime.lastError.message;
      btn.disabled = false;
      btn.textContent = "转换当前页面";
      return;
    }
    if (resp && resp.ok) {
      st.textContent = "已开始转换，完成后会提示";
    } else {
      st.textContent = "失败：" + ((resp && resp.error) || "未知错误");
      btn.disabled = false;
      btn.textContent = "转换当前页面";
    }
  });
});
