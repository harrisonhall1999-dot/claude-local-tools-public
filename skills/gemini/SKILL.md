---
name: gemini
description: Hand work to Gemini via the Antigravity CLI. Use for every image-generation request (gemini_image), and bulk reading of PUBLIC material such as cases, statutes, readings and web pages (gemini / gemini_batch), e.g. "make an image of...", "brief each of these 12 cases". Also gemini_search for multi-query web sweeps (not ordinary searches). Never send confidential, client or unpublished material.
---

# Gemini offloading

Gemini runs in Google's cloud through the Antigravity CLI (`agy`), signed in with the user's Google
AI Pro account. It costs no Claude usage and no local RAM, is fast (about 5-60s per call) and is much
stronger than the local model. **But the input leaves the Mac** and may be used by Google for
training.

## Pick the route

| Material | Route |
|---|---|
| Public: cases, statutes, regs, assigned readings, published articles, web pages | `gemini` / `gemini_batch` |
| Confidential, client facts, unpublished drafts (journal note, memos, briefs), personal data, anything the user called private | `local_llm` / `local_llm_batch` (nothing leaves the Mac) |
| Unsure | ask the user, or use `local_llm` |

## When to offload at all
Same bar as `local-llm`: the input is large (more than ~15k words or ~5 files), the task is mechanical
(summarize, extract, classify, filter, first pass), you don't need to read the input yourself anyway,
and the output is much smaller than the input. Never offload the user's legal analysis or
conclusions, final drafts, or Bluebook/citation work.

No RAM heads-up is needed (it doesn't run on the Mac). Just say in one line what you're sending to
Gemini.

## How

**MCP tools** (Claude Code and the Desktop Chat tab):
- `gemini(instruction, paths=[...] | text=..., output_path=...)`: one combined answer (up to
  ~200k words per call). `output_path` writes long answers to a file.
- `gemini_batch(instruction, paths=[...], output_dir=...)`: one result per file.

**CLI** (Claude Code Bash; `run_in_background` for many files):
```bash
gemini-offload "instruction" "~/path/*.pdf"                  # one combined answer
gemini-offload "instruction" --batch "~/dir/*.pdf" --out DIR  # one .md per file
```
Files are read on the Mac (PDF with OCR fallback, docx/pptx/xlsx, images, text) and inlined, so
Gemini never gets file or shell access.

## Web search: `gemini_search`
Not the default: use your own web search for ordinary lookups (faster, real snippets). Use
`gemini_search` only for multi-query sweeps where you want a compact sourced list back, or when the
user asks. Treat results as links, not text. Operators (`"exact phrase"`, OR, `-term`, `filetype:`)
run as written; `site:` often returns NONE, so put the site name in the query instead.
- Lexis/Westlaw terms-and-connectors (`/s`, `/p`, `pre/n`, `ATLEAST`, `SY()`, `DI()`) don't work on the
  web. Give the user those queries to run in Lexis/Westlaw.
- Its "quotes" are sometimes paraphrased or misattributed and dates are often missing. Never quote
  from it; open the source with `fetch_url` first.
- Default model is `gemini-3.8-flash-low` (~15s). Pass `gemini-3.8-flash-high` for hard
  multi-step searches (slower, sometimes minutes).
- Keep client facts out of the query.

## Images: `gemini_image`
Use it for every image-generation request: `gemini_image(prompt, output_dir, count)` saves JPEGs
and returns their paths (~30-90s). Write a full brief (subject, style, composition, colors, aspect
ratio). For data charts or diagrams with exact text, build them in code/SVG instead, since generated
images garble text.

## Writing the instruction
- Be explicit about output format. Ask for verbatim quotes of rules and tests, with page numbers.
- Tell it to write NONE when it finds nothing.

## After it returns
- Spot-check 1-2 claims against the source, more if the stakes are high.
- Tell the user which parts came from Gemini; never present it as verified.
- If it errors with a sign-in message, tell the user to run `agy` in Terminal and sign in again.
