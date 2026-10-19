const HOST = "com.localbot.ingest";
let url = "";

chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  url = tabs[0] ? (tabs[0].url || "") : "";
  document.getElementById("url").textContent = url || "（拿不到当前页链接）";
});

// 弹窗不直发链接，统一交给 background 处理——
// 右键菜单和按钮行为完全一致
document.getElementById("go").addEventListener("click", () => {
  if (!url) return;
  const btn = document.getElementById("go");
  const st = document.getElementById("status");
  btn.disabled = true;
  btn.textContent = "已发起…";
  chrome.runtime.sendMessage({ type: "localbot-ingest", url: url }, (resp) => {
    if (chrome.runtime.lastError) {
      st.textContent = "❌ " + chrome.runtime.lastError.message;
      btn.disabled = false;
      btn.textContent = "📥 存知识库";
      return;
    }
    if (resp && resp.ok) {
      st.textContent = "✅ 已交给本地助手，完成后弹系统通知";
    } else {
      st.textContent = "❌ " + ((resp && resp.error) || "未知错误");
      btn.disabled = false;
      btn.textContent = "📥 存知识库";
    }
  });
});
