"""Citation helper MCP server (local, no model).

Built for journal tech-edit work:
- extract_citations: pull every citation out of a draft (Word footnotes read
  directly) with eyecite, group short forms / id. / supra under the authority
  they point to, and flag short-form problems worth a human look.
- verify_quotes: check every quotation in a draft against the source files.
- format_case: a modest formatter for a basic case cite.

None of this validates Bluebook form or looks cases up - the lookup side needs
the CourtListener or Descrybe connector. Output is a checklist for a human.
"""

import difflib
import logging
import os
import re
import unicodedata
import zipfile
from collections import defaultdict
from xml.etree import ElementTree as ET

from mcp.server.mcpserver import MCPServer

logging.getLogger("eyecite").setLevel(logging.ERROR)

mcp = MCPServer("cite")

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


# ---------------------------------------------------------------- loading ---

def _docx_text(el) -> str:
    parts = []
    for node in el.iter():
        if node.tag == _W + "t" and node.text:
            parts.append(node.text)
        elif node.tag in (_W + "tab", _W + "br"):
            parts.append(" ")
    return "".join(parts).strip()


def _docx_indent(p) -> int:
    """Left indent in twips; block-quote paragraph styles count as indented."""
    style = p.find(f"{_W}pPr/{_W}pStyle")
    if style is not None and re.search(r"quote|block", style.get(_W + "val", ""), re.I):
        return 720
    ind = p.find(f"{_W}pPr/{_W}ind")
    if ind is None:
        return 0
    val = ind.get(_W + "left") or ind.get(_W + "start") or "0"
    try:
        return int(val)
    except ValueError:
        return 0


def _load_docx(path: str) -> list[dict]:
    """Body paragraphs and footnotes as units. Tracked insertions count,
    deletions don't (the "accepted" view). Footnotes are numbered by the order
    their references appear in the body, which is what Word displays."""
    with zipfile.ZipFile(path) as z:
        doc = ET.fromstring(z.read("word/document.xml"))
        fn_xml = z.read("word/footnotes.xml") if "word/footnotes.xml" in z.namelist() else None
    units = []
    body = doc.find(_W + "body")
    n = 0
    for p in body.iter(_W + "p"):
        text = _docx_text(p)
        if text:
            n += 1
            units.append({"loc": f"¶{n}", "kind": "body", "text": text,
                          "indent": _docx_indent(p)})
    if fn_xml is None:
        return units
    notes = {}
    for fn in ET.fromstring(fn_xml).iter(_W + "footnote"):
        if fn.get(_W + "type") in ("separator", "continuationSeparator", "continuationNotice"):
            continue
        paras = [(_docx_text(p), _docx_indent(p)) for p in fn.iter(_W + "p")]
        notes[fn.get(_W + "id")] = paras
    order = []
    for ref in doc.iter(_W + "footnoteReference"):
        fid = ref.get(_W + "id")
        if fid in notes and fid not in order:
            order.append(fid)
    for num, fid in enumerate(order, 1):
        paras = [t for t, _ in notes[fid] if t]
        units.append({"loc": f"fn {num}", "kind": "fn", "num": num, "text": " ".join(paras),
                      "indent": max((i for _, i in notes[fid]), default=0)})
    return units


def _load_pdf(path: str) -> list[dict]:
    import pymupdf

    units = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc):
            label = page.get_label() if hasattr(page, "get_label") else ""
            loc = f"p. {label} (pdf p. {i + 1})" if label else f"pdf p. {i + 1}"
            # Rejoin words hyphenated across line breaks, then flatten lines.
            text = re.sub(r"(\w)-\n(\w)", r"\1\2", page.get_text())
            units.append({"loc": loc, "kind": "page", "text": " ".join(text.split())})
    return units


def _load(path: str) -> list[dict] | str:
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return f"Error: file not found: {path}"
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".docx":
            return _load_docx(path)
        if ext == ".pdf":
            return _load_pdf(path)
        with open(path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
        if ext in (".html", ".htm"):
            import trafilatura

            raw = trafilatura.extract(raw, include_tables=True) or ""
            return [{"loc": "page", "kind": "page", "text": " ".join(raw.split())}]
        if ext in (".txt", ".md", ".markdown", ""):
            return [{"loc": f"line {n}", "kind": "line", "text": line}
                    for n, line in enumerate(raw.splitlines(), 1) if line.strip()]
    except Exception as e:  # corrupt zip, bad PDF, etc.
        return f"Error: could not read {path}: {e}"
    return f"Error: unsupported file type '{ext}' (use .docx, .pdf, .txt, .md or .html)"


_SPACES = re.compile(r"[\u00a0\u2000-\u200b\u202f\u205f]")


def _clean(units):
    # Word puts non-breaking spaces inside cites ("Rev.\xa01", "§\xa01983"),
    # which hides them from eyecite and the quote matcher.
    if isinstance(units, list):
        for u in units:
            u["text"] = _SPACES.sub(" ", u["text"])
    return units


def _units(path: str, text: str) -> list[dict] | str:
    if path:
        units = _clean(_load(path))
    else:
        units = [{"loc": f"line {n}", "kind": "line", "text": line}
                 for n, line in enumerate(text.splitlines(), 1) if line.strip()]
    if isinstance(units, list) and not units:
        return "Error: no text to scan"
    return units


# ------------------------------------------------------ extract_citations ---

def _full_law_text(c, text: str) -> str:
    # eyecite stops a section at the first period ("§ 240" for "§ 240.10b-5").
    s = c.matched_text()
    tail = re.match(r"[\w.\-]*\w(?:\([\w]+\))*", text[c.span()[1]:])
    return s + tail.group(0) if tail else s


def _case_name(c) -> str:
    md = c.metadata
    p, d = getattr(md, "plaintiff", None), getattr(md, "defendant", None)
    if p and d:
        p = re.sub(r"^(?:Id\.|See|See also|Cf\.|But see|E\.g\.,?)\s+", "", p)
        return f"{p} v. {d}"
    return ""


def _pin(c) -> str:
    pin = getattr(c.metadata, "pin_cite", None)
    return f" at {pin.removeprefix('at ').strip()}" if pin else ""


@mcp.tool()
def extract_citations(path: str = "", text: str = "") -> str:
    """List every legal citation in a draft, grouped by authority, with flags for tech edit.

    Uses eyecite (Free Law Project's parser) to find full case cites, short
    cites, id., supra, statutes/regs (U.S.C., C.F.R., state codes) and law-review
    cites. Each short form, id. and supra is listed under the authority it points
    to, so you can see every place a source is cited. For a .docx it reads the
    FOOTNOTES directly (locations like "fn 12", numbered as Word shows them) plus
    body paragraphs ("¶3") - pass the .docx path, not read_document output, which
    drops footnotes.

    Also flags, for a human to check (heuristics, not rulings):
    - short case cites with no earlier full cite, or whose full cite is more
      than five footnotes back (Bluebook R10.9);
    - id. at the start of a footnote when the previous footnote has zero or
      several authorities (R4.1);
    - "supra note N" where footnote N doesn't mention the cited author/name.

    It surfaces citations; it does NOT check Bluebook form, signals, parentheticals
    or whether a cite is right. No model, runs in seconds, output is compact.

    Args:
        path: Absolute path to a .docx, .txt, .md or .pdf draft (or pass `text`).
        text: Draft text, if not reading from a path (locations are line numbers).

    Returns:
        Authorities with every location they're cited, supra cites, and flags.
    """
    from eyecite import get_citations, resolve_citations
    from eyecite.models import (FullCaseCitation, FullJournalCitation, FullLawCitation,
                                IdCitation, ShortCaseCitation, SupraCitation)

    units = _units(path, text)
    if isinstance(units, str):
        return units
    # Parse each paragraph/footnote on its own (eyecite reads case names across
    # boundaries otherwise), then resolve short forms across the whole draft.
    cites, owner = [], {}
    try:
        for u in units:
            for c in sorted(get_citations(u["text"]), key=lambda c: c.span()[0]):
                cites.append(c)
                owner[id(c)] = u
        resolved = resolve_citations(cites)
    except Exception as e:
        return f"Error: eyecite failed: {e}"

    def unit_of(c):
        return owner[id(c)]

    # Authority key for each cite: eyecite's resolution for cases (full + short),
    # its own key for statutes/journals, (name, note) for supra, previous for id.
    by_cite = {}
    for res, group in resolved.items():
        for c in group:
            by_cite[id(c)] = res
    authorities = {}          # key -> {"label", "kind", "uses": [(loc, form)]}
    order = []
    fn_auths = defaultdict(set)
    flags = []
    supras = []
    prev_key = None
    first_full_fn = {}

    def add(key, label, kind, loc, form):
        if key not in authorities:
            authorities[key] = {"label": label, "kind": kind, "uses": []}
            order.append(key)
        authorities[key]["uses"].append((loc, form))

    for c in cites:
        u = unit_of(c)
        loc, fn = u["loc"], u.get("num")
        key = None
        if isinstance(c, FullCaseCitation):
            res = by_cite.get(id(c))
            key = ("res", id(res)) if res is not None else ("cite", c.corrected_citation())
            name = _case_name(c)
            label = f"{name}, {c.corrected_citation()}" if name else c.corrected_citation()
            add(key, label, "case", loc, "full" + _pin(c))
            if fn is not None:
                first_full_fn.setdefault(key, fn)
        elif isinstance(c, ShortCaseCitation):
            res = by_cite.get(id(c))
            if res is None:
                key = ("cite", c.matched_text())
                add(key, c.matched_text(), "case", loc, "short")
                flags.append(f"{loc}: short cite \"{c.matched_text()}\" has no earlier full cite")
            else:
                key = ("res", id(res))
                add(key, "", "case", loc, "short" + _pin(c))
                full_fn = first_full_fn.get(key)
                if fn is not None and full_fn is not None and fn - full_fn > 5:
                    flags.append(f"{loc}: short cite \"{c.matched_text()}\" - full cite is in fn "
                                 f"{full_fn}, more than 5 footnotes back (R10.9)")
        elif isinstance(c, FullLawCitation):
            label = _full_law_text(c, u["text"])
            key = ("law", label)
            add(key, label, "law", loc, "cited")
        elif isinstance(c, FullJournalCitation):
            label = c.corrected_citation()
            key = ("journal", label)
            add(key, label, "journal", loc, "full" + _pin(c))
        elif isinstance(c, SupraCitation):
            name = (c.metadata.antecedent_guess or "").strip()
            note = re.search(r"note\s+(\d+)", c.metadata.pin_cite or "")
            note_n = int(note.group(1)) if note else None
            key = ("supra", name.lower(), note_n)
            form = f"{name}, supra" + (f" note {note_n}" if note_n else "")
            pin = re.sub(r"^note\s+\d+,?\s*", "", c.metadata.pin_cite or "").strip()
            supras.append((loc, form + (f", {pin}" if pin else ""), name, note_n))
            add(key, form, "supra", loc, "supra")
        elif isinstance(c, IdCitation):
            if prev_key is None:
                flags.append(f"{loc}: id. with no earlier citation to refer to")
            else:
                authorities[prev_key]["uses"].append((loc, "id." + _pin(c)))
                key = prev_key
            prev_fn_n = (fn or 0) - 1
            starts_fn = fn is not None and not any(
                unit_of(o) is u and o.span()[0] < c.span()[0] for o in cites)
            if starts_fn and prev_fn_n >= 1:
                n_prev = len(fn_auths.get(prev_fn_n, ()))
                if n_prev != 1:
                    flags.append(f"{loc}: id. opens the footnote but fn {prev_fn_n} has "
                                 f"{n_prev} authorities (R4.1)")
        else:
            continue
        if key is not None:
            prev_key = key
            if fn is not None:
                fn_auths[fn].add(key)

    # supra note N should point at a footnote that names the source.
    fn_text = {u["num"]: u["text"] for u in units if u.get("num")}
    supra_lines = []
    for loc, form, name, note_n in supras:
        if note_n is None or not fn_text:
            supra_lines.append(f"  {loc}: {form}")
        elif note_n not in fn_text:
            supra_lines.append(f"  {loc}: {form}")
            flags.append(f"{loc}: {form} - there is no fn {note_n}")
        elif name and name.lower() not in fn_text[note_n].lower():
            supra_lines.append(f"  {loc}: {form}")
            flags.append(f"{loc}: {form} - fn {note_n} doesn't mention \"{name}\"")
        else:
            supra_lines.append(f"  {loc}: {form}  (fn {note_n} mentions it)")

    if not order and not flags:
        return "No citations found."
    n_fn = sum(1 for u in units if u["kind"] == "fn")
    head = f"{len(cites)} citations to {len(order)} authorities"
    if n_fn:
        head += f" ({n_fn} footnotes read)"
    out = [head]
    titles = {"case": "Cases", "law": "Statutes & regulations", "journal": "Journals",
              "supra": "Supra-cited sources (author/title only; see Supra cites)"}
    for kind, title in titles.items():
        keys = [k for k in order if authorities[k]["kind"] == kind]
        if not keys:
            continue
        out.append(f"\n{title} ({len(keys)}):")
        for k in keys:
            a = authorities[k]
            uses = "; ".join(f"{loc} {form}" for loc, form in a["uses"])
            out.append(f"  {a['label'] or a['uses'][0][1]} — {uses}")
    if supra_lines:
        out.append(f"\nSupra cites ({len(supra_lines)}):")
        out.extend(supra_lines)
    if flags:
        out.append(f"\nFlags to check ({len(flags)}):")
        out.extend(f"  - {f}" for f in flags)
    out.append("\n(eyecite parse: verify form, signals and pins yourself.)")
    return "\n".join(out)


# ---------------------------------------------------------- verify_quotes ---

_QUOTE_RE = re.compile(r"“([^“”]+)”|\"([^\"]+)\"")
_ELLIPSIS_RE = re.compile(r"\s*(?:\.\s){2,}\.|\s*…|\s*\.\.\.")
_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                        " ": " ", "­": None})


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).translate(_TRANS)


def _key(tok: str) -> str:
    """Matching key: case-folded, brackets and punctuation stripped."""
    return re.sub(r"[^\w§]", "", tok.replace("[", "").replace("]", "")).casefold()


def _quotes(units: list[dict], min_words: int) -> tuple[list[tuple[str, str]], int]:
    found, short = [], 0
    for u in units:
        for m in _QUOTE_RE.finditer(_norm(u["text"])):
            q = (m.group(1) or m.group(2)).strip()
            if len(q.split()) >= min_words:
                found.append((u["loc"], q))
            else:
                short += 1
        # Indented paragraphs with no quote marks are likely block quotes.
        if u.get("indent", 0) >= 720 and not _QUOTE_RE.search(u["text"]) \
                and len(u["text"].split()) >= 25:
            found.append((u["loc"] + " (block)", _norm(u["text"])))
    return found, short


class _Source:
    def __init__(self, path: str, units: list[dict]):
        self.name = os.path.basename(path)
        self.tokens, self.locs = [], []
        for u in units:
            for t in _norm(u["text"]).split():
                self.tokens.append(t)
                self.locs.append(u["loc"])
        self.keys = [_key(t) for t in self.tokens]
        self.index = defaultdict(list)
        for i in range(len(self.keys) - 2):
            self.index[tuple(self.keys[i:i + 3])].append(i)


def _best_match(seg: list[str], sources: list[_Source]):
    """Vote on candidate start positions via shared word trigrams, then score
    the best few windows by word alignment. Returns (score, source, i, j)."""
    keys = [_key(t) for t in seg]
    best = (0.0, None, 0, 0)
    for src in sources:
        votes = defaultdict(int)
        for k in range(len(keys) - 2):
            for i in src.index.get(tuple(keys[k:k + 3]), ()):
                votes[i - k] += 1
        for start, _ in sorted(votes.items(), key=lambda kv: -kv[1])[:5]:
            lo = max(0, start - 3)
            hi = min(len(src.keys), start + 2 * len(keys) + 5)  # room for omissions
            sm = difflib.SequenceMatcher(None, keys, src.keys[lo:hi], autojunk=False)
            blocks = [b for b in sm.get_matching_blocks() if b.size]
            if not blocks:
                continue
            score = sum(b.size for b in blocks) / len(keys)
            if score > best[0]:
                # Drop a stray one-word match ("the") at either edge: one cut off
                # from the rest by quote words the source doesn't have, and
                # sitting even farther away in the source.
                def stray(x, y):
                    qgap, sgap = y.a - x.a - x.size, y.b - x.b - x.size
                    return qgap > 0 and sgap > qgap
                while len(blocks) > 1 and blocks[0].size == 1 and stray(blocks[0], blocks[1]):
                    blocks.pop(0)
                while len(blocks) > 1 and blocks[-1].size == 1 and stray(blocks[-2], blocks[-1]):
                    blocks.pop()
                i = lo + blocks[0].b
                j = lo + blocks[-1].b + blocks[-1].size
                best = (score, src, i, j)
    return best


def _diffs(seg: list[str], src_toks: list[str]) -> list[str]:
    """Word-level differences. Words are aligned ignoring case and punctuation;
    then aligned words are compared for capitalization and punctuation.
    Bracketed words are reported as alterations to confirm. Punctuation next
    to an omission, and on the last word (comma/period inside the quote), is
    not reported."""
    a, b = [_key(t) for t in seg], [_key(t) for t in src_toks]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ops = sm.get_opcodes()
    out = []
    for n, (op, a1, a2, b1, b2) in enumerate(ops):
        q, s = " ".join(seg[a1:a2]), " ".join(src_toks[b1:b2])
        if op == "equal":
            for k in range(a2 - a1):
                qt, st = seg[a1 + k].strip("\"'"), src_toks[b1 + k].strip("\"'")
                if qt == st:
                    continue
                if "[" in qt:
                    out.append(f"bracketed: {qt} for source \"{st}\"")
                    continue
                qw, sw = re.sub(r"[^\w§]", "", qt), re.sub(r"[^\w§]", "", st)
                if qw != sw:
                    out.append(f"capitalization: draft \"{qt}\" vs source \"{st}\"")
                    continue
                last = a1 + k == len(seg) - 1
                edge = (k == a2 - a1 - 1 and n + 1 < len(ops)) or (k == 0 and n > 0)
                if not last and not edge:
                    out.append(f"punctuation: draft \"{qt}\" vs source \"{st}\"")
        elif "[" in q or "]" in q:
            out.append(f"bracketed: {q} for source \"{s}\"")
        elif op == "delete":
            out.append(f"draft adds \"{q}\"")
        elif op == "insert":
            out.append(f"draft omits \"{s}\" (no ellipsis)")
        else:
            out.append(f"draft \"{q}\" vs source \"{s}\"")
    return out


@mcp.tool()
def verify_quotes(draft_path: str, sources: list[str], min_words: int = 4) -> str:
    """Check every quotation in a draft against the source files, word for word.

    For tech edit / cite-checking: finds each quoted passage in the draft
    ("..." or curly quotes, plus indented block quotes in a .docx; Word footnotes
    included, located as "fn 12") and searches all the sources for it. Each quote
    comes back as:
      ✓ exact   - found verbatim (ignoring quote-mark style), with source and page;
      ~ near    - found with differences, each listed: changed words, capitalization,
                  punctuation, words added or omitted without an ellipsis, and
                  bracketed alterations (shown so you can confirm they're proper);
      ✗ missing - not found in any source (wrong source, paraphrase, or a scan
                  without a text layer - run pdf_ocr on scans first).
    Ellipses split a quote into parts that are checked separately.

    Pages are PDF page labels when the PDF has them (HeinOnline/Westlaw PDFs often
    do), else the PDF page index - confirm pin cites against the printed page.
    No model; source text never enters Claude's context, only the report.

    Args:
        draft_path: Absolute path to the draft (.docx best; .txt/.md/.pdf work).
        sources: Absolute paths to source files and/or folders of them
            (.pdf, .docx, .txt, .md, .html).
        min_words: Skip quotes shorter than this (default 4); they're counted.

    Returns:
        A report: summary counts, then near and missing quotes in detail, then
        exact ones one line each.
    """
    units = _units(draft_path, "")
    if isinstance(units, str):
        return units
    paths = []
    for p in sources:
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                paths += [os.path.join(root, f) for f in sorted(files)
                          if f.lower().endswith((".pdf", ".docx", ".txt", ".md", ".html", ".htm"))
                          and not f.startswith(("~$", "."))]
        elif os.path.isfile(p):
            paths.append(p)
        else:
            return f"Error: source not found: {p}"
    if not paths:
        return "Error: no readable source files found"
    srcs, problems = [], []
    for p in paths:
        su = _clean(_load(p))
        if isinstance(su, str):
            problems.append(su)
        elif sum(len(u["text"]) for u in su) < 200:
            problems.append(f"{os.path.basename(p)}: little or no text (scanned? run pdf_ocr)")
        else:
            srcs.append(_Source(p, su))
    if not srcs:
        return "Error: none of the sources had readable text\n" + "\n".join(problems)

    quotes, short = _quotes(units, min_words)
    if not quotes:
        return f"No quotations of {min_words}+ words found in the draft."
    exact, near, missing = [], [], []
    for loc, q in quotes:
        parts = [s.split() for s in _ELLIPSIS_RE.split(q) if len(s.split()) >= 3]
        if not parts:
            continue
        lines, worst = [], "exact"
        for seg in parts:
            score, src, i, j = _best_match(seg, srcs)
            if src is None or score < 0.6:
                lines.append(f"    part \"{' '.join(seg[:8])}…\" not found")
                worst = "missing"
                continue
            where = f"{src.name} {src.locs[i]}"
            d = _diffs(seg, src.tokens[i:j])
            if d:
                lines.append(f"    {where}: " + "; ".join(d))
                if worst == "exact":
                    worst = "near"
            else:
                lines.append(f"    {where}")
        preview = " ".join(q.split()[:10]) + ("…" if len(q.split()) > 10 else "")
        entry = (f"  {loc}: \"{preview}\"", lines)
        {"exact": exact, "near": near, "missing": missing}[worst].append(entry)

    out = [f"{len(quotes)} quotes checked against {len(srcs)} source(s): "
           f"{len(exact)} exact, {len(near)} with differences, {len(missing)} not found"
           + (f"; {short} under {min_words} words skipped" if short else "")]
    if problems:
        out.append("Sources skipped:\n" + "\n".join(f"  {p}" for p in problems))
    for title, group in (("~ Differences", near), ("✗ Not found", missing)):
        if group:
            out.append(f"\n{title} ({len(group)}):")
            for head, lines in group:
                out.append(head)
                out.extend(lines)
    if exact:
        out.append(f"\n✓ Exact ({len(exact)}):")
        for head, lines in exact:
            out.append(f"{head} — {'; '.join(l.strip() for l in lines)}")
    return "\n".join(out)


# ------------------------------------------------------------ format_case ---

@mcp.tool()
def format_case(case_name: str, volume: str, reporter: str, first_page: str,
                court: str = "", year: str = "", pincite: str = "") -> str:
    """Assemble a BASIC case citation string from its parts (verify against Bluebook).

    A convenience for a first-draft cite; it does not apply every Bluebook rule
    (italics, signals, short forms, court abbreviations) - a human must check it.

    Args:
        case_name: e.g. "Miranda v. Arizona".
        volume, reporter, first_page: e.g. "384", "U.S.", "436".
        court: Court abbreviation for non-U.S.-Supreme cites, e.g. "9th Cir.".
        year: Decision year, e.g. "1966".
        pincite: Optional pin page, e.g. "444".

    Returns:
        A draft citation string.
    """
    page = f"{first_page}, {pincite}" if pincite else first_page
    paren = ", ".join(p for p in (court, year) if p)
    cite = f"{case_name}, {volume} {reporter} {page}"
    if paren:
        cite += f" ({paren})"
    return cite + "   [draft — verify against Bluebook]"


if __name__ == "__main__":
    mcp.run()
