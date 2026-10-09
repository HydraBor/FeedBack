#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
用法：./feedback.sh [start|stop|status] [选项]

  start   后台启动；不传动作时默认启动
  stop    正常关闭本项目服务
  status  查看运行状态

选项：
  --port PORT       启动端口，默认 8765（或 FEEDBACK_PORT）
  --timeout SECONDS 启动或关闭的等待时间，默认 30 秒
  --json            以 JSON 输出状态

示例：
  ./feedback.sh start
  ./feedback.sh stop
  ./feedback.sh status
  ./feedback.sh start --port 8766
EOF
}

feedback_action="${1:-start}"
case "$feedback_action" in
    -h|--help|help) usage; exit 0 ;;
    start|stop|status) ;;
    *) usage >&2; exit 2 ;;
esac
if (($#)); then shift; fi

feedback_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$feedback_root"
if [[ ! -x "$feedback_root/.venv/bin/python" ]]; then
    printf '%s\n' '尚未安装项目依赖，请先在项目目录执行：bash scripts/setup.sh' >&2
    exit 2
fi
if [[ "$feedback_action" == start && ! -f "$feedback_root/frontend/dist/index.html" ]]; then
    printf '%s\n' '前端尚未构建，请先在项目目录执行：bash scripts/setup.sh' >&2
    exit 2
fi

# The controller detaches the server session and redirects all terminal I/O.
exec "$feedback_root/.venv/bin/python" "$feedback_root/scripts/service.py" "$feedback_action" "$@"
