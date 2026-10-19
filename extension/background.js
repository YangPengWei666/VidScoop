const HOST = "com.localbot.ingest";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "save-to-kb",
    title: "📥 存知识库",
    contexts: ["page", "link", "video", "frame"]
  });
});

// ============ 统一入口：右键菜单和弹窗按钮都走这里 ============

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const url = info.linkUrl || info.srcUrl || info.pageUrl || (tab && tab.url);
  if (url) handleIngest(url, tab, "右键菜单");
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "localbot-ingest" && msg.url) {
    if (sender.tab && sender.tab.id != null) {
      // 来自悬浮按钮（内容脚本）：sender 自带所在 tab，最准
      handleIngest(msg.url, sender.tab, "悬浮按钮");
    } else {
      // 来自弹窗：查当前活动 tab
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        handleIngest(msg.url, tabs && tabs[0], "弹窗按钮");
      });
    }
    sendResponse({ ok: true });
    return true;
  }
});

function handleIngest(url, tab, src) {
  // 全路径探针：随消息写进 worker.log，断点一眼可见
  const dbg = "v=" + chrome.runtime.getManifest().version
    + " src=" + src
    + " tab=" + (tab && tab.id != null ? tab.id : "无")
    + " scripting=" + (chrome.scripting ? "有" : "无");

  // 把链接交给本地助手（yt-dlp 处理 B站/YouTube）
  sendToHost(url, dbg, tab ? tab.id : null);
}

function sendToHost(url, debugInfo, tabId) {
  // 长连接端口：native_host 会随任务全程，实时回传进度/结果（不再弹任何系统通知）
  let port;
  try {
    port = chrome.runtime.connectNative(HOST);
  } catch (e) {
    if (tabId != null) {
      chrome.tabs.sendMessage(tabId, { localbot_done: { ok: false, error: "无法启动本地助手：" + String((e && e.message) || e).slice(0, 120) } }, () => void chrome.runtime.lastError);
    }
    return null;
  }
  let settled = false; // worker 的 done 是否已到过（最终结论；到过后 host 退出不许翻案）
  const msg = { url };
  if (debugInfo) msg.ext_debug = debugInfo;
  port.postMessage(msg);
  port.onMessage.addListener((m) => {
    if (!m) return;
    if (m.localbot_done) settled = true; // done 已给最终结论，之后 onDisconnect 的"host 已退出"一律不翻案
    if (m.localbot_host_exit && !m.localbot_done) return; // 收尾兜底由 done 消息负责
    if (tabId != null) {
      // 页面可能已关闭：吞掉“无接收方”报错
      chrome.tabs.sendMessage(tabId, m, () => void chrome.runtime.lastError);
    }
  });
  port.onDisconnect.addListener(() => {
    const err = chrome.runtime.lastError && chrome.runtime.lastError.message;
    if (err && !settled && tabId != null) {
      // 任务中途退出（done 从未来过）：告诉页面让图标从充能态出来；
      // done 已到过（含成功）后的正常退出/崩溃一律静默，不翻案
      chrome.tabs.sendMessage(tabId, { localbot_done: { ok: false, error: "本地助手中断：" + err } }, () => void chrome.runtime.lastError);
    }
  });
  return port;
}
