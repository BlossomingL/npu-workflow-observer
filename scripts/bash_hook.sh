# Source this file from ~/.bashrc AFTER installing `npu-observer`.
# It records command start/end metadata only. It never records raw keystrokes.

if [[ -n "${NPU_OBSERVER_BASH_HOOK:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
export NPU_OBSERVER_BASH_HOOK=1

__npu_obs_active=0
__npu_obs_cmd=""
__npu_obs_start_ns=0

__npu_obs_emit() {
  local name="$1" attrs="$2"
  command npu-observer event "$name" --source shell-hook --attributes "$attrs" >/dev/null 2>&1 || true
}

__npu_obs_debug_trap() {
  [[ "$__npu_obs_active" == "1" ]] && return 0
  local cmd="$BASH_COMMAND"
  case "$cmd" in
    __npu_obs_*|history*|command\ npu-observer*|npu-observer*) return 0 ;;
  esac
  __npu_obs_active=1
  __npu_obs_cmd="$cmd"
  __npu_obs_start_ns="$(date +%s%N 2>/dev/null || python - <<'PY'
import time; print(time.time_ns())
PY
)"
  local attrs
  attrs="$(python - "$PWD" "$cmd" <<'PY'
import json,sys
print(json.dumps({"cwd":sys.argv[1],"command":sys.argv[2]}, ensure_ascii=False))
PY
)"
  __npu_obs_emit shell.command.started "$attrs"
  __npu_obs_active=0
}

__npu_obs_prompt() {
  local rc=$?
  [[ -z "$__npu_obs_cmd" ]] && return 0
  __npu_obs_active=1
  local end_ns duration attrs
  end_ns="$(date +%s%N 2>/dev/null || python - <<'PY'
import time; print(time.time_ns())
PY
)"
  duration=$(( (end_ns - __npu_obs_start_ns) / 1000000 ))
  attrs="$(python - "$PWD" "$__npu_obs_cmd" "$rc" "$duration" <<'PY'
import json,sys
print(json.dumps({"cwd":sys.argv[1],"command":sys.argv[2],"exit_code":int(sys.argv[3]),"duration_ms":int(sys.argv[4])}, ensure_ascii=False))
PY
)"
  __npu_obs_emit shell.command.completed "$attrs"
  __npu_obs_cmd=""
  __npu_obs_active=0
}

trap '__npu_obs_debug_trap' DEBUG
if [[ -n "$PROMPT_COMMAND" ]]; then
  PROMPT_COMMAND="__npu_obs_prompt; $PROMPT_COMMAND"
else
  PROMPT_COMMAND="__npu_obs_prompt"
fi
