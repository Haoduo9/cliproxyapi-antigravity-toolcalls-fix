#!/bin/bash
# 停服务 → 换补丁二进制 → 起服务 → 验证
BASE=/home/dyk/桌面/workspace/cliproxyapi
LIVE=$BASE/cli-proxy-api
PATCHED=/home/dyk/.hermes/cache/scratch/cli-proxy-api.patched
ARCH=$(ls -t /home/dyk/桌面/workspace/archive/2026-10/cli-proxy-api.bak-toolcalls-* | head -1)

echo "=== 1) 停 CPA ==="
systemctl --user stop cli-proxy-api
sleep 1
systemctl --user is-active cli-proxy-api || echo "  已停止 (inactive)"

echo
echo "=== 2) 换二进制 ==="
cp "$PATCHED" "$LIVE" && chmod 755 "$LIVE"
LMD5=$(md5sum "$LIVE" | cut -d' ' -f1)
SIZE=$(stat -c%s "$LIVE")
echo "  生产 md5: $LMD5  大小: $SIZE"
if [ "$LMD5" != "a49e003f6775cf2b1d1bfbefc3ec62e4" ]; then
  echo "!! 校验失败，立刻回滚"
  cp -a "$ARCH" "$LIVE" && chmod 755 "$LIVE"
  systemctl --user start cli-proxy-api
  echo "已回滚并重启。备份来源: $ARCH"
  exit 1
fi
echo "  ✓ md5 与大小都对"

echo
echo "=== 3) 起 CPA ==="
systemctl --user start cli-proxy-api
sleep 4
systemctl --user is-active cli-proxy-api
echo "  MainPID: $(systemctl --user show cli-proxy-api -p MainPID --value)"
echo
echo "=== 4) 端口 ==="
ss -tlnp 2>/dev/null | grep 8317 || echo "  !! 8317 未监听"
echo
echo "回滚命令: systemctl --user stop cli-proxy-api && cp -a $ARCH $LIVE && chmod 755 $LIVE && systemctl --user start cli-proxy-api"
