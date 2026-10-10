#!/usr/bin/env python3
"""校验打补丁后的二进制：跑起来、抓 SSE 帧、确认 tool_calls:null 消失且工具调用仍正常"""
import subprocess, time, json, sys, os, urllib.request, socket

BASE = "/home/dyk/桌面/workspace/cliproxyapi"
PAT = "/home/dyk/.hermes/cache/scratch/cli-proxy-api.patched"
PROBE_CFG = "/home/dyk/.hermes/cache/scratch/probe8318.yaml"
KEY = None
for line in open("/home/dyk/.hermes/.env"):
    if line.startswith("HERMES_CUSTOM_127_0_0_1_8317_API_KEY="):
        KEY = line.split("=", 1)[1].strip()
        break
assert KEY, "没找到 key"

# 从正式配置派生：换端口 8318、关掉文件日志（免得和正式实例抢 main.log）
import yaml
cfg = yaml.safe_load(open(os.path.join(BASE, "config.yaml")))
cfg["server"]["port"] = 8318
cfg["observability"]["logs"]["logging-to-file"] = False
yaml.safe_dump(cfg, open(PROBE_CFG, "w"), allow_unicode=True, sort_keys=False)
print("探测配置已写: %s (port=8318, file-log=off)" % PROBE_CFG)

proc = subprocess.Popen([PAT, "-config", PROBE_CFG],
                        stdout=open("/home/dyk/.hermes/cache/scratch/probe8318.out", "w"),
                        stderr=subprocess.STDOUT)

def wait_port(port, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = socket.socket()
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except Exception:
            time.sleep(0.5)
        finally:
            try: s.close()
            except Exception: pass
    return False

try:
    if not wait_port(8318):
        print("!! 8318 没起来")
        sys.exit(1)
    print("补丁实例已在 8318 监听 (pid=%d)" % proc.pid)

    # 等模型注册完成（异步从上游拉取）
    def fetch_models():
        req = urllib.request.Request("http://127.0.0.1:8318/v1/models",
                                     headers={"Authorization": "Bearer " + KEY})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())

    models, waited = [], 0
    while waited < 90:
        try:
            d = fetch_models()
            models = [m.get("id") for m in d.get("data", [])]
            if "gemini-3.5-flash-lite" in models:
                break
        except Exception as e:
            print("  轮询异常: %s" % e)
        time.sleep(3)
        waited += 3
    print("等待 %.0fs 后模型数=%d, 目标模型在列=%s" % (waited, len(models), "gemini-3.5-flash-lite" in models))

    def call(payload, tag):
        req = urllib.request.Request(
            "http://127.0.0.1:8318/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
        frames = []
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if line.startswith("data:"):
                        b = line[5:].strip()
                        if b and b != "[DONE]":
                            frames.append(b)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            print("\n=== %s: HTTP %d ===" % (tag, e.code))
            print("  响应体: %s" % body[:600])
            return []
        print("\n=== %s: 抓到 %d 帧 ===" % (tag, len(frames)))
        nulls = sum(1 for f in frames if '"tool_calls":null' in f)
        arrays = sum(1 for f in frames if '"tool_calls":[' in f)
        print("  含 tool_calls:null 的帧: %d   ← 修复后应为 0" % nulls)
        print("  含 tool_calls:[...] 的帧: %d" % arrays)
        for i, f in enumerate(frames):
            d = json.loads(f)
            delta = d["choices"][0]["delta"]
            keys = ",".join(k for k in delta.keys() if delta[k] is not None or k == "role")
            print("   帧%d keys=%s" % (i, keys))
            if i == 0:
                print("       原样: %s" % f[:230])
        return frames

    # A: 纯文本流式
    call({"model": "gemini-3.5-flash-lite", "stream": True,
          "messages": [{"role": "user", "content": "只说三个字：我很好"}]}, "A 纯文本流式")

    # B: 带工具调用
    call({"model": "gemini-3.5-flash-lite", "stream": True,
          "messages": [{"role": "user", "content": "调用工具查一下北京天气"}],
          "tools": [{"type": "function", "function": {"name": "get_weather", "description": "查天气",
                     "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                                    "required": ["city"]}}}]}, "B 工具调用")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
    print("\n探测实例已停止")
