"""
native_host.py —— Chrome Native Messaging 入口（由扩展通过 connectNative 唤起）
收到 {url} → 启动 worker → 实时转发进度与终态。
韧性：浏览器中途关闭导致管道断开时，本进程退出，worker 作为孤儿进程继续跑完。
"""
import sys
import os
import json
import struct
import subprocess
import threading
import time

# 打包成 exe（--noconsole）后 __file__ 不可靠，用 exe 自身位置定位
if getattr(sys, "frozen", False):
    BASE = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
PYTHONW = os.path.join(BASE, ".venv", "Scripts", "pythonw.exe")
WORKER = os.path.join(BASE, "worker.py")

_out_lock = threading.Lock()


def read_message():
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None
    (length,) = struct.unpack("<I", raw)
    try:
        return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))
    except Exception:
        return {}


def send_message(obj) -> bool:
    """发一条 Native Messaging 消息；管道断开返回 False。"""
    try:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        with _out_lock:
            sys.stdout.buffer.write(struct.pack("<I", len(data)))
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        return True
    except Exception:
        return False  # Chrome 已断开（页面关闭/扩展重载）


def logline(text: str):
    try:
        stamp = __import__("time").strftime("%Y-%m-%d %H:%M:%S")
        with open(os.path.join(BASE, "worker.log"), "a", encoding="utf-8") as f:
            f.write(f"{stamp} INFO native_host: {text}\n")
    except Exception:
        pass


def main():
    msg = read_message()
    if not msg or not msg.get("url"):
        send_message({"localbot_started": False, "error": "no url in message"})
        return
    url = str(msg["url"]).strip()
    # 探针：把扩展→助手这一环的实况写进 worker.log，断点一眼可见
    logline(f"收到消息 url={url[:80]} debug={str(msg.get('ext_debug') or '-')}")

    send_message({"localbot_started": True, "url": url})
    cmd = [PYTHONW, WORKER, url]

    # ---------- 看门狗 + 启动自动重试 ----------
    # 现象：worker 偶尔被安全软件（火绒主动防御）冻在启动环节，0 CPU、无输出、不退出，
    #      图标就无限呼吸。策略：
    #      a) 启动 90s 无任何输出 → 判定冻结，杀掉自动重拉一次；重试再冻才报失败（图标变灰）。
    #      b) 有过输出后 300s 静默 → 判定卡死，报失败。
    #      无论哪种，worker 都留作孤儿——若之后被放行恢复，仍会继续跑完并写笔记。
    FIRST_OUT_LIMIT = 90
    SILENT_LIMIT = 300
    MAX_START_ATTEMPTS = 2
    attempt = 0
    returncode = None
    while True:
        attempt += 1
        try:
            # stdout=PIPE：worker 的进度 JSON 行实时回传给 Chrome
            # CREATE_NO_WINDOW：全链路无黑框
            proc = subprocess.Popen(
                cmd, cwd=BASE,
                stdin=subprocess.DEVNULL,  # 不继承 Chrome 管道；worker 不读 stdin
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace",
                creationflags=0x08000000,
            )
        except Exception as e:
            send_message({"localbot_started": False, "error": str(e)[:200]})
            return

        last_output = [time.time()]   # pump 每读到 worker 一行输出就刷新
        got_output = [False]
        frozen = [False]

        def pump():
            """读 worker 的 stdout 进度行并转发；管道断开时静默退出（worker 继续跑）。"""
            try:
                for line in proc.stdout:
                    last_output[0] = time.time()
                    got_output[0] = True
                    line = line.strip()
                    if not line or ("localbot_" not in line):
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if not send_message(obj):
                        return  # Chrome 已断开，停止转发但让 worker 跑完
            except Exception:
                pass

        threading.Thread(target=pump, daemon=True).start()

        def watchdog():
            while proc.poll() is None:
                silent_for = time.time() - last_output[0]
                if got_output[0]:
                    limit, tag = SILENT_LIMIT, "长时间无输出"
                else:
                    limit, tag = FIRST_OUT_LIMIT, "启动超时"
                if silent_for > limit:
                    if tag == "启动超时" and attempt < MAX_START_ATTEMPTS:
                        logline(f"看门狗：worker {tag}（{silent_for:.0f}s 无输出），疑似被安全软件冻结 → 自动重试（{attempt}/{MAX_START_ATTEMPTS - 1}）")
                        send_message({"localbot_progress": {"stage": "retry", "msg": "后台启动卡住，自动重试中…"}})
                        frozen[0] = True
                        proc.kill()
                        return
                    logline(f"看门狗：worker {tag}（{silent_for:.0f}s 无输出） → 报失败；worker 留作孤儿，若恢复仍会继续")
                    code = "watchdog_startup" if tag == "启动超时" else "watchdog_silent"
                    send_message({"localbot_host_exit": {"code": code}})
                    return
                time.sleep(5)

        threading.Thread(target=watchdog, daemon=True).start()
        proc.wait()  # 陪跑到任务结束

        if frozen[0]:
            continue  # 冻结 → 重拉 worker
        returncode = proc.returncode
        break

    # worker 结束却没发过收尾消息（异常崩溃被 except 漏掉等）→ 补一条，浏览器图标不至于卡在充能态
    logline(f"worker 退出 code={returncode}")
    send_message({"localbot_host_exit": {"code": returncode}})


if __name__ == "__main__":
    main()
