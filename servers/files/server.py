"""Local file/media utilities MCP server.

Thin, well-defaulted wrappers around tools already on this Mac (pandoc,
ImageMagick, ocrmypdf, PyMuPDF, yt-dlp, gallery-dl) so Claude can convert documents, OCR
scanned PDFs, split/merge PDFs, and download media from any link - and chain them (e.g.
fetch_media -> transcribe, or pdf_ocr -> read_document) without the file's
contents passing through Claude.
"""

import glob
import os
import sys
import shutil
import subprocess

from mcp.server.mcpserver import MCPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

mcp = MCPServer("files")

# Homebrew tools aren't always on PATH for processes Claude spawns.
os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")


def _run(cmd, timeout=1800):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        return (p.stderr or p.stdout or f"exit {p.returncode}").strip()
    return None


def _default_out(path, new_ext):
    base = os.path.splitext(os.path.expanduser(path))[0]
    return f"{base}{new_ext}"


# pandoc writer name -> output extension, for the formats worth exposing.
_CONVERT = {
    "markdown": ".md", "gfm": ".md", "docx": ".docx", "html": ".html",
    "rtf": ".rtf", "latex": ".tex", "plain": ".txt", "epub": ".epub",
    "pdf": ".pdf",
}


# ImageMagick target name -> output extension.
_IMAGE = {
    "png": ".png", "jpg": ".jpg", "jpeg": ".jpg", "webp": ".webp", "heic": ".heic",
    "avif": ".avif", "gif": ".gif", "tiff": ".tiff", "bmp": ".bmp", "ico": ".ico",
}
_IMAGE_IN = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".avif", ".gif",
             ".tif", ".tiff", ".bmp", ".ico", ".svg", ".jxl"}


def _image_sources(path):
    """A file, folder (its images) or glob -> sorted image paths."""
    path = os.path.expanduser(path)
    if os.path.isdir(path):
        files = [os.path.join(path, f) for f in os.listdir(path)]
    elif os.path.isfile(path):
        return [path]
    else:
        files = glob.glob(path)
    return sorted(f for f in files if os.path.isfile(f)
                  and os.path.splitext(f)[1].lower() in _IMAGE_IN)


def _convert_images(path, to, output_path, resize, quality):
    if not shutil.which("magick"):
        return "Error: ImageMagick isn't installed (`brew install imagemagick`)."
    srcs = _image_sources(path)
    if not srcs:
        return f"Error: no images found at {path}"
    opts = ["-auto-orient"]
    if resize:
        opts += ["-resize", resize]
    if quality:
        opts += ["-quality", str(quality)]
    out = os.path.expanduser(output_path) if output_path else ""
    # Several images -> one PDF when output_path names a .pdf file.
    if to == "pdf" and len(srcs) > 1 and out.lower().endswith(".pdf"):
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        err = _run(["magick", *srcs, *opts, out])
        return f"Error: magick: {err}" if err else f"Wrote {out} ({len(srcs)} pages)"
    ext = ".pdf" if to == "pdf" else _IMAGE[to]
    single = len(srcs) == 1 and not os.path.isdir(out)
    written, errors = [], []
    for src in srcs:
        if single and out:
            dest = out
        elif out:
            dest = os.path.join(out, os.path.splitext(os.path.basename(src))[0] + ext)
        else:
            dest = _default_out(src, ext)
        if dest in written:  # b.heic and b.jpg both -> b.webp: keep both
            dest = os.path.splitext(dest)[0] + os.path.splitext(src)[1].replace(".", "-") + ext
        if os.path.abspath(dest) == os.path.abspath(src):
            errors.append(f"{src}: already {to}; pass output_path")
            continue
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        err = _run(["magick", src, *opts, dest])
        (errors.append(f"{src}: {err}") if err else written.append(dest))
    lines = [f"Wrote {len(written)} file(s):", *written[:50]]
    if len(written) > 50:
        lines.append(f"... and {len(written) - 50} more")
    if errors:
        lines += [f"Error on {len(errors)}:", *errors[:20]]
    return "\n".join(lines) if written else "Error: " + "; ".join(errors[:20])


@mcp.tool()
def convert(path: str, to: str, output_path: str = "", resize: str = "",
            quality: int = 0) -> str:
    """Convert a document (pandoc) or images (ImageMagick) to another format, locally.

    Documents: good for producing a finished deliverable (e.g. a Markdown draft
    -> .docx). To turn a source INTO Markdown (PDF, Word, web page...), use
    to_markdown instead: it keeps legal structure and checks nothing was lost.
    Document targets: markdown, gfm, docx, html, rtf, latex, plain, epub, pdf.
    PDF output needs a PDF engine (weasyprint/wkhtmltopdf/tectonic/pdflatex);
    if none is installed the error says so - convert to docx or html instead.

    Images (HEIC, PNG, JPG, WebP, AVIF, GIF, TIFF, BMP, SVG...): targets png,
    jpg, webp, heic, avif, gif, tiff, bmp, ico, or pdf. `path` may be one
    image, a folder, or a glob, so a whole batch is one call; photos are
    rotated upright from their EXIF orientation. Several images with to="pdf"
    and an output_path ending in .pdf become ONE multi-page PDF (e.g. phone
    photos of handouts -> a PDF; run pdf_ocr on it after to make it
    searchable). Not for PDF -> image (needs Ghostscript) or text from images
    (use ocr).

    Args:
        path: Absolute path to the source file (images: also a folder or glob).
        to: Target format (see lists above).
        output_path: Output file; for a batch of images, an output folder.
            Defaults to each source's name with the new extension, beside it.
        resize: Images only, ImageMagick geometry: "1600x1600>" (shrink to fit,
            never enlarge), "50%", "800x" (width 800).
        quality: Images only, 1-100 for jpg/webp/heic/avif (0 = default).

    Returns:
        Where the converted file(s) were written.
    """
    to = to.lower().lstrip(".")
    src = os.path.expanduser(path)
    is_image_src = (os.path.splitext(src)[1].lower() in _IMAGE_IN or os.path.isdir(src)
                    or any(c in src for c in "*?["))
    if to in _IMAGE or (to == "pdf" and is_image_src):
        return _convert_images(path, to, output_path, resize, quality)
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return f"Error: file not found: {path}"
    if to not in _CONVERT:
        return (f"Error: unsupported target '{to}' (documents: {', '.join(_CONVERT)}; "
                f"images: {', '.join(_IMAGE)}, pdf)")
    out = os.path.expanduser(output_path) if output_path else _default_out(path, _CONVERT[to])
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    cmd = ["pandoc", path, "-o", out]
    if to in ("markdown", "gfm"):
        cmd += ["-t", "gfm"]
    if to == "pdf":
        engine = next((e for e in ("weasyprint", "wkhtmltopdf", "tectonic", "pdflatex")
                       if shutil.which(e)), None)
        if not engine:
            return ("Error: PDF output needs a PDF engine. Install one "
                    "(`uv pip install --python .venv/bin/python weasyprint`) or convert to docx/html.")
        cmd += [f"--pdf-engine={engine}"]
    err = _run(cmd)
    return f"Error: pandoc: {err}" if err else f"Wrote {out}"


@mcp.tool()
def pdf_ocr(path: str, output_path: str = "") -> str:
    """Add a searchable text layer to a scanned PDF (ocrmypdf, local).

    Makes a scanned casebook chapter or court filing Cmd-F searchable and
    readable by read_document without vision tokens. Skips pages that already
    have text. Uses ~1-2 GB of RAM briefly; give the user a one-line heads-up
    first per the project rules.

    Args:
        path: Absolute path to the PDF.
        output_path: Output PDF; defaults to "<name> (searchable).pdf".

    Returns:
        Where the searchable PDF was written.
    """
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return f"Error: file not found: {path}"
    out = os.path.expanduser(output_path) if output_path else _default_out(path, " (searchable).pdf")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    err = _run(["ocrmypdf", "--skip-text", "--optimize", "1", path, out])
    return f"Error: ocrmypdf: {err}" if err else f"Wrote {out}"


@mcp.tool()
def pdf_tool(operation: str, paths: list[str], output_path: str = "", pages: str = "") -> str:
    """Split, merge, or extract pages from PDFs (PyMuPDF, local).

    Args:
        operation: "merge" (join paths in order into one PDF), "extract" (pull
            `pages` from the first path into a new PDF), or "split" (write one
            PDF per page of the first path into output_path's folder).
        paths: Absolute PDF path(s) or globs.
        output_path: Output file (merge/extract) or folder (split); has a default.
        pages: For extract, e.g. "1-3,7,10-12" (1-based, inclusive).

    Returns:
        What was written.
    """
    import fitz  # PyMuPDF

    files = []
    for p in paths:
        p = os.path.expanduser(p)
        files += sorted(glob.glob(p)) if any(c in p for c in "*?[") else [p]
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        return "Error: no input PDFs found"

    try:
        if operation == "merge":
            out = os.path.expanduser(output_path) if output_path else _default_out(files[0], " (merged).pdf")
            doc = fitz.open()
            for f in files:
                with fitz.open(f) as src:
                    doc.insert_pdf(src)
            doc.save(out)
            return f"Wrote {out} ({doc.page_count} pages from {len(files)} files)"

        if operation == "extract":
            if not pages:
                return "Error: extract needs `pages`, e.g. \"1-3,7\""
            want = []
            for part in pages.split(","):
                part = part.strip()
                if "-" in part:
                    a, b = part.split("-", 1)
                    want += list(range(int(a), int(b) + 1))
                elif part:
                    want.append(int(part))
            out = os.path.expanduser(output_path) if output_path else _default_out(files[0], f" (p{pages}).pdf")
            with fitz.open(files[0]) as src:
                doc = fitz.open()
                for n in want:
                    if 1 <= n <= src.page_count:
                        doc.insert_pdf(src, from_page=n - 1, to_page=n - 1)
            doc.save(out)
            return f"Wrote {out} ({doc.page_count} pages)"

        if operation == "split":
            out_dir = os.path.expanduser(output_path) if output_path else _default_out(files[0], "_pages")
            os.makedirs(out_dir, exist_ok=True)
            with fitz.open(files[0]) as src:
                width = len(str(src.page_count))
                for i in range(src.page_count):
                    one = fitz.open()
                    one.insert_pdf(src, from_page=i, to_page=i)
                    one.save(os.path.join(out_dir, f"p{str(i + 1).zfill(width)}.pdf"))
            return f"Wrote {src.page_count} pages to {out_dir}"

        return f"Error: unknown operation '{operation}' (use merge, extract, split)"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def to_markdown(sources: list[str], output_dir: str = "", output_path: str = "",
                overwrite: bool = False, keep_links: bool = False) -> str:
    """Convert files or web pages to Markdown files on disk, structure intact.

    The default way to turn a source into Markdown, especially a legal one
    (opinion, statute, regulation, law review article, brief, outline). The
    text never enters Claude's context: only the saved path and a short
    report come back. Then read just the parts you need, or hand the file to
    local_llm/gemini/verify_quotes by path.

    Keeps what accuracy depends on: headings, statute/regulation paragraph
    markers ((a), (1), (A), (i)), block quotes, italics (case names, signals,
    emphasis), tables, Word footnotes as [^n] notes, star paging and footnote
    markers on court sites, and <!-- page N --> before each PDF page for pin
    cites (the printed page label when the PDF has one). Word tracked changes
    are accepted; comments are dropped.

    Each result has a fidelity score: the share of the source's words found
    in the Markdown, checked against an independent plain-text read. Below
    98% it's flagged with a sample of the missing words; tell the user and
    check those parts against the original before relying on them. For web
    pages it also says how much of the page was kept (menus and sidebars are
    dropped; the whole <main>/<article> is kept, never trimmed by guesswork).

    Handles: .pdf, .docx, .pptx, .xlsx, .odt, .epub, .html, .tex, .csv, .rtf,
    .doc (via macOS textutil, which loses footnotes), .txt/.md, folders and
    globs, and http(s) URLs: web pages, or links straight to a PDF/Word file.
    Fast and local (~10 s for a 100-page opinion). PDFs use a small layout
    model (~0.5 GB for a few seconds, released after each batch), so no
    heads-up is needed for a few files; give one for a folder of big PDFs. Scanned PDF pages
    have no text: it says which; run pdf_ocr first. Pages that need
    JavaScript or a bot check (e.g. CourtListener) fail with a clear error;
    use that site's connector or a PDF link instead. Better than fetch_url
    whenever the text will be saved, quoted or cited.

    Args:
        sources: File paths, folders, globs ("~/Readings/*.pdf") and/or URLs.
        output_dir: Where to write. Default: next to each file; ~/Downloads
            for URLs.
        output_path: Exact output file (one source only).
        overwrite: Replace an existing .md instead of adding " (1)".
        keep_links: Keep hyperlinks from web pages as [text](url). Off by
            default (defined-term and cite links are mostly noise).

    Returns:
        One line per source: the .md path, word/page/heading/footnote counts,
        the fidelity score, and any warnings.
    """
    from tomd import to_markdown as run
    return run(sources, output_dir, output_path, overwrite, keep_links)


@mcp.tool()
def fetch_media(url: str, kind: str = "auto", output_dir: str = "", playlist: bool = False,
                max_items: int = 50, max_height: int = 0, language: str = "en",
                cookies_from_browser: str = "") -> str:
    """Download the media behind any web link: video, audio, images, captions or a file.

    One tool for "grab this link". It routes the URL itself: a direct file link
    (.mp3/.mp4/.pdf/.jpg/.zip...) is downloaded as-is; a page with video or audio
    (YouTube, Vimeo, podcasts, news sites, lecture players, embedded HLS; ~1,800
    sites) goes to yt-dlp; an image post or gallery (Instagram, X, Reddit,
    Imgur, Flickr...) goes to gallery-dl. Runs locally, no tokens; only the
    saved paths come back. Not for article text (use fetch_url), and not for
    content the user isn't allowed to download.

    Before transcribing an online video, try kind="subtitles" first: if the
    site has captions you get a timestamped transcript in seconds with no
    Whisper run. Use kind="info" to see what a link offers without
    downloading: duration, each resolution with an estimated size, caption
    languages, playlist size. Check it before a big video download.

    Long downloads (a whole playlist, hours of video) can outlast the tool call;
    in a shell run `fetch-media URL ...` in the background instead.

    Args:
        url: The page or file URL.
        kind: "auto" (default: the file, else the video, else the images),
            "audio" (best audio as .m4a, for transcribe), "video" (.mp4),
            "images" (gallery-dl), "file" (plain download, no extractors),
            "subtitles" (captions saved as a [mm:ss] .txt transcript), or
            "info" (describe only, download nothing).
        output_dir: Folder to save into; defaults to ~/Downloads. Playlists and
            galleries get their own subfolder.
        playlist: True to fetch a whole playlist/channel instead of just the
            linked video.
        max_items: Cap on playlist items or gallery images (default 50).
        max_height: For video, cap the resolution (e.g. 720 or 1080); 0 = best.
        language: Caption language code for kind="subtitles" (default "en").
        cookies_from_browser: e.g. "chrome" or "safari" to use the user's
            logged-in session for private/members-only/login-walled media
            (Panopto, Instagram...). Only when the user asks or agrees; macOS
            may prompt for Keychain access.

    Returns:
        The saved file path(s) and sizes, a short description for "info", or
        "Error: ..." with what each downloader said.
    """
    from media import fetch
    return fetch(url, kind, output_dir, playlist, max_items, max_height, language, cookies_from_browser)


if __name__ == "__main__":
    mcp.run()
