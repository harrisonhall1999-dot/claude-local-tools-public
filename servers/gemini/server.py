"""Gemini MCP server.

Lets Claude (Desktop / Code) hand bulk reading of PUBLIC material, live web
searches and image generation to Gemini through the Antigravity CLI (`agy`),
signed in with the user's Google AI Pro account. Runs in the cloud, so it uses no local RAM and no Claude usage, but
the text leaves this Mac.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.mcpserver import MCPServer

import agy

mcp = MCPServer("gemini")


@mcp.tool()
def gemini(
    instruction: str,
    text: str = "",
    paths: list[str] | None = None,
    model: str = agy.DEFAULT_MODEL,
    output_path: str = "",
) -> str:
    """Run a task on Gemini (cloud, via the Antigravity CLI) and return its answer.

    PRIVACY: the input is sent to Google and may be used for training. Use
    ONLY for public material: cases, statutes, regulations, assigned
    readings, published articles, web pages. NEVER send confidential or
    client material, unpublished drafts (e.g. the user's journal note),
    personal data, or anything the user called private; use `local_llm`
    for those. If unsure, ask the user first.

    Use for bulk, mechanical reading of long public text that you would
    otherwise read yourself: summarizing, extracting holdings/rules/quotes/
    dates into a list or table, classifying, first-pass filtering. Prefer it
    over `local_llm` for public material: it's faster (~5-60s), much
    stronger, handles very long input (~200k words per call) and needs no
    local RAM, so no heads-up about closing apps is needed. Pass files by
    path so their contents never enter your context. Do NOT use for the
    user's final legal analysis or drafts, Bluebook work, or anything you
    can't spot-check. Tell the user which parts came from Gemini.

    Args:
        instruction: What to do. Be explicit about the output format; ask
            for verbatim quotes and page numbers so you can check them.
        text: Optional inline input text.
        paths: Optional absolute file paths or globs (e.g. "~/Docs/*.pdf").
            Supports PDF (with OCR fallback), docx/pptx/xlsx, images (OCR)
            and plain text. All files are combined into one input.
        model: agy model id. Default gemini-3.8-flash-high; also
            gemini-3.8-flash-medium / -low (faster).
        output_path: Optional file to write the answer to; only a short
            note comes back, keeping long output out of your context.

    Returns:
        Gemini's answer (or a note about the file written), then a line
        naming the model and time taken.
    """
    try:
        return agy.run(instruction, text, paths, model, output_path or None)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def gemini_batch(
    instruction: str,
    paths: list[str],
    output_dir: str = "",
    model: str = agy.DEFAULT_MODEL,
) -> str:
    """Apply the same instruction to each file separately on Gemini (cloud).

    Same PRIVACY rule as `gemini`: public material only, never confidential,
    client or unpublished work (use `local_llm_batch` for those).

    Use for per-document jobs over many public files, e.g. "brief each
    assigned case" or "summarize each reading". With output_dir set, each
    result is saved to <output_dir>/<file name>.md and only a short index
    comes back; open just the results you need. ~5-60s per file.

    Args:
        instruction: What to do with each file. Be explicit about format.
        paths: Absolute file paths or globs (e.g. "~/Docs/Week 3/*.pdf").
        output_dir: Optional folder to write one .md result per file.
        model: agy model id (default gemini-3.8-flash-high).

    Returns:
        Per-file results, or an index of written files if output_dir is set.
    """
    try:
        return agy.run_batch(instruction, paths, model, output_dir or None)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def gemini_search(
    query: str,
    model: str = agy.SEARCH_MODEL,
    output_path: str = "",
) -> str:
    """Run a live web search on Gemini (Google Search) and return sourced raw results.

    NOT the default: use your own web search for ordinary lookups (it's
    faster and its snippets are real). Use this only for multi-query sweeps
    (many searches where you want a compact sourced list back) or when the
    user asks for it. Treat results as links, not text.

    Query operators run as written: "exact phrase", OR, -exclude, site:,
    filetype:, intitle:, before:/after:, parentheses. Lexis/Westlaw
    terms-and-connectors (/s, /p, pre/n, ATLEAST, SY(), DI()) do NOT work on
    the web; give the user those queries to run in Lexis/Westlaw instead.

    The query goes to Google, so keep confidential client facts out of it.
    Results are unverified: its "quotes" are sometimes paraphrased or
    misattributed and dates are often missing. Never quote from it; open the
    source (fetch_url) first, and tell the user the results came from Gemini. ~15-60s.

    Args:
        query: A natural-language question or an operator query. Add what
            you need back (e.g. "only opinions from 2025-2026").
        model: agy model id (default gemini-3.8-flash-low, fastest; use
            gemini-3.8-flash-high for hard multi-step searches).
        output_path: Optional file to write the results to; only a short
            note comes back.

    Returns:
        Numbered sourced results (or a note about the file written), then a
        line naming the model and time taken.
    """
    try:
        return agy.web_search(query, model, output_path or None)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def gemini_image(
    prompt: str,
    output_dir: str,
    count: int = 1,
) -> str:
    """Generate images with Gemini (Antigravity's image generator) and save them.

    Use this for ALL image generation requests (illustrations, diagrams as
    pictures, slide art, icons, mockups); you can't make raster images
    yourself. For charts of data or precise diagrams, build them in code or
    SVG instead, since generated images garble exact text and numbers.

    The prompt goes to Google. ~30-90s per call. Show the user the saved
    file paths (or open the image) and offer one round of revision.

    Args:
        prompt: A full brief: subject, style, composition, colors, aspect
            ratio, and any text that must appear (keep text short).
        output_dir: Folder to save the images in (created if missing), e.g.
            the user's project folder.
        count: Number of images to make (1-4).

    Returns:
        The saved image paths, one per line, then a line with the time taken.
    """
    try:
        return agy.image(prompt, output_dir, max(1, min(count, 4)))
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    mcp.run()
