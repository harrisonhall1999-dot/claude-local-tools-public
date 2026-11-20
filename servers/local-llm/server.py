"""Local LLM MCP server.

Lets Claude (Desktop / Code) hand bulk, mechanical text work to the local
Ollama model by file path, so long inputs are processed on this machine
instead of being read into Claude's context.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.mcpserver import MCPServer

import core

mcp = MCPServer("local-llm")


@mcp.tool()
def local_llm(
    instruction: str,
    text: str = "",
    paths: list[str] | None = None,
    model: str = core.DEFAULT_MODEL,
    think: bool = False,
) -> str:
    """Run a task on a free model and return its answer.

    Tries the Ollama cloud model first (fast, no local RAM, text leaves the
    Mac: for confidential material pass model="apple-fm" or "qwen-offload"
    unless the user has said cloud offload is fine). When the cloud errors or
    hits its limit, DeepSeek's API takes over (cloud, no local RAM; sign-up
    credit, then the user's prepaid balance; skipped when it has no key or
    no balance). Then Apple's on-device model (apple-fm, ~200 MB RAM, ~30k
    chars per piece), and the local qwen-offload model (~6 GB RAM) runs only
    if Apple's model refuses or is unavailable.
    The footer names the model that answered. Before a big job, call
    local_llm_status (instant, loads nothing); only if it says LOCAL give the
    user a one-line heads-up to close Teams, Outlook and extra Chrome tabs
    (this Mac has 16 GB of RAM), then proceed without waiting.

    Use for mechanical work over LONG input that you would otherwise have to
    read yourself: summarizing, extracting facts/quotes/dates/names into a
    list or table, classifying, first-pass sorting or filtering. Pass files
    by path so their contents never enter your context. Do NOT use for
    legal analysis, final drafting, or anything that needs careful
    reasoning; these are small models and make mistakes, so spot-check
    anything that matters. apple-fm is weak at arithmetic and can mislabel
    mixed outcomes (it called "granted in part" "denied in part"), so don't
    rely on it for sums or rulings. Cloud: ~1-5s per call. apple-fm: ~1-7s.
    Local qwen-offload: roughly 10-60s per call, more for long input.

    Args:
        instruction: What to do. Be explicit about the output format.
        text: Optional inline input text.
        paths: Optional absolute file paths or globs (e.g. "~/Docs/*.pdf").
            Supports PDF (with OCR fallback), docx/pptx/xlsx, images (OCR)
            and plain text. All files are combined into one input.
        model: Default "auto" = FreeLLMAPI (free router), cloud, DeepSeek,
            apple-fm, the user's PCs over Tailscale (if awake), then
            qwen-offload. Or name one: "free", "deepseek", "apple-fm", "pc",
            or any Ollama model.
        think: Let the model reason before answering (slower, better on
            multi-step tasks).

    Returns:
        The model's answer, followed by a line naming the model and time taken.
    """
    try:
        return core.run(instruction, text, paths, model, think)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def local_llm_status() -> str:
    """Say whether the next local_llm call runs on the cloud model or LOCAL.

    Instant and free: loads no model and calls no API. Use it before a big
    offload to decide whether the user needs the close-apps heads-up (only
    when it says LOCAL). Also reports cloud tokens used since the free
    allowance last reset, DeepSeek tokens used, and why either is paused.
    """
    try:
        return core.status()
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def local_llm_batch(
    instruction: str,
    paths: list[str],
    output_dir: str = "",
    model: str = core.DEFAULT_MODEL,
    think: bool = False,
) -> str:
    """Apply the same instruction to each file separately on a cheap model (cloud, then DeepSeek, then Apple on-device, then local).

    Call local_llm_status first (instant). Only if it says LOCAL, give the
    user a one-line heads-up: how many files, a time estimate, and a reminder
    to close Teams, Outlook and extra Chrome tabs (the local model uses ~6 GB
    of this Mac's 16 GB of RAM). Then proceed; don't wait for a reply.

    Use for per-document jobs over many files, e.g. "summarize each reading"
    or "pull the holding and key facts from each case". With output_dir set,
    each result is saved to <output_dir>/<file name>.md and only a short
    index comes back; open just the results you need.

    Args:
        instruction: What to do with each file. Be explicit about format.
        paths: Absolute file paths or globs (e.g. "~/Docs/Week 3/*.pdf").
        output_dir: Optional folder to write one .md result per file.
        model: Default "auto" = FreeLLMAPI (free router), cloud, DeepSeek,
            apple-fm, the user's PCs over Tailscale (if awake), then
            qwen-offload. Or name one: "free", "deepseek", "apple-fm", "pc",
            or any Ollama model.
        think: Let the model reason before answering (slower).

    Returns:
        Per-file results, or an index of written files if output_dir is set.
    """
    try:
        return core.run_batch(instruction, paths, model, think, output_dir or None)
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    mcp.run()
