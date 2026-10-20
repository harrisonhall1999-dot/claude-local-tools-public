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
    """Run a task on the free local model (Ollama) and return its answer.

    Right before calling, give the user a one-line heads-up: what you're
    sending, a time estimate, and a reminder to close Teams, Outlook and extra
    Chrome tabs. The model uses ~8 GB of this Mac's 16 GB of RAM and has
    caused freezes. Then proceed; don't wait for a reply.

    Use for mechanical work over LONG input that you would otherwise have to
    read yourself: summarizing, extracting facts/quotes/dates/names into a
    list or table, classifying, first-pass sorting or filtering. Pass files
    by path so their contents never enter your context. Do NOT use for
    legal analysis, final drafting, or anything that needs careful
    reasoning; the local model is a 12B model and makes mistakes, so spot-check
    anything that matters. Slow: roughly 10-60s per call, more for long
    input.

    Args:
        instruction: What to do. Be explicit about the output format.
        text: Optional inline input text.
        paths: Optional absolute file paths or globs (e.g. "~/Docs/*.pdf").
            Supports PDF (with OCR fallback), docx/pptx/xlsx, images (OCR)
            and plain text. All files are combined into one input.
        model: Ollama model name. Defaults to the configured local model.
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
def local_llm_batch(
    instruction: str,
    paths: list[str],
    output_dir: str = "",
    model: str = core.DEFAULT_MODEL,
    think: bool = False,
) -> str:
    """Apply the same instruction to each file separately on the local model.

    Right before calling, give the user a one-line heads-up: how many files,
    a time estimate, and a reminder to close Teams, Outlook and extra Chrome
    tabs. The model uses ~8 GB of this Mac's 16 GB of RAM and has caused
    freezes. Then proceed; don't wait for a reply.

    Use for per-document jobs over many files, e.g. "summarize each reading"
    or "pull the holding and key facts from each case". With output_dir set,
    each result is saved to <output_dir>/<file name>.md and only a short
    index comes back; open just the results you need.

    Args:
        instruction: What to do with each file. Be explicit about format.
        paths: Absolute file paths or globs (e.g. "~/Docs/Week 3/*.pdf").
        output_dir: Optional folder to write one .md result per file.
        model: Ollama model name. Defaults to the configured local model.
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
