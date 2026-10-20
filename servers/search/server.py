"""Local hybrid search over the user's documents.

Embeds documents with a small local model (Ollama nomic-embed-text) into a
SQLite index and also keeps an FTS5 keyword index of the same chunks. A query
is ranked both ways (cosine similarity and BM25) and the two rankings are merged
with Reciprocal Rank Fusion, so exact terms the embeddings blur (section cites
like "§ 2511(2)(a)(i)", case names, docket numbers) still surface - and Claude
can pull the 5 paragraphs that matter instead of reading whole folders.

Indexing uses the text layer of PDFs and the Office/text readers only (no OCR),
so it's fast; scanned PDFs with no text layer are skipped (run pdf_ocr on them
first). The embedding model is ~300 MB and loads lazily.
"""

import glob
import json
import os
import re
import sqlite3
import struct
import urllib.request

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("search")

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
EMBED_MODEL = os.environ.get("LOCAL_EMBED_MODEL", "nomic-embed-text")
DB_PATH = os.path.expanduser("~/.cache/claude-local-tools/search.db")

TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".html",
             ".htm", ".rtf", ".log", ".tex", ".py"}
OFFICE_EXTS = {".docx", ".pptx", ".xlsx"}
CHUNK_CHARS = 1500
OVERLAP = 200
CANDIDATES = 50  # passages each ranker contributes before fusion
RRF_K = 60       # Reciprocal Rank Fusion constant: score = sum of 1/(RRF_K + rank)

_OCR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ocr")


def _read_office(path):
    import sys
    sys.path.insert(0, _OCR_DIR)
    import server as ocr
    return ocr.read_document(path)


def _extract(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        import fitz
        with fitz.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)
    if ext in OFFICE_EXTS:
        return _read_office(path)
    if ext in TEXT_EXTS:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    return ""


def _chunks(text):
    text = text.strip()
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + CHUNK_CHARS])
        i += CHUNK_CHARS - OVERLAP
    return [c for c in out if c.strip()]


def _embed(text):
    body = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/embeddings", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)["embedding"]


def _pack(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def _db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS chunks (path TEXT, mtime REAL, idx INTEGER, "
                "text TEXT, vec BLOB)")
    con.execute("CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path)")
    # Keyword index of the same chunks, joined back by (path, idx) rather than
    # rowid, which VACUUM may renumber. index_docs keeps it in sync and clears the
    # stale flag in the same transaction. Any other write to chunks (an older copy
    # of this server still running, or the code before this index existed) sets
    # the flag through the triggers, which live in the database file - so the next
    # call rebuilds it from the stored text: no re-embedding, ~3 s for 70k chunks.
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, path UNINDEXED, "
                "idx UNINDEXED, tokenize='porter unicode61 remove_diacritics 2')")
    con.execute("CREATE TABLE IF NOT EXISTS fts_state (stale INTEGER)")
    for op in ("INSERT", "DELETE"):
        con.execute(f"CREATE TRIGGER IF NOT EXISTS chunks_{op.lower()}_fts_stale AFTER {op} ON chunks "
                    "BEGIN UPDATE fts_state SET stale = 1; END")
    state = con.execute("SELECT stale FROM fts_state").fetchone()
    if state is None or state[0]:
        with con:
            if state is None:
                con.execute("INSERT INTO fts_state VALUES (1)")
            con.execute("DELETE FROM chunks_fts")
            con.execute("INSERT INTO chunks_fts (text, path, idx) SELECT text, path, idx FROM chunks")
            _mark_synced(con)
    con.commit()
    return con


def _mark_synced(con):
    """Clear the stale flag the chunks triggers set; call after mirroring the
    same writes into chunks_fts, before committing."""
    con.execute("UPDATE fts_state SET stale = 0")


def _fts_query(query):
    """Quote each whitespace-separated piece so FTS5 reads § ( ) . - " as text, not syntax.

    A quoted piece is a phrase, so "2511(2)(a)(i)" must match its tokens in order;
    pieces are OR'd and BM25 rewards chunks that hit more (and rarer) of them.
    """
    pieces = ['"' + p.replace('"', '""') + '"' for p in query.split() if re.search(r"\w", p)]
    return " OR ".join(pieces)


@mcp.tool()
def index_docs(folder: str, reindex: bool = False) -> str:
    """Build or update the search index over a folder (recursive).

    Run this once over a folder of notes/outlines/cases, and again when files
    change (unchanged files are skipped by modification time). Slow the first
    time - minutes for a large folder - so for anything big, run the `index-docs`
    CLI with run_in_background instead of calling this tool and waiting. Loads
    the ~300 MB embedding model; give the user a one-line heads-up first.

    Args:
        folder: Absolute path to index (searched recursively).
        reindex: True to re-embed every file even if unchanged.

    Returns:
        A summary of how many files and chunks were indexed or skipped.
    """
    folder = os.path.expanduser(folder)
    if not os.path.isdir(folder):
        return f"Error: not a folder: {folder}"
    con = _db()
    files = [f for f in glob.glob(os.path.join(folder, "**", "*"), recursive=True)
             if os.path.isfile(f)
             and os.path.splitext(f)[1].lower() in (TEXT_EXTS | OFFICE_EXTS | {".pdf"})]
    indexed = skipped = chunks = no_text = 0
    try:
        for path in files:
            mtime = os.path.getmtime(path)
            if not reindex:
                row = con.execute("SELECT mtime FROM chunks WHERE path=? LIMIT 1", (path,)).fetchone()
                if row and abs(row[0] - mtime) < 1:
                    skipped += 1
                    continue
            try:
                text = _extract(path)
            except Exception:
                continue
            con.execute("DELETE FROM chunks WHERE path=?", (path,))
            con.execute("DELETE FROM chunks_fts WHERE path=?", (path,))
            parts = _chunks(text)
            if not parts:
                no_text += 1
                continue
            for i, part in enumerate(parts):
                con.execute("INSERT INTO chunks VALUES (?,?,?,?,?)",
                            (path, mtime, i, part, _pack(_embed(part))))
                con.execute("INSERT INTO chunks_fts (text, path, idx) VALUES (?,?,?)", (part, path, i))
                chunks += 1
            _mark_synced(con)
            con.commit()
            indexed += 1
    finally:
        _mark_synced(con)
        con.commit()
        con.close()
    return (f"Indexed {indexed} files ({chunks} chunks), skipped {skipped} unchanged, "
            f"{no_text} had no extractable text (OCR them first). DB: {DB_PATH}")


def _vector_ranking(con, query, n, where, args):
    """Cosine-rank the n chunks matching `where` against the query embedding.

    Returns ({(path, idx): rank} for the top CANDIDATES, {(path, idx): cosine} for
    every chunk). Reads the vectors straight into one float32 matrix (~0.2 s and
    ~210 MB for 70k chunks, freed on return), so nothing stays cached between calls.
    """
    import numpy as np

    q = np.array(_embed(query), dtype=np.float32)
    q /= np.linalg.norm(q) or 1.0
    keys, mat = [], None
    for row, (path, idx, blob) in enumerate(
            con.execute("SELECT path, idx, vec FROM chunks" + where, args)):
        if mat is None:
            mat = np.empty((n, len(blob) // 4), dtype=np.float32)
        if row >= n:  # rows added since the count; they'll be there next time
            break
        mat[row] = np.frombuffer(blob, dtype=np.float32)
        keys.append((path, idx))
    if not keys:
        return {}, {}
    mat = mat[:len(keys)]
    if mat.shape[1] != q.shape[0]:
        raise ValueError(f"index vectors have {mat.shape[1]} dims but {EMBED_MODEL} gives "
                         f"{q.shape[0]}; re-run index_docs with reindex=True")
    scores = (mat @ q) / (np.sqrt(np.einsum("ij,ij->i", mat, mat)) + 1e-9)
    top = np.argsort(-scores) if len(keys) <= CANDIDATES else \
        np.argpartition(-scores, CANDIDATES)[:CANDIDATES]
    top = sorted(top, key=lambda j: -scores[j])
    ranks = {keys[j]: r for r, j in enumerate(top, 1)}
    return ranks, dict(zip(keys, scores.tolist()))


@mcp.tool()
def search_docs(query: str, k: int = 8, folder: str = "") -> str:
    """Find the passages most relevant to a query across indexed documents.

    Use this instead of reading whole folders: it returns the top matching
    chunks with their file path, so you can open only what matters. Run
    index_docs first.

    Hybrid search: passages are ranked by meaning (embeddings) and by exact words
    (keyword BM25), and the two rankings are fused. So put exact terms in the
    query verbatim - section cites ("§ 2511(2)(a)(i)"), case names, docket
    numbers, defined terms - alongside plain-language words; punctuation is
    handled for you. Each result is tagged with its cosine similarity and its
    keyword rank ("kw #2", or "no kw" when it matched on meaning only), and
    keyword hits show the text around the match. Takes about half a second plus
    embedding the query; if Ollama is down it returns keyword matches only.

    Args:
        query: What to look for: plain language, exact terms, or both.
        k: How many passages to return (default 8).
        folder: Optional path prefix to restrict results to.

    Returns:
        Ranked passages, each with its source path.
    """
    k = max(1, k)
    where, args = (" WHERE path LIKE ?", (os.path.expanduser(folder) + "%",)) if folder else ("", ())
    con = _db()
    try:
        n = con.execute("SELECT count(*) FROM chunks" + where, args).fetchone()[0]
        if not n:
            return "No indexed documents (run index_docs first)."
        notes = []

        kw = {}  # (path, idx) -> (keyword rank, snippet around the match)
        match = _fts_query(query)
        if match:
            sql = ("SELECT path, idx, snippet(chunks_fts, 0, '', '', ' … ', 64) FROM chunks_fts "
                   "WHERE chunks_fts MATCH ?" + where.replace("WHERE", "AND") + " ORDER BY rank LIMIT ?")
            try:
                for rank, (path, idx, snip) in enumerate(con.execute(sql, (match, *args, CANDIDATES)), 1):
                    kw[(path, idx)] = (rank, snip)
            except sqlite3.Error as e:
                notes.append(f"Note: keyword search failed ({e}); ranked by meaning only.")

        vec, cos = {}, {}
        try:
            vec, cos = _vector_ranking(con, query, n, where, args)
        except Exception as e:
            if not kw:
                return f"Error: embedding the query failed ({e}). Is Ollama running?"
            notes.append(f"Note: embedding the query failed ({e}); keyword matches only.")

        fused = {}
        for ranking in (vec, {key: r for key, (r, _) in kw.items()}):
            for key, r in ranking.items():
                fused[key] = fused.get(key, 0.0) + 1.0 / (RRF_K + r)
        out = []
        for key in sorted(fused, key=fused.get, reverse=True)[:k]:
            if key in kw:
                snippet = kw[key][1]
            else:
                row = con.execute("SELECT text FROM chunks WHERE path=? AND idx=?", key).fetchone()
                if not row:
                    continue
                snippet = row[0]
            tags = ([f"cos {cos[key]:.2f}"] if key in cos else []) + \
                [f"kw #{kw[key][0]}" if key in kw else "no kw"]
            out.append(f"{len(out) + 1}. [{', '.join(tags)}] {key[0]}\n   "
                       + " ".join(snippet.split())[:500])
        if not out:
            return "\n".join(notes + ["No matching passages."])
        return "\n\n".join(notes + out)
    finally:
        con.close()


if __name__ == "__main__":
    mcp.run()
