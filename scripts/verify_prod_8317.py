#!/usr/bin/env python3
"""验证生产 CPA (8317)：tool_calls:null 是否消失、工具调用是否仍正常"""
import json, time, urllib.request, urllib.error

KEY = None
for line in open("/home/dyk/.hermes/.env"):
    if line.startswith("HERMES_CUSTOM_127_0_0_1_8317_API_KEY="):
        KEY = line.split("=", 1)[1].strip()
        break
assert KEY, "没找到 key"
BASE = "http://127.0.0.1:8317"

# 等模型注册
models, waited = [], 0
while waited < 120:
    try:
        req = urllib.request.Request(BASE + "/v1/models", headers={"Authorization": "Bearer " + KEY})
        with urllib.request.urlopen(req, timeout=20) as r:
            models = [m.get("id") for m in json.loads(r.read().decode()).get("data", [])]
        if "gemini-3.5-flash-lite" in models:
            break
    except Exception as e:
        print("  轮询异常: %s" % e)
    time.sleep(3)
    waited += 3
print("等待 %.0fs, 模型数=%d, 目标模型在列=%s" % (waited, len(models), "gemini-3.5-flash-lite" in models))
assert "gemini-3.5-flash-lite" in models, "模型未注册，中止"


def call(payload, tag):
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Authorization": "Bearer " + KEY,
                                          "Content-Type": "application/json"})
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
        print("  %s: HTTP %d %s" % (tag, e.code, e.read().decode("utf-8", "replace")[:300]))
        return None
    nulls = sum(1 for f in frames if '"tool_calls":null' in f)
    arrays = sum(1 for f in frames if '"tool_calls":[' in f)
    print("  %s: %d 帧 | tool_calls:null 帧=%d | tool_calls:[...] 帧=%d" % (tag, len(frames), nulls, arrays))
    for i, f in enumerate(frames[:1]):
        print("     帧0: %s" % f[:210])
    return nulls, arrays


print("\n=== 生产实例 8317 验证 ===")
r1 = call({"model": "gemini-3.5-flash-lite", "stream": True,
           "messages": [{"role": "user", "content": "只说三个字：我很好"}]}, "A 纯文本流式")
r2 = call({"model": "gemini-3.5-flash-lite", "stream": True,
           "messages": [{"role": "user", "content": "调用工具查一下北京天气"}],
           "tools": [{"type": "function", "function": {"name": "get_weather", "description": "查天气",
                      "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                                     "required": ["city"]}}}]}, "B 工具调用")

print()
ok = True
if not r1 or r1[0] != 0:
    print("❌ A 仍有 tool_calls:null"); ok = False
else:
    print("✅ A 纯文本流式：0 帧含 tool_calls:null")
if not r2 or r2[0] != 0:
    print("❌ B 仍有 tool_calls:null"); ok = False
elif r2[1] < 1:
    print("❌ B 工具调用帧丢了！"); ok = False
else:
    print("✅ B 工具调用：0 帧含 tool_calls:null，且工具调用帧仍正常（%d 帧）" % r2[1])
print("\n结论: %s" % ("生产验证通过" if ok else "生产验证未过——需回滚"))
