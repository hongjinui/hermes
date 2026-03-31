# Claude Code Statusline 설정

## 목적
다른 컴퓨터에서도 동일한 Claude Code statusline을 빠르게 세팅하기 위한 가이드.

## 전제 조건
- `jq` 설치 필요 (`brew install jq` / `apt install jq`)
- Claude Code CLI 설치 완료

## 설정 절차

### 1. 스크립트 파일 생성

`~/.claude/statusline-command.sh` 파일을 아래 내용으로 생성:

```sh
#!/bin/sh
input=$(cat)

# Helper: format token count (e.g., 80000 → 80K, 1000000 → 1M)
fmt_tokens() {
  if [ "$1" -ge 1000000 ] 2>/dev/null; then
    echo "$1" | awk '{printf "%.1fM", $1/1000000}'
  elif [ "$1" -ge 1000 ] 2>/dev/null; then
    echo "$1" | awk '{printf "%.0fK", $1/1000}'
  else
    echo "$1"
  fi
}

dim="\033[2m"
reset="\033[0m"
sep="${dim}│${reset}"

# ── 1. Model ──
model=$(echo "$input" | jq -r '.model.display_name // ""')
if [ -n "$model" ]; then
  model_part="\033[1;35m${model}${reset}"
else
  model_part=""
fi

# ── 2. Context window (colored + token stats) ──
remaining=$(echo "$input" | jq -r '.context_window.remaining_percentage // empty')
window_size=$(echo "$input" | jq -r '.context_window.context_window_size // empty')
used_pct=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
ctx_part=""
if [ -n "$remaining" ]; then
  remaining_int=$(printf "%.0f" "$remaining")
  if [ "$remaining_int" -le 10 ]; then
    ctx_color="\033[1;31m"; ctx_icon="🔴"
  elif [ "$remaining_int" -le 30 ]; then
    ctx_color="\033[0;31m"; ctx_icon="🟠"
  elif [ "$remaining_int" -le 50 ]; then
    ctx_color="\033[0;33m"; ctx_icon="🟡"
  else
    ctx_color="\033[0;32m"; ctx_icon="🟢"
  fi
  if [ -n "$window_size" ] && [ -n "$used_pct" ]; then
    used_tokens=$(echo "$window_size $used_pct" | awk '{printf "%.0f", $1 * $2 / 100}')
    used_fmt=$(fmt_tokens "$used_tokens")
    total_fmt=$(fmt_tokens "$window_size")
    ctx_part="${ctx_color}${ctx_icon} ctx:${remaining_int}% (${used_fmt}/${total_fmt})${reset}"
  else
    ctx_part="${ctx_color}${ctx_icon} ctx:${remaining_int}%${reset}"
  fi
fi

# ── 3. Session cost ──
cost=$(echo "$input" | jq -r '.cost.total_cost_usd // empty')
cost_part=""
if [ -n "$cost" ]; then
  cost_fmt=$(echo "$cost" | awk '{printf "$%.2f", $1}')
  cost_part="${dim}💰${cost_fmt}${reset}"
fi

# ── 4. Session duration ──
duration_ms=$(echo "$input" | jq -r '.cost.total_duration_ms // empty')
duration_part=""
if [ -n "$duration_ms" ]; then
  total_sec=$(echo "$duration_ms" | awk '{printf "%.0f", $1/1000}')
  if [ "$total_sec" -ge 3600 ]; then
    h=$((total_sec / 3600))
    m=$(((total_sec % 3600) / 60))
    duration_part="${dim}⏱ ${h}h${m}m${reset}"
  elif [ "$total_sec" -ge 60 ]; then
    m=$((total_sec / 60))
    s=$((total_sec % 60))
    duration_part="${dim}⏱ ${m}m${s}s${reset}"
  else
    duration_part="${dim}⏱ ${total_sec}s${reset}"
  fi
fi

# ── 5. Code changes ──
lines_added=$(echo "$input" | jq -r '.cost.total_lines_added // empty')
lines_removed=$(echo "$input" | jq -r '.cost.total_lines_removed // empty')
code_part=""
if [ -n "$lines_added" ] || [ -n "$lines_removed" ]; then
  added="${lines_added:-0}"
  removed="${lines_removed:-0}"
  if [ "$added" -gt 0 ] || [ "$removed" -gt 0 ]; then
    code_part="\033[0;32m+${added}${reset}/\033[0;31m-${removed}${reset}"
  fi
fi

# ── 6. Rate limits (5hr / 7day) with reset countdown ──
rate_5h=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
rate_7d=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
reset_5h=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
reset_7d=$(echo "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')
now=$(date +%s)

# Helper: seconds until reset → human readable
fmt_countdown() {
  left=$(($1 - now))
  if [ "$left" -le 0 ]; then
    echo "now"
  elif [ "$left" -ge 3600 ]; then
    echo "$((left / 3600))h$((left % 3600 / 60))m"
  elif [ "$left" -ge 60 ]; then
    echo "$((left / 60))m"
  else
    echo "${left}s"
  fi
}

rate_part=""
if [ -n "$rate_5h" ] || [ -n "$rate_7d" ]; then
  r5=$(printf "%.0f" "${rate_5h:-0}")
  r7=$(printf "%.0f" "${rate_7d:-0}")
  # Color for 5h rate
  if [ "$r5" -ge 80 ]; then r5_color="\033[1;31m"
  elif [ "$r5" -ge 50 ]; then r5_color="\033[0;33m"
  else r5_color="\033[0;32m"
  fi
  # Color for 7d rate
  if [ "$r7" -ge 80 ]; then r7_color="\033[1;31m"
  elif [ "$r7" -ge 50 ]; then r7_color="\033[0;33m"
  else r7_color="\033[0;32m"
  fi
  # Build 5h part with countdown (show countdown when >= 50%)
  r5_str="5h:${r5_color}${r5}%${reset}"
  if [ -n "$reset_5h" ] && [ "$r5" -ge 50 ]; then
    r5_ttl=$(fmt_countdown "$reset_5h")
    r5_str="${r5_str}${dim}(${r5_ttl})${reset}"
  fi
  # Build 7d part with countdown (show countdown when >= 50%)
  r7_str="7d:${r7_color}${r7}%${reset}"
  if [ -n "$reset_7d" ] && [ "$r7" -ge 50 ]; then
    r7_ttl=$(fmt_countdown "$reset_7d")
    r7_str="${r7_str}${dim}(${r7_ttl})${reset}"
  fi
  rate_part="⚡${r5_str} ${r7_str}"
fi

# ── Assemble ──
parts=""
for p in "$model_part" "$ctx_part" "$cost_part" "$duration_part" "$code_part" "$rate_part"; do
  if [ -n "$p" ]; then
    if [ -n "$parts" ]; then
      parts="${parts} ${sep} ${p}"
    else
      parts="${p}"
    fi
  fi
done

printf '%b\n' "$parts"
```

### 2. settings.json에 등록

`~/.claude/settings.json`에 아래 항목 추가:

```json
{
  "statusLine": {
    "type": "command",
    "command": "sh ~/.claude/statusline-command.sh"
  }
}
```

또는 Claude Code 안에서 `/statusline` 명령 후 위 스크립트 경로를 지정.

## 표시 항목

```
Opus 4.6 │ 🟢 ctx:92% (80K/1M) │ 💰$0.42 │ ⏱ 23m │ +45/-12 │ ⚡5h:15% 7d:8%
```

| 항목 | 소스 필드 | 설명 |
|------|-----------|------|
| 모델명 | `model.display_name` | 현재 사용 중인 모델 (보라색) |
| 컨텍스트 | `context_window.*` | 남은 비율 + 사용/전체 토큰 (색상 변화) |
| 세션 비용 | `cost.total_cost_usd` | 이 세션에서 소비한 비용 |
| 세션 시간 | `cost.total_duration_ms` | 세션 경과 시간 |
| 코드 변경 | `cost.total_lines_added/removed` | 추가(초록)/삭제(빨강) 라인 수 |
| Rate Limit | `rate_limits.*` | 5시간/7일 사용량 + 리셋 카운트다운 |

## 색상 기준

### 컨텍스트 잔량
| 조건 | 아이콘 | 색상 | 의미 |
|------|--------|------|------|
| > 50% | 🟢 | 초록 | 여유 |
| 31~50% | 🟡 | 노랑 | 절반 소진 |
| 11~30% | 🟠 | 빨강 | 주의 — `/compact` 고려 |
| ≤ 10% | 🔴 | 굵은 빨강 | 위험 — `/compact` 또는 새 세션 권장 |

### Rate Limit
| 조건 | 색상 | 카운트다운 |
|------|------|-----------|
| < 50% | 초록 | 숨김 |
| 50~79% | 노랑 | 리셋까지 남은 시간 표시 |
| ≥ 80% | 빨강 | 리셋까지 남은 시간 표시 |

## 주의사항

- **`printf` 주의**: ANSI 이스케이프가 포함된 변수를 출력할 때 반드시 `printf '%b\n'`을 사용. `printf "$var"`는 `\`를 포맷 문자로 해석해서 간헐적 오류 발생 → statusline이 사라지는 원인이 됨.
- **Rate Limit**: Claude.ai Pro/Max 구독자만 데이터가 제공됨. API 키 사용자는 해당 섹션이 자동 숨김.
- **데이터 없는 항목**: 각 섹션은 데이터가 없으면 자동 생략되어 깔끔하게 유지됨.
