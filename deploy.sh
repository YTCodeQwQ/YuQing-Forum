#!/bin/bash
# 语晴论坛 - 代码部署脚本
# 用法: bash deploy.sh

set -e

cd /home/yutian/workspace/forum

echo "=== 拉取最新代码 ==="
git pull

echo "=== 清除缓存 ==="
rm -f __pycache__/*.pyc

echo "=== 重启服务 ==="
fuser -k 5006/tcp 2>/dev/null || true
sleep 1
nohup python3 app.py > /tmp/forum.log 2>&1 &

sleep 2
if ss -tlnp | grep -q 5006; then
    echo "=== 部署成功，端口 5006 已启动 ==="
else
    echo "=== 部署失败，请检查日志 ==="
    tail -20 /tmp/forum.log
fi
