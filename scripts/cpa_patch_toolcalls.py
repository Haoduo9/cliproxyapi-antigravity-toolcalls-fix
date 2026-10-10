#!/usr/bin/env python3
"""
CPA antigravity 流式 delta 的 tool_calls:null 修复补丁（等长字节替换）
目标: internal/translator/antigravity/openai/chat-completions/antigravity_openai_response.go L98 的 streaming delta 模板
手法: 摘掉 "tool_calls":null 这个键（连同前面的逗号一起变成空格），保持字节长度不变
      因为 gjson 对 null 和 missing 都返回 Exists()=false，工具调用分支走的是同一条 else 路径，
      所以带工具调用的帧输出字节级不变 —— 只有非工具帧不再吐 tool_calls:null
"""
import sys, shutil, hashlib, re

SRC = "/home/dyk/桌面/workspace/cliproxyapi/cli-proxy-api"
DST = "/home/dyk/.hermes/cache/scratch/cli-proxy-api.patched"

data = bytearray(open(SRC, "rb").read())
orig_len = len(data)
orig_md5 = hashlib.md5(bytes(data)).hexdigest()

needle = b',"tool_calls":null'
hits = []
start = 0
while True:
    p = data.find(needle, start)
    if p < 0:
        break
    hits.append(p)
    start = p + 1

print("原始大小: %d  原始 md5: %s" % (orig_len, orig_md5))
print("命中 %d 处:" % len(hits))

# 只补 streaming delta 模板（上下文里带 chat.completion.chunk 的那处）
targets = []
for p in hits:
    ctx = bytes(data[max(0, p - 200):p])
    tail = bytes(data[p:p + 300])
    is_chunk = b'"object":"chat.completion.chunk"' in ctx
    is_msg = b'"object":"chat.completion"' in ctx
    print("  offset=%-9d chunk模板=%-5s 非流式message模板=%-5s" % (p, is_chunk, is_msg))
    print("    上文: ...%s" % ctx[-80:].decode("utf-8", "replace"))
    if is_chunk:
        targets.append(p)

assert len(targets) == 1, "预期只命中 1 处 chunk 模板，实际 %d 处 —— 停止，需人工确认" % len(targets)
tp = targets[0]

# 等长替换: ',"tool_calls":null' (18 字节) -> 18 个空格
# 结果: {"role":null,"content":null,"reasoning_content":null                  } —— JSON 合法，键消失
repl = b" " * len(needle)
data[tp:tp + len(needle)] = repl

assert len(data) == orig_len, "长度变了！"
new_md5 = hashlib.md5(bytes(data)).hexdigest()

# 落盘前自检：替换点上下文必须是合法 JSON 片段形态
check = bytes(data[tp - 60:tp + 60]).decode("utf-8", "replace")
print()
print("补丁后大小: %d (未变)" % len(data))
print("补丁后 md5: %s" % new_md5)
print("替换点上下文: %s" % check)
print("tool_calls 残留次数: %d (原 3 处，现应为 2)" % bytes(data).count(b',"tool_calls":null'))

open(DST, "wb").write(bytes(data))
shutil.copystat(SRC, DST)
print()
print("已写出: %s" % DST)
