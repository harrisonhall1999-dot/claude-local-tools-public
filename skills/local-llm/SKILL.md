---
name: local-llm
description: Offload bulk, mechanical text work (summarizing, extracting, classifying, first-pass sorting) over long documents or many files to the free local Ollama model, so the input never enters Claude's context. Use when a task means reading a lot of text to produce a much shorter output that doesn't need legal judgment, e.g. "summarize each of these 20 readings", "pull every date and party from these PDFs", "which of these files mention X".
---

# Local LLM offloading

A local model (Ollama, `gemma4:12b` by default, the largest that fits this Mac's 16 GB of RAM) runs
on this Mac. It costs no Claude usage, but it is a small model: it's slow (about 20s to load, then about 5-60s per call) and makes mistakes
(miscounts, adds unsupported details). Use it to **save Claude context on bulk reading**, not to
replace Claude's judgment.

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
asked for Claude specifically. Confidential material is fine (and a good fit), because nothing
leaves the machine.

## Give a heads-up first (not a gate)
The model takes ~8 GB of this Mac's 16 GB of RAM. When Teams, Outlook and Chrome are open, that has
frozen the machine. Right before each offload, tell the user in one or two lines:
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
