#!/usr/bin/env python3
"""重建探测配置：不重新序列化 yaml，只做文本级替换，避免破坏原配置"""
import re, sys

BASE = "/home/dyk/桌面/workspace/cliproxyapi/config.yaml"
OUT = "/home/dyk/.hermes/cache/scratch/probe8318.yaml"

txt = open(BASE, encoding="utf-8").read()

# 1) server.port: 8317 -> 8318（只替换第一个处于 server 段下的 port 行）
new, n = re.subn(r"(?m)^(\s+)port:\s*8317\s*$", r"\1port: 8318", txt, count=1)
print("port 替换次数: %d" % n)
assert n == 1, "port 替换失败"

# 2) 关掉文件日志，免得和正式实例抢 main.log
before = new
new, n2 = re.subn(r"(?m)^(\s*)logging-to-file:\s*true\s*$", r"\1logging-to-file: false", new, count=1)
print("logging-to-file 替换次数: %d" % n2)

open(OUT, "w", encoding="utf-8").write(new)

# 校验：能被 yaml 解析，且 port 对了
import yaml
d = yaml.safe_load(open(OUT, encoding="utf-8"))
print("解析校验: server.port = %s, access.api-keys 条数 = %d, models 键数 = %d"
      % (d["server"]["port"], len(d["access"]["api-keys"]), len(d.get("models") or {})))
print("行数: 原 %d -> 新 %d" % (txt.count("\n"), new.count("\n")))
print("已写出: %s" % OUT)
