"""Convert files and web pages to Markdown on disk, keeping their structure,
behind the files server's to_markdown tool and the to-md command.

Built for legal sources, where a dropped subsection or footnote is an error:
- Word/PowerPoint/Excel/ODT/RTF/EPUB/HTML/LaTeX -> pandoc (headings, nested
  lists, block quotes, tables, italics and footnotes all kept; tracked
  changes accepted, comments dropped)
- legacy .doc/.webarchive -> macOS textutil to .docx first, then pandoc
- PDF -> pymupdf4llm, with a <!-- page N --> marker before each page for pin
  cites (the printed page label when the PDF has one)
- web page -> fetched with a browser fingerprint, the main content picked
  conservatively (whole <main>/<article>, never sentence-level scoring),
  then pandoc

Every conversion is checked against an independent plain-text read of the
source, and the result reports what share of the source's words made it
into the Markdown, so a silent loss shows up as a number instead of going
unnoticed.
"""

import collections
import datetime
import glob
import logging
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import urllib.parse
import zipfile

os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")
logging.getLogger("httpx").setLevel(logging.WARNING)

PANDOC_IN = {
    ".docx": "docx", ".pptx": "pptx", ".xlsx": "xlsx", ".odt": "odt",
    ".epub": "epub", ".html": "html", ".htm": "html", ".xhtml": "html", ".tex": "latex",
    ".rst": "rst", ".org": "org", ".ipynb": "ipynb", ".csv": "csv", ".tsv": "tsv",
}
# Pandoc's RTF reader drops the letter after a curly quote ("ransformative"), so
# RTF goes through textutil too.
TEXTUTIL_IN = (".doc", ".rtf", ".rtfd", ".webarchive", ".wordml")
PLAIN_IN = (".md", ".markdown", ".txt")
WARN_BELOW = 0.98
WRITER = "markdown_strict-raw_html+footnotes+pipe_tables+fancy_lists+startnum+strikeout"

# Site rules: domain suffix -> XPaths for the content container, tried in order.
SITE_CONTAINERS = {
    "justia.com": ["//div[contains(concat(' ', normalize-space(@class), ' '), ' opinions ')]"],
    "law.cornell.edu": ["//main", "//*[@id='content']"],
    "ecfr.gov": ["//div[contains(concat(' ', normalize-space(@class), ' '), ' part ')]",
                 "//div[contains(concat(' ', normalize-space(@class), ' '), ' subpart ')]",
                 "//div[contains(concat(' ', normalize-space(@class), ' '), ' section ')]"],
    "supremecourt.gov": ["//*[@id='pagemaindiv']", "//main"],
}
# Removed from inside the chosen container.
CRUFT_TAGS = ("script", "style", "noscript", "nav", "form", "button", "iframe", "svg",
              "select", "input", "template", "dialog")
CRUFT_CLASS = re.compile(
    r"(?:^|[\s_-])(?:nav|navbar|menu|breadcrumbs?|sidebar|cookie|consent|share|sharing|social|"
    r"subscribe|newsletter|advert|ads?|promo|skip|modal|popup|toolbar|masthead|prevnext)(?:$|[\s_-])", re.I)


# --- fidelity check -------------------------------------------------------------

def _tokens(text):
    text = unicodedata.normalize("NFKC", text).replace("’", "'").replace("‘", "'")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)  # rejoin words hyphenated across lines
    return collections.Counter(re.findall(r"[^\W_]+|[§¶]", text.lower()))


def _fidelity(source_text, md_text):
    """Share of the source's words found in the Markdown, plus a sample of what's missing."""
    src, out = _tokens(source_text), _tokens(md_text)
    total = sum(src.values())
    if not total:
        return None, []
    missing = src - out
    lost = sum(missing.values())
    sample = [w for w, _ in missing.most_common(12)]
    return 1 - lost / total, sample


# --- sources ---------------------------------------------------------------------

def _pandoc(path_or_text, fmt, is_text=False):
    # markdown_strict plus the extensions legal text needs: footnotes, tables, and
    # lettered/roman/parenthesized list markers ((a), (i), A.) kept as written,
    # with no raw HTML wrappers left behind.
    cmd = ["pandoc", "-f", fmt, "-t", WRITER, "--wrap=none", "--track-changes=accept"]
    if fmt in ("docx", "pptx", "odt", "epub"):
        cmd += ["--extract-media", os.devnull]  # keep alt text, don't write image files
    p = subprocess.run(cmd + ([] if is_text else [path_or_text]), input=path_or_text if is_text else None,
                       capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        raise RuntimeError(f"pandoc: {(p.stderr or 'failed').strip().splitlines()[-1]}")
    md = p.stdout
    md = re.sub(r"!\[([^\]]*)\]\([^)]*\)(\{[^}]*\})?", lambda m: f"[image: {m.group(1)}]" if m.group(1) else "", md)
    return md


def _office_text(path):
    """Plain text straight from the Office XML (body, footnotes, endnotes, slides,
    cells), independent of pandoc, for the fidelity check. Deleted tracked text
    (w:delText) is skipped, matching --track-changes=accept."""
    parts = []
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.match(
            r"(word/(document|footnotes|endnotes)\d*\.xml|ppt/slides/slide\d+\.xml|xl/sharedStrings\.xml"
            r"|content\.xml)$", n)]
        for n in names:
            xml = z.read(n).decode("utf-8", "replace")
            if n == "content.xml":  # ODT: text is the element content
                xml = re.sub(r"</text:(p|h)>|</text:note-citation>", "\n", xml)
                parts.append(re.sub(r"<[^>]+>", "", xml))
                continue
            # Word/PowerPoint/Excel: only text runs (w:t, a:t, t), never attribute
            # values or ids; deleted tracked text is w:delText, so it's skipped.
            xml = re.sub(r"<w:footnote [^>]*w:type=\"(separator|continuationSeparator|continuationNotice)\".*?</w:footnote>", " ", xml, flags=re.S)
            xml = re.sub(r"</(w:p|a:p|si)>", "<t>\n</t>", xml)
            xml = re.sub(r"<(w:tab|w:br)\b[^>]*/>", "<t> </t>", xml)
            parts.append("".join(re.findall(r"<(?:w:t|a:t|t)(?:\s[^>]*)?>([^<]*)</(?:w:t|a:t|t)>", xml)))
    import html as _html
    return _html.unescape("\n".join(parts))


def _from_pdf(path):
    """Run in a child process: pymupdf4llm loads a small layout model (~0.5 GB at
    peak), and a long-running MCP server would otherwise keep it in memory."""
    import json
    import sys

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "result.json")
        p = subprocess.run([sys.executable, os.path.abspath(__file__), "--pdf-worker", path, out],
                           capture_output=True, text=True, timeout=1800)
        if p.returncode != 0 or not os.path.isfile(out):
            err = (p.stderr or "failed").strip().splitlines()
            raise RuntimeError(f"PDF conversion: {err[-1] if err else 'failed'}")
        with open(out, encoding="utf-8") as f:
            r = json.load(f)
    return r["md"], r["plain"], r["title"], r["meta"], r["notes"]


def _pdf_worker(path):
    import pymupdf
    import pymupdf4llm

    doc = pymupdf.open(path)
    # No OCR here: it's slow and RAM-heavy; scanned pages are reported instead.
    chunks = pymupdf4llm.to_markdown(doc, page_chunks=True, show_progress=False, use_ocr=False)
    out, plain, blank = [], [], []
    for i, (page, chunk) in enumerate(zip(doc, chunks), 1):
        label = page.get_label() or str(i)
        text = page.get_text()
        plain.append(text)
        if not text.strip() or (len(text.strip()) < 20 and page.get_images()):
            blank.append(label)
        out.append(f"<!-- page {label} -->\n\n{chunk.get('text', '').strip()}\n")
    meta = {"pages": doc.page_count}
    notes = []
    if blank:
        shown = ", ".join(blank[:10]) + (" ..." if len(blank) > 10 else "")
        notes.append(f"{len(blank)} page(s) have no text layer ({shown}); run pdf_ocr on the PDF first, then convert the searchable copy")
    title = (doc.metadata or {}).get("title") or ""
    doc.close()
    return "\n".join(out), "\n".join(plain), title, meta, notes


def _from_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _from_pdf(path)
    if ext in PLAIN_IN:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        return text, text, "", {}, []
    if ext in TEXTUTIL_IN:
        with tempfile.TemporaryDirectory() as tmp:
            docx = os.path.join(tmp, os.path.splitext(os.path.basename(path))[0] + ".docx")
            p = subprocess.run(["textutil", "-convert", "docx", "-output", docx, path],
                               capture_output=True, text=True, timeout=300)
            if p.returncode != 0 or not os.path.isfile(docx):
                raise RuntimeError(f"textutil could not read {ext}: {(p.stderr or '').strip()}")
            md, plain, title, meta, notes = _from_file(docx)
            return md, plain, title, meta, notes + [f"{ext} read via macOS textutil, which drops footnotes and turns headings into bold; if those matter, re-save as .docx in Word and convert that"]
    if ext in PANDOC_IN:
        fmt = PANDOC_IN[ext]
        md = _pandoc(path, fmt)
        if ext in (".docx", ".pptx", ".xlsx", ".odt"):
            plain = _office_text(path)
        elif fmt == "html":
            with open(path, "rb") as f:
                return _from_html(f.read(), "", whole=True)
        else:
            plain = ""
        return md, plain, "", {}, []
    if ext in (".ppt", ".xls"):
        raise RuntimeError(f"legacy {ext} isn't readable here; re-save it as {ext}x in PowerPoint/Excel")
    raise RuntimeError(f"unsupported file type '{ext}'")


def _choose_container(tree, url):
    host = urllib.parse.urlparse(url).netloc.lower()
    for domain, xpaths in SITE_CONTAINERS.items():
        if host == domain or host.endswith("." + domain):
            for xp in xpaths:
                hit = tree.xpath(xp)
                if hit:
                    return hit[0], f"site rule ({domain})"
    body = tree.find("body")
    if body is None:
        body = tree
    body_words = len(body.text_content().split()) or 1
    for xp in ("//main", "//*[@role='main']", "//article"):
        hits = sorted(tree.xpath(xp), key=lambda n: len(n.text_content().split()), reverse=True)
        if hits and len(hits[0].text_content().split()) >= 0.25 * body_words:
            return hits[0], xp.strip("/")
    for xp in ("//header", "//footer", "//aside", "//*[@role='banner']", "//*[@role='contentinfo']"):
        for n in body.xpath(xp):
            n.drop_tree()
    return body, "whole page"


BLOCK_TAGS = {"div", "p", "table", "ul", "ol", "dl", "blockquote", "pre", "section", "article", "main",
              "header", "footer", "figure", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "aside", "center"}
_BREAK = re.compile(r"\n[ \t\r]*\n\s*")


def _paragraphize(el):
    """Some court sites (Justia) put an opinion in one <div> as plain text with
    blank lines between paragraphs; HTML ignores those, so pandoc would merge the
    whole opinion into one paragraph. Wrap each blank-line-separated run in <p>."""
    from lxml import etree

    if not isinstance(el.tag, str) or el.tag in ("pre", "code", "textarea", "p"):
        return
    for child in list(el):
        if isinstance(child.tag, str) and child.tag in BLOCK_TAGS:
            _paragraphize(child)
    if el.tag not in ("div", "section", "article", "main", "body", "td", "blockquote", "li", "center"):
        return
    pieces = [el.text or ""] + [c.tail or "" for c in el]
    if not any(_BREAK.search(t.strip(" \t")) for t in pieces if t.strip()):
        return
    new, cur = [], etree.Element("p")

    def flush():
        nonlocal cur
        if len(cur) or (cur.text or "").strip():
            new.append(cur)
        cur = etree.Element("p")

    def add_text(text):
        parts = _BREAK.split(text)
        for i, part in enumerate(parts):
            if i:
                flush()
            if len(cur):
                cur[-1].tail = (cur[-1].tail or "") + part
            else:
                cur.text = (cur.text or "") + part

    add_text(el.text or "")
    for child in list(el):
        tail, child.tail = child.tail or "", None
        if isinstance(child.tag, str) and child.tag in BLOCK_TAGS:
            flush()
            new.append(child)
        else:
            cur.append(child)
        add_text(tail)
    flush()
    el.text = None
    for child in list(el):
        el.remove(child)
    el.extend(new)


def _block_text(node):
    """Plain text with a line break after each block, so adjacent blocks
    ("Topeka" + "Argued") don't fuse into one word in the fidelity check."""
    import copy

    node = copy.deepcopy(node)
    for el in node.iter():
        if isinstance(el.tag, str) and (el.tag in BLOCK_TAGS or el.tag in ("br", "li", "td", "th", "tr", "dt", "dd")):
            el.tail = "\n" + (el.tail or "")
    return node.text_content()


def _tidy(md):
    """Undo writer artifacts that would change quoted text."""
    md = md.replace("\\[", "[").replace("\\]", "]")          # [ly], [487], [Footnote 1]
    md = re.sub(r"(?<=[_*]) (?=[,.;:)\]])", "", md)          # "_Powell_ ," from PDF italics
    md = re.sub(r"(?m)^(\(\w{1,6}\))[ \t]*\n[ \t]*\n(?=\S)", r"\1 ", md)  # "(1)" alone on a line
    md = re.sub(r"[ \t]+$", "", md, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", md)


def _strip_cruft(node):
    for tag in CRUFT_TAGS:
        for n in node.xpath(f".//{tag}"):
            n.drop_tree()
    for n in node.xpath(".//*[@aria-hidden='true' or @hidden or @role='navigation' or @role='search']"):
        n.drop_tree()
    for n in node.xpath(".//*[@class or @id]"):
        if n.getparent() is not None and CRUFT_CLASS.search(f"{n.get('class', '')} {n.get('id', '')}"):
            if len(n.text_content().split()) < 150:  # never drop a big block on a class name alone
                n.drop_tree()


def _decode(raw, ctype=""):
    """Bytes -> text using the HTTP charset, else the page's <meta>, else UTF-8."""
    if isinstance(raw, str):
        return raw
    m = re.search(r"charset=[\"']?([\w-]+)", ctype or "", re.I) or \
        re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:4096], re.I)
    enc = m.group(1) if m else "utf-8"
    enc = enc.decode() if isinstance(enc, bytes) else enc
    try:
        return raw.decode(enc, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _from_html(raw, url, whole=False, keep_links=False, ctype=""):
    from lxml import html

    tree = html.fromstring(_decode(raw, ctype))
    page_words = len(tree.text_content().split())
    title = (tree.findtext(".//title") or "").strip()
    if whole:
        node, how = tree.find("body") if tree.find("body") is not None else tree, "whole file"
    else:
        node, how = _choose_container(tree, url)
    h1 = node.xpath(".//h1")
    if h1 and h1[0].text_content().strip():
        title = h1[0].text_content().strip()
    _strip_cruft(node)
    _paragraphize(node)
    if keep_links and url:
        node.make_links_absolute(url, resolve_base_href=True)
    elif not keep_links:
        for a in node.xpath(".//a"):
            a.drop_tag()
    plain = _block_text(node)
    md = _pandoc(html.tostring(node, encoding="unicode"), "html", is_text=True)
    md = re.sub(r"\n{3,}", "\n\n", md)
    kept = len(plain.split())
    meta = {"container": how}
    notes = []
    if not whole and page_words:
        meta["kept"] = f"{kept:,} of {page_words:,} words on the page ({how})"
    if kept < 80:
        notes.append("very little text on this page: it may render with JavaScript, sit behind a "
                     "login or bot check, or just link to a PDF (fetch that link instead)")
    return md, plain, title, meta, notes


def _fetch(url):
    from curl_cffi import requests as cr

    r = cr.get(url, impersonate="chrome", timeout=60, allow_redirects=True)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} from {url}")
    if r.status_code == 202 and len(r.content) < 5000:
        raise RuntimeError(f"{url} answered with a bot check; use the site's connector/API or save the page from a browser")
    return r.content, r.headers.get("content-type", ""), str(r.url)


def _from_url(url, keep_links=False):
    raw, ctype, final = _fetch(url)
    ct = ctype.split(";")[0].strip().lower()
    ext = {"application/pdf": ".pdf",
           "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
           "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
           "application/msword": ".doc", "application/rtf": ".rtf", "text/plain": ".txt",
           "application/epub+zip": ".epub"}.get(ct)
    if not ext and raw[:5] == b"%PDF-":
        ext = ".pdf"
    if ext:
        with tempfile.TemporaryDirectory() as tmp:
            name = os.path.basename(urllib.parse.urlparse(final).path) or "download"
            path = os.path.join(tmp, os.path.splitext(name)[0] + ext)
            with open(path, "wb") as f:
                f.write(raw)
            md, plain, title, meta, notes = _from_file(path)
            return md, plain, title or os.path.splitext(name)[0], meta, notes
    return _from_html(raw, final, keep_links=keep_links, ctype=ctype)


# --- entry point -------------------------------------------------------------------

def _safe_name(name):
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]+', " ", name).strip(" .")
    return re.sub(r"\s+", " ", name)[:120] or "page"


def _unique(path):
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(path):
        path = f"{base} ({n}){ext}"
        n += 1
    return path


def _expand(sources):
    out = []
    for s in sources:
        s = (s or "").strip()
        if not s:
            continue
        if re.match(r"https?://", s):
            out.append(s)
            continue
        s = os.path.expanduser(s)
        if any(c in s for c in "*?["):
            out += sorted(glob.glob(s))
        elif os.path.isdir(s):
            out += sorted(os.path.join(s, n) for n in os.listdir(s)
                          if os.path.splitext(n)[1].lower() in (*PANDOC_IN, *TEXTUTIL_IN, ".pdf")
                          and not n.startswith("~$"))
        else:
            out.append(s)
    return out


def convert_one(source, output_dir="", output_path="", overwrite=False, keep_links=False, taken=None):
    is_url = bool(re.match(r"https?://", source))
    if not is_url and not os.path.isfile(source):
        return f"Error: file not found: {source}"
    try:
        md, plain, title, meta, notes = _from_url(source, keep_links) if is_url else _from_file(source)
    except Exception as e:
        return f"Error: {source}: {e}"

    if output_path:
        out = os.path.expanduser(output_path)
    else:
        if is_url:
            folder = os.path.expanduser(output_dir) if output_dir else os.path.expanduser("~/Downloads")
            name = _safe_name(title or urllib.parse.urlparse(source).netloc)
        else:
            folder = os.path.expanduser(output_dir) if output_dir else os.path.dirname(source)
            name = os.path.splitext(os.path.basename(source))[0]
        out = os.path.join(folder, name + ".md")
        if os.path.abspath(out) == os.path.abspath(source):
            out = os.path.join(folder, name + " (converted).md")
    taken = set() if taken is None else taken
    clash = os.path.exists(out) if not overwrite else out in taken
    if clash and not output_path and not is_url:
        # sample.docx and sample.odt in one folder: "sample (odt).md", not "sample (1).md"
        out = os.path.join(os.path.dirname(out), f"{name} ({os.path.splitext(source)[1].lstrip('.').lower()}).md")
    if not overwrite or out in taken:
        out = _unique(out)
    taken.add(out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    stamp = datetime.date.today().isoformat()
    head = f"<!-- source: {source} | {'retrieved' if is_url else 'converted'} {stamp} -->\n"
    if is_url and title and not re.search(r"^#\s", md, re.M):
        head += f"\n# {title}\n"
    md = _tidy(md)
    with open(out, "w", encoding="utf-8") as f:
        f.write(head + "\n" + md.strip() + "\n")

    words = len(re.findall(r"[^\W_]+", md))
    stats = [f"{words:,} words"]
    if meta.get("pages"):
        stats.append(f"{meta['pages']} pages (<!-- page N --> markers)")
    heads = len(re.findall(r"^#{1,6} ", md, re.M))
    fns = len(re.findall(r"^\[\^[^\]]+\]:", md, re.M))
    tables = len(re.findall(r"^\|[ :-]+\|", md, re.M))
    for n, label in ((heads, "headings"), (fns, "footnotes"), (tables, "tables")):
        if n:
            stats.append(f"{n} {label}")
    lines = [f"Wrote {out} ({', '.join(stats)})"]
    if meta.get("kept"):
        lines.append(f"  kept {meta['kept']}")
    if plain.strip():
        score, missing = _fidelity(plain, md)
        if score is not None:
            flag = "" if score >= WARN_BELOW else "  <-- check: words were lost in conversion"
            lines.append(f"  fidelity {score:.1%} of source words present{flag}")
            if score < 0.999 and missing:
                lines.append(f"  missing words include: {', '.join(missing)}")
    lines += [f"  note: {n}" for n in notes]
    return "\n".join(lines)


def to_markdown(sources, output_dir="", output_path="", overwrite=False, keep_links=False):
    """See the to_markdown tool docstring in server.py."""
    if isinstance(sources, str):
        sources = [sources]
    items = _expand(sources)
    if not items:
        return "Error: no sources found"
    if output_path and len(items) > 1:
        return "Error: output_path works with one source; use output_dir for several"
    taken = set()
    results = [convert_one(s, output_dir, output_path, overwrite, keep_links, taken) for s in items]
    failed = sum(r.startswith("Error:") for r in results)
    if len(results) > 1:
        results.insert(0, f"Converted {len(results) - failed} of {len(results)} sources"
                          + (f" ({failed} failed)" if failed else "") + ":")
    return "\n".join(results)


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) == 4 and sys.argv[1] == "--pdf-worker":
        md, plain, title, meta, notes = _pdf_worker(sys.argv[2])
        with open(sys.argv[3], "w", encoding="utf-8") as f:
            json.dump({"md": md, "plain": plain, "title": title, "meta": meta, "notes": notes}, f)
