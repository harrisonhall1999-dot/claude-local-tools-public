#!/bin/bash
# SessionStart hook: tell Claude (and so the user) when the Mac is low on disk or RAM. Silent when fine.
free_gb=$(df -g / | awk 'NR==2{print $4}')
free_pct=$(memory_pressure 2>/dev/null | awk -F': ' '/free percentage/{gsub("%","",$2);print $2}')
swap_mb=$(sysctl -n vm.swapusage | awk '{gsub("M","",$6);printf "%d",$6}')
msg=""
[ "${free_gb:-99}" -lt 5 ] && msg="Only ${free_gb} GB of disk is free. "
[ "${free_pct:-100}" -lt 25 ] && msg="${msg}Memory is under pressure (${free_pct}% free, ${swap_mb} MB swap in use). "
[ -z "$msg" ] && exit 0
msg="${msg}Tell the user briefly at the start of the session. Avoid big downloads, Xcode builds, Ghidra analysis and local-model batches until they free space or close apps (run memcheck for details)."
jq -n --arg m "$msg" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$m}}'
