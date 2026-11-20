---
name: local-llm
description: Offload bulk, mechanical text work (summarizing, extracting, classifying, first-pass sorting) over long documents or many files to the free local Ollama model, so the input never enters Claude's context. Use when a task means reading a lot of text to produce a much shorter output that doesn't need legal judgment, e.g. "summarize each of these 20 readings", "pull every date and party from these PDFs", "which of these files mention X".
---

# Local LLM offloading

Free models do the bulk reading. `local_llm` tries the Ollama cloud model `cloud-offload` first
(about 1-5s per call, no local RAM; the text leaves the Mac). When the cloud errors or its free limit is hit, DeepSeek's API takes over (also cloud, no
local RAM; runs on a one-time sign-up credit, then the user's prepaid balance, and is skipped when the
balance is empty). After that, Apple's on-device model `apple-fm` (the
`fm` command built into macOS 27, about 1-7s per call, ~200 MB of RAM, ~30k characters per piece)
takes over, and the local `qwen-offload` (abliterated Qwen3.5 9B, about 20s to load, then 5-60s per
call) runs only if Apple's model refuses or is unavailable. The result footer names the model that
answered. They are small models and make mistakes (miscounts, adds unsupported details; `apple-fm`
is weak at arithmetic and once labelled "granted in part" as "denied in part"). Use them to **save
Claude context on bulk reading**, not to replace Claude's judgment.

## When to offload

Offload only when **all** of these hold:
1. **The input is large**: more than ~15k words in total, or more than ~5 files. For short input,
   doing the task yourself is cheaper than writing the instruction and checking the result.
2. **The task is mechanical**: summarize, extract into a list or table, classify or tag, filter
   ("which files mention X"), reformat, or a first rough pass.
3. **You don't need to read the input yourself** anyway. If you must read it to do the real work,
   delegating just adds a step.
4. **The output is much smaller than the input**, or goes straight to files you won't read in full.

Never offload: legal analysis or conclusions, final drafts the user will submit or send, citation or
Bluebook work, anything where an error would hurt and you can't verify it, or tasks where the user
asked for Claude specifically. The first tiers are cloud models, so for confidential material pass `model="apple-fm"` or
`model="qwen-offload"` (nothing leaves the Mac) unless the user has said cloud offload is fine. To keep
every call local, set `LOCAL_LLM_FREE_MODEL`, `LOCAL_LLM_CLOUD_MODEL` and `LOCAL_LLM_DEEPSEEK_MODEL` to empty.

## Give a heads-up first (not a gate)
Call `local_llm_status` first (instant, loads nothing). Only if it says LOCAL (cloud paused and
Apple's model unavailable, or you chose `model="qwen-offload"`) is the heads-up needed:
`qwen-offload` takes ~6 GB of this Mac's 16 GB of RAM, and with Teams, Outlook and Chrome open that
has frozen the machine. `apple-fm` is light and needs no heads-up. Right before such an offload, tell the user in one or two lines:
- what you're sending (how many files and roughly how many pages or words) and a rough time estimate
  (about 20s to load, plus about 5-60s per file or chunk)
- a reminder to close Teams, Outlook and extra Chrome tabs if they can, since the Mac may slow down
  while it runs

Then proceed. Don't wait for a reply.

## How

**MCP tools** (Claude Code and the Desktop Chat tab), when available:
- `local_llm(instruction, paths=[...] | text=...)`: one combined answer.
- `local_llm_batch(instruction, paths=[...], output_dir=...)`: one result per file. Use
  `output_dir` for many files, and read only what you need.

**CLI** (Claude Code Bash; use `run_in_background` for more than a few files):
```bash
local-llm "instruction" "~/path/*.pdf"                 # one combined answer
local-llm "instruction" --batch "~/dir/*.pdf" --out DIR # one .md per file
cat file.txt | local-llm "instruction"                 # piped text
```
Both handle PDF (with an OCR fallback), docx/pptx/xlsx, images and text, and split long input into
chunks automatically. Add `think=true` / `--think` for multi-step tasks (slower).

## Writing the instruction
- Be explicit about the output format (e.g. "a markdown table with columns ...", or "one line per item").
- Ask it to quote or cite page numbers for extracted facts, so you can check them.
- Tell it what to do when it finds nothing ("write NONE"), so it doesn't make something up.

## After it returns
- Spot-check: open 1-2 sources and confirm a few claims, more if the stakes are high.
- Tell the user which parts came from the local model. Never present its output as verified.
- If the output is poor, do the task yourself instead of retrying repeatedly.
