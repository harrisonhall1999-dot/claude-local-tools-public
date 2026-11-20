# Global preferences (starter template)

## Local tools on this Mac
A set of local tools ("Claude Local Tools") runs on this Mac for free and keeps files private. Prefer them when
they fit; they do heavy or bulk work locally so Claude spends context on judgment, not raw reading.

- **Bulk reading -> `local_llm` / `local_llm_batch`**: offload summarizing, extracting, classifying or filtering across
  long documents or many files instead of reading them into context. Keep judgment, final drafting, and anything
  you can't verify. Spot-check its output and say which parts came from the local model.
- **Bulk reading of public material -> `gemini` / `gemini_batch`** (if set up): the text goes to Google, so never send
  confidential or unpublished material. The app cancels an MCP tool call after about 60 s, so for big jobs run
  `gemini-offload` from Bash in the background and write the results to files. **Image generation -> `gemini_image`.**
- **Chaining tools in Claude Code -> `localtools`**: when a job needs 3+ tool calls, a loop, or filtering big tool
  output, write one Python script (`import localtools as lt`; `localtools run <script>`) and print only the result.
- **Finding things in documents -> `search_docs`**: locate relevant passages instead of opening whole folders.
- **Recordings -> `transcribe`**: ask for speaker count, names and key terms first.
- **Downloading from a link -> `fetch_media`**; **anything -> Markdown -> `to_markdown`**.
- **Files -> `ocr`, `read_document`, `convert`, `pdf_ocr`, `pdf_tool`.**

**Before running anything that loads a local model** (the offload model, Whisper, OCR, or indexing), give a one-line
heads-up (what you're sending, a rough time estimate, and a reminder to close big apps) and then go ahead.
