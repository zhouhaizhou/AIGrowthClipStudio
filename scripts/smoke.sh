#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DB_PATH="$ROOT/data/agcs.db"
export STORAGE_DIR="$ROOT/storage"
export API_PORT="${API_PORT:-8787}"
mkdir -p "$ROOT/data" "$ROOT/storage"

cleanup() {
  # Kill whatever is still listening on the API port (node child, npm wrapper, etc.).
  local pids
  pids="$(lsof -ti "tcp:$API_PORT" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    kill $pids 2>/dev/null || true
  fi
}
trap cleanup EXIT

# 1) 生成一个本地样例视频
SAMPLE="$ROOT/storage/sample.mp4"
if [ ! -f "$SAMPLE" ]; then
  ffmpeg -y -f lavfi -i testsrc=duration=20:size=1280x720:rate=25 \
    -f lavfi -i sine=frequency=440:duration=20 \
    -c:v libx264 -preset ultrafast -c:a aac -shortest "$SAMPLE" >/dev/null 2>&1
fi

# 2) 起 API（后台），等待端口就绪
( cd "$ROOT/apps/api" && npm start >/tmp/agcs-api.log 2>&1 ) &
for _ in $(seq 1 30); do
  if curl -s "localhost:$API_PORT/api/ai-growth-clip/tasks" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

# 3) 建任务
RESP=$(curl -s -X POST "localhost:$API_PORT/api/ai-growth-clip/tasks" \
  -H 'content-type: application/json' \
  -d "{\"sourceContentId\":\"1\",\"sourceContentType\":\"episode\",\"sourceVideoUrl\":\"file://$SAMPLE\",\"title\":\"样例\",\"targetScenarios\":[\"feed\"],\"targetDurations\":[15,30],\"targetAspectRatios\":[\"9:16\"],\"targetLanguages\":[\"zh-CN\"],\"clipCount\":3}")
echo "create: $RESP"
TASK_ID=$(echo "$RESP" | sed -E 's/.*"taskId":"([^"]+)".*/\1/')

# 4) 跑一轮 worker
( cd "$ROOT/apps/worker" && DB_PATH="$DB_PATH" STORAGE_DIR="$STORAGE_DIR" python3 -m agcs_worker.main --once )

# 5) 查状态与产物
echo "task: $(curl -s localhost:$API_PORT/api/ai-growth-clip/tasks/$TASK_ID)"
echo "assets: $(curl -s localhost:$API_PORT/api/ai-growth-clip/tasks/$TASK_ID/assets)"
