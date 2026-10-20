"""Read-only access to classic Outlook for Mac's local copy of mail and calendar.

Shared by server.py (MCP) and cli.py. Nothing here talks to Microsoft: Outlook already syncs the
mailbox to this Mac, so no sign-in or tenant approval is needed.

- Mail lists and search read Outlook's own database (Outlook.sqlite, opened read-only). Works
  whether or not Outlook is running; it's as fresh as Outlook's last sync.
- Message bodies and calendar details come from Outlook over AppleScript (`osascript`), which
  needs Outlook running (it launches it for interactive calls; background syncs skip it).
- `sync()` expands the calendar (recurring series included) into a local store, logs changes
  between syncs, and writes the daily briefing once a day.

Never sends, moves, deletes or marks anything. Store: ~/Library/Application Support/
claude-local-tools/outlook (owner-only).
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import subprocess
from datetime import date, datetime, time, timedelta, timezone

PROFILE = os.path.expanduser(os.environ.get(
    "OUTLOOK_PROFILE",
    "~/Library/Group Containers/UBF8T346G9.Office/Outlook/Outlook 15 Profiles/Main Profile"))
SRC_DB = os.path.join(PROFILE, "Data", "Outlook.sqlite")
DATA_DIR = os.path.expanduser(os.environ.get(
    "OUTLOOK_DATA", "~/Library/Application Support/claude-local-tools/outlook"))
STORE = os.path.join(DATA_DIR, "outlook.db")
BRIEF_DIR = os.path.join(DATA_DIR, "briefings")
BRIEF_HOUR = 6  # first sync at or after this hour writes the day's briefing

EPOCH_1601 = 11644473600  # seconds from 1601-01-01 to 1970-01-01 (calendar times are minutes since 1601)
SEP = "\x1e"              # record separator in AppleScript output
FS = "\x1f"               # field separator
HIDDEN_FOLDERS = {"Deleted Items", "Junk Email", "Drafts", "Outbox", "Sync Issues", "Conflicts",
                  "Local Failures", "Server Failures", "Conversation History"}


def local_tz():
    return datetime.now().astimezone().tzinfo


def _private_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    os.chmod(path, 0o700)
    return path


# ---------- Outlook's database (read-only) ----------

def source() -> sqlite3.Connection:
    if not os.path.exists(SRC_DB):
        raise RuntimeError(f"Outlook database not found at {SRC_DB}. Is classic (legacy) Outlook "
                           "set up? New Outlook keeps no readable local database.")
    con = sqlite3.connect(f"file:{SRC_DB}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _folders(con) -> dict[int, str]:
    return {r[0]: r[1] or "" for r in con.execute("SELECT Record_RecordID, Folder_Name FROM Folders")}


def _ts(unix) -> str:
    return datetime.fromtimestamp(unix, local_tz()).strftime("%Y-%m-%d %H:%M") if unix else ""


def _mail_row(r, folders) -> dict:
    return {"id": r["Record_RecordID"], "received": _ts(r["Message_TimeReceived"]),
            "folder": folders.get(r["Record_FolderID"], str(r["Record_FolderID"])),
            "from": r["Message_SenderList"] or "", "from_addr": r["Message_SenderAddressList"] or "",
            "to": r["Message_ToRecipientAddressList"] or "",
            "subject": r["Message_NormalizedSubject"] or "",
            "preview": re.sub(r"\s+", " ", r["Message_Preview"] or "").strip(),
            "unread": not r["Message_ReadFlag"], "flagged": bool(r["Record_FlagStatus"]),
            "attachments": bool(r["Message_HasAttachment"]),
            "focused": r["Message_InferenceClassification"] != 1,
            "thread": r["Conversation_ConversationID"]}


def search_mail(query: str = "", sender: str = "", folder: str = "", since_hours: float = 0,
                days: float = 30, unread_only: bool = False, flagged_only: bool = False,
                focused_only: bool = False, limit: int = 25) -> list[dict]:
    """Newest first. query matches subject, preview and sender (all words must match)."""
    con = source()
    folders = _folders(con)
    where, args = ["Message_MarkedForDelete = 0"], []
    hours = since_hours or days * 24
    if hours:
        where.append("Message_TimeReceived >= ?")
        args.append(int(datetime.now().timestamp() - hours * 3600))
    if folder:
        ids = [i for i, n in folders.items() if n.lower() == folder.lower()]
        if not ids:
            raise RuntimeError(f"No folder named {folder!r}. Folders: "
                               + ", ".join(sorted({n for n in folders.values() if n and 'Placeholder' not in n})))
        where.append(f"Record_FolderID IN ({','.join('?' * len(ids))})")
        args += ids
    else:
        hidden = [i for i, n in folders.items() if n in HIDDEN_FOLDERS]
        if hidden:
            where.append(f"Record_FolderID NOT IN ({','.join('?' * len(hidden))})")
            args += hidden
    for word in query.split():
        where.append("(Message_NormalizedSubject LIKE ? OR Message_Preview LIKE ? OR Message_SenderList LIKE ?"
                     " OR Message_SenderAddressList LIKE ?)")
        args += [f"%{word}%"] * 4
    if sender:
        where.append("(Message_SenderList LIKE ? OR Message_SenderAddressList LIKE ?)")
        args += [f"%{sender}%"] * 2
    if unread_only:
        where.append("Message_ReadFlag = 0")
    if flagged_only:
        where.append("Record_FlagStatus != 0")
    if focused_only:
        where.append("Message_InferenceClassification != 1")
    sql = (f"SELECT * FROM Mail WHERE {' AND '.join(where)} "
           f"ORDER BY Message_TimeReceived DESC LIMIT ?")
    return [_mail_row(r, folders) for r in con.execute(sql, args + [int(limit)])]


def thread(message_id: int) -> list[dict]:
    con = source()
    folders = _folders(con)
    row = con.execute("SELECT Conversation_ConversationID FROM Mail WHERE Record_RecordID=?",
                      (message_id,)).fetchone()
    if not row:
        raise RuntimeError(f"No message with id {message_id}.")
    rows = con.execute("SELECT * FROM Mail WHERE Conversation_ConversationID=? AND Message_MarkedForDelete=0 "
                       "ORDER BY Message_TimeReceived", (row[0],))
    return [_mail_row(r, folders) for r in rows]


def write_csv(rows: list[dict], out_path: str) -> str:
    out_path = os.path.expanduser(out_path)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()}
                        for r in rows)
    return f"Wrote {len(rows)} rows to {out_path}"


# ---------- AppleScript ----------

def outlook_running() -> bool:
    return subprocess.run(["pgrep", "-xq", "Microsoft Outlook"]).returncode == 0


def osa(script: str, timeout: int = 120) -> str:
    p = subprocess.run(["osascript", "-"], input=script, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        err = p.stderr.strip()
        if "-1743" in err or "Not authorized" in err:
            raise RuntimeError("macOS blocked control of Outlook. Allow it in System Settings > "
                               "Privacy & Security > Automation, then retry.")
        raise RuntimeError(f"Outlook AppleScript failed: {err}")
    return p.stdout.rstrip("\n")


_READ = """
set FS to (ASCII character 31)
tell application "Microsoft Outlook"
  set m to message id %d
  set out to (subject of m) & FS
  try
    set snd to sender of m
    set out to out & (name of snd) & " <" & (address of snd) & ">"
  end try
  set out to out & FS
  repeat with kind in {"to", "cc"}
    if kind as text is "to" then
      set rs to to recipients of m
    else
      set rs to cc recipients of m
    end if
    repeat with r in rs
      try
        set ea to email address of r
        set out to out & (name of ea) & " <" & (address of ea) & ">; "
      end try
    end repeat
    set out to out & FS
  end repeat
  set out to out & ((time received of m) as «class isot» as string) & FS
  repeat with a in attachments of m
    set out to out & (name of a) & "; "
  end repeat
  set out to out & FS & (plain text content of m)
  return out
end tell
"""

_QUOTE_START = re.compile(
    r"^(\s*-{2,}\s*Original Message\s*-{2,}|\s*From:\s.+\n\s*(Sent|Date):\s|\s*On .{6,200} wrote:\s*$"
    r"|_{20,}\s*$)", re.M | re.I)


def read_mail(message_id: int, strip_quoted: bool = True, max_chars: int = 8000) -> dict:
    raw = osa(_READ % int(message_id))
    subject, frm, to, cc, received, atts, body = (raw.split(FS) + [""] * 7)[:7]
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    quoted = False
    if strip_quoted:
        m = _QUOTE_START.search(body)
        if m and m.start() > 0:
            body, quoted = body[:m.start()].rstrip(), True
    truncated = len(body) > max_chars > 0
    return {"id": message_id, "subject": subject, "from": frm, "to": to.rstrip("; "),
            "cc": cc.rstrip("; "), "received": received.replace("T", " ")[:16],
            "attachments": [a for a in atts.split("; ") if a],
            "body": body[:max_chars] if truncated else body,
            "note": "; ".join(n for n, on in (("earlier quoted messages removed (strip_quoted=False keeps them)", quoted),
                                              (f"body cut at {max_chars} chars", truncated)) if on)}


def save_attachments(message_id: int, out_dir: str) -> str:
    out_dir = os.path.abspath(os.path.expanduser(out_dir))
    os.makedirs(out_dir, exist_ok=True)
    esc = out_dir.replace('"', '\\"')
    script = f"""
tell application "Microsoft Outlook"
  set out to ""
  repeat with a in attachments of message id {int(message_id)}
    set p to "{esc}/" & (name of a)
    save a in (POSIX file p)
    set out to out & p & linefeed
  end repeat
  return out
end tell"""
    saved = [p for p in osa(script).splitlines() if p]
    return f"Saved {len(saved)} attachment(s):\n" + "\n".join(saved) if saved else "No attachments."


# ---------- Calendar ----------

def _min1601(dt: datetime) -> int:
    return int((dt.timestamp() + EPOCH_1601) // 60)


def _calendar_ids(con, start: datetime, end: datetime) -> list[tuple[int, int]]:
    """(record id, folder id) of recurring series and one-off events that can touch the window.
    Exceptions to a series are skipped: the series' iCalendar data already includes them."""
    rows = con.execute(
        "SELECT Record_RecordID, Record_FolderID FROM CalendarEvents WHERE Calendar_MasterRecordID=0 AND "
        "(Calendar_IsRecurring=1 OR (Calendar_EndDateUTC >= ? AND Calendar_StartDateUTC <= ?))",
        (_min1601(start), _min1601(end)))
    return [(r[0], r[1]) for r in rows]


def _fetch_ics(ids: list[int]) -> dict[int, str]:
    out = {}
    for i in range(0, len(ids), 150):
        chunk = ids[i:i + 150]
        script = f"""
set SEP to (ASCII character 30)
set FS to (ASCII character 31)
set out to ""
tell application "Microsoft Outlook"
  repeat with i in {{{",".join(map(str, chunk))}}}
    try
      set out to out & i & FS & (icalendar data of calendar event id i) & SEP
    end try
  end repeat
end tell
return out"""
        for rec in osa(script, timeout=600).split(SEP):
            if FS in rec:
                rid, ics = rec.split(FS, 1)
                out[int(rid.strip())] = ics
    return out


def _as_local(v) -> tuple[str, bool]:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=local_tz())
        return v.astimezone(local_tz()).strftime("%Y-%m-%d %H:%M"), False
    return v.isoformat(), True


def _person(p) -> str:
    name = p.params.get("CN", "") if hasattr(p, "params") else ""
    addr = str(p).replace("mailto:", "").replace("MAILTO:", "")
    return f"{name} <{addr}>" if name and name != addr else addr


def _expand(ics: str, start: datetime, end: datetime) -> list[dict]:
    import icalendar
    import recurring_ical_events
    cal = icalendar.Calendar.from_ical(ics)
    series = any("RRULE" in c for c in cal.walk("VEVENT"))
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        s, all_day = _as_local(ev.decoded("DTSTART"))
        e = ev.decoded("DTEND") if "DTEND" in ev else ev.decoded("DTSTART")
        e, _ = _as_local(e)
        if str(ev.get("X-MICROSOFT-CDO-ALLDAYEVENT", "")).upper() == "TRUE":
            all_day = True
        attendees = ev.get("ATTENDEE", [])
        attendees = attendees if isinstance(attendees, list) else [attendees]
        out.append({
            "uid": str(ev.get("UID", "")), "start": s, "end": e, "all_day": all_day,
            "summary": str(ev.get("SUMMARY", "")), "location": str(ev.get("LOCATION", "")),
            "organizer": _person(ev["ORGANIZER"]) if "ORGANIZER" in ev else "",
            "attendees": [_person(a) for a in attendees],
            "busy": str(ev.get("X-MICROSOFT-CDO-BUSYSTATUS", "")),
            "recurring": series,
            "description": re.sub(r"\n{3,}", "\n\n", str(ev.get("DESCRIPTION", "")).replace("\r", "")).strip(),
        })
    return out


def store() -> sqlite3.Connection:
    _private_dir(DATA_DIR)
    con = sqlite3.connect(STORE)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS events(key TEXT PRIMARY KEY, record_id INTEGER, calendar TEXT,
        uid TEXT, start TEXT, end TEXT, all_day INTEGER, summary TEXT, location TEXT, organizer TEXT,
        attendees TEXT, busy TEXT, recurring INTEGER, description TEXT);
    CREATE TABLE IF NOT EXISTS cal_log(at TEXT, change TEXT, key TEXT, summary TEXT, start TEXT,
        detail TEXT);
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    """)
    os.chmod(STORE, 0o600)
    return con


def _meta(con, k, v=None):
    if v is None:
        r = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else None
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, json.dumps(v)))


def sync_calendar(past_days: int = 14, future_days: int = 120) -> dict:
    """Expand every calendar event in the window into the store; log what changed since last time."""
    tz = local_tz()
    today = datetime.combine(date.today(), time(), tz)
    start, end = today - timedelta(days=past_days), today + timedelta(days=future_days)
    src = source()
    folders = _folders(src)
    ids = _calendar_ids(src, start, end)
    ics = _fetch_ics([i for i, _ in ids])
    events, failed = {}, 0
    for rid, fid in ids:
        if rid not in ics:
            continue
        try:
            occ = _expand(ics[rid], start, end)
        except Exception:
            failed += 1
            continue
        for o in occ:
            key = f"{o['uid'] or rid}|{o['start']}" if not o["recurring"] else f"{o['uid'] or rid}|{o['start'][:10]}"
            events[key] = {"key": key, "record_id": rid, "calendar": folders.get(fid, ""), **o}
    con = store()
    lo, hi = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    old = {r["key"]: dict(r) for r in con.execute("SELECT * FROM events WHERE start >= ? AND start < ?", (lo, hi))}
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    first_run = _meta(con, "last_calendar_sync") is None
    log = []
    future = now[:10]
    if not first_run:
        for k, e in events.items():
            if e["start"] < future:
                continue
            o = old.get(k)
            if o is None:
                log.append((now, "added", k, e["summary"], e["start"], f"{e['start']}-{e['end'][11:]} {e['location']}".strip()))
            else:
                diff = [f"{f}: {o[f]!r} -> {e[f]!r}" for f in ("start", "end", "summary", "location")
                        if str(o[f]) != str(e[f])]
                if diff:
                    log.append((now, "changed", k, e["summary"], e["start"], "; ".join(diff)))
        for k, o in old.items():
            if k not in events and o["start"] >= future:
                log.append((now, "removed", k, o["summary"], o["start"], ""))
    con.execute("DELETE FROM events WHERE start >= ? AND start < ?", (lo, hi))
    con.executemany(
        "INSERT OR REPLACE INTO events VALUES(:key,:record_id,:calendar,:uid,:start,:end,:all_day,:summary,"
        ":location,:organizer,:attendees,:busy,:recurring,:description)",
        [{**e, "attendees": json.dumps(e["attendees"])} for e in events.values()])
    con.executemany("INSERT INTO cal_log VALUES(?,?,?,?,?,?)", log)
    _meta(con, "last_calendar_sync", now)
    _meta(con, "calendar_window", [lo, hi])
    con.commit()
    return {"events": len(events), "series_and_items_read": len(ics), "unreadable": failed,
            "changes_logged": len(log), "window": [lo, hi], "at": now}


def _parse_day(s: str) -> date:
    s = (s or "today").strip().lower()
    if s == "today":
        return date.today()
    if s == "tomorrow":
        return date.today() + timedelta(days=1)
    if s == "yesterday":
        return date.today() - timedelta(days=1)
    return date.fromisoformat(s)


def ensure_fresh(max_age_min: int = 30) -> str:
    """Sync the calendar if the store is older than max_age_min and Outlook can be asked."""
    con = store()
    last = _meta(con, "last_calendar_sync")
    if last and datetime.now() - datetime.strptime(last, "%Y-%m-%d %H:%M") < timedelta(minutes=max_age_min):
        return f"calendar as of {last}"
    sync_calendar()
    return f"calendar as of {_meta(store(), 'last_calendar_sync')} (just synced)"


def calendar(start: str = "today", days: int = 7, query: str = "", calendar_name: str = "",
             details: bool = False) -> list[dict]:
    d0 = _parse_day(start)
    lo, hi = d0.isoformat(), (d0 + timedelta(days=max(1, days))).isoformat()
    con = store()
    win = _meta(con, "calendar_window")
    if not win or lo < win[0] or hi > win[1]:
        raise RuntimeError(f"Synced window is {win}; ask for dates inside it, or run ol_sync with a wider window.")
    where, args = ["start >= ? AND start < ?"], [lo, hi]
    for w in query.split():
        where.append("(summary LIKE ? OR location LIKE ? OR description LIKE ? OR organizer LIKE ?)")
        args += [f"%{w}%"] * 4
    if calendar_name:
        where.append("calendar LIKE ?")
        args.append(f"%{calendar_name}%")
    rows = []
    for r in con.execute(f"SELECT * FROM events WHERE {' AND '.join(where)} ORDER BY start", args):
        e = dict(r)
        e["attendees"] = json.loads(e["attendees"])
        e["all_day"], e["recurring"] = bool(e["all_day"]), bool(e["recurring"])
        if not details:
            e["attendees"] = len(e["attendees"])
            e.pop("description")
        e.pop("key")
        e.pop("uid")
        rows.append(e)
    return rows


def free_slots(day: str = "today", start_hour: int = 9, end_hour: int = 18, min_minutes: int = 30,
               days: int = 1) -> list[dict]:
    """Open gaps between busy events (free/tentative-free and all-day events don't block)."""
    out = []
    d0 = _parse_day(day)
    for n in range(max(1, days)):
        d = d0 + timedelta(days=n)
        busy = sorted((e["start"][11:], e["end"][11:] if e["end"][:10] == d.isoformat() else "24:00")
                      for e in calendar(d.isoformat(), 1)
                      if not e["all_day"] and e["busy"].upper() not in ("FREE",))
        cur = f"{start_hour:02d}:00"
        stop = f"{end_hour:02d}:00"
        for s, e in busy + [(stop, stop)]:
            s = min(max(s, cur), stop)
            if _mins(s) - _mins(cur) >= min_minutes:
                out.append({"date": d.isoformat(), "start": cur, "end": s, "minutes": _mins(s) - _mins(cur)})
            cur = max(cur, min(e, stop))
    return out


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def calendar_changes(since_hours: float = 24) -> list[dict]:
    cutoff = (datetime.now() - timedelta(hours=since_hours)).strftime("%Y-%m-%d %H:%M")
    return [dict(r) for r in store().execute(
        "SELECT at, change, summary, start, detail FROM cal_log WHERE at >= ? ORDER BY at, start", (cutoff,))]


# ---------- Sync + briefing ----------

def _line(m: dict) -> str:
    flags = "".join(f for f, on in (("●", m["unread"]), ("⚑", m["flagged"]), ("📎", m["attachments"])) if on)
    prev = m["preview"][:160] + ("…" if len(m["preview"]) > 160 else "")
    return f"- {flags} **{m['from'] or m['from_addr']}** — {m['subject'] or '(no subject)'} " \
           f"<sub>{m['received'][5:]} · id {m['id']}</sub>\n  {prev}"


def _event_line(e: dict) -> str:
    when = "all day" if e["all_day"] else f"{e['start'][11:]}–{e['end'][11:]}"
    bits = [b for b in (e["location"], e["calendar"] if e["calendar"] not in ("Calendar", "") else "") if b]
    tag = " ⟳" if e["recurring"] else ""
    return f"- {when} **{e['summary'] or '(no title)'}**{tag}" + (f" — {' · '.join(bits)}" if bits else "")


def briefing(write: bool = True) -> str:
    now = datetime.now()
    today = date.today()
    parts = [f"# Briefing — {today:%A, %B %-d, %Y}", f"_Generated {now:%H:%M} from Outlook on this Mac._", ""]
    try:
        status = ensure_fresh(30) if outlook_running() else f"calendar as of {_meta(store(), 'last_calendar_sync')} (Outlook closed)"
        for label, d in (("Today", today), ("Tomorrow", today + timedelta(days=1))):
            evs = [e for e in calendar(d.isoformat(), 1) if e["busy"].upper() != "FREE" or e["all_day"]]
            parts += [f"## {label}", *([_event_line(e) for e in evs] or ["- nothing scheduled"]), ""]
        week = calendar((today + timedelta(days=2)).isoformat(), 5)
        if week:
            parts += ["## Rest of the week"]
            for e in week:
                parts.append(_event_line(e).replace("- ", f"- {e['start'][5:10]} ", 1))
            parts.append("")
        ch = calendar_changes(24)
        if ch:
            parts += ["## Calendar changes (last 24 h)"]
            parts += [f"- {c['change']}: **{c['summary']}** {c['start']} {c['detail']}".rstrip() for c in ch[:30]]
            parts.append("")
        parts.insert(2, f"_{status}._")
    except Exception as e:
        parts += [f"_Calendar unavailable: {e}_", ""]
    unread = search_mail(since_hours=24, unread_only=True, focused_only=True, limit=40, folder="Inbox")
    other = search_mail(since_hours=24, unread_only=True, limit=200, folder="Inbox")
    n_other = sum(1 for m in other if not m["focused"])
    parts += [f"## Unread in Focused inbox (last 24 h): {len(unread)}", *[_line(m) for m in unread], ""]
    if n_other:
        parts += [f"_Plus {n_other} unread in Other._", ""]
    flagged = search_mail(flagged_only=True, days=60, limit=20)
    if flagged:
        parts += ["## Flagged (last 60 days)", *[_line(m) for m in flagged], ""]
    text = "\n".join(parts).rstrip() + "\n"
    if write:
        _private_dir(BRIEF_DIR)
        for name in (f"{today.isoformat()}.md", "latest.md"):
            p = os.path.join(BRIEF_DIR, name)
            with open(p, "w") as f:
                f.write(text)
            os.chmod(p, 0o600)
    return text


def sync(force_briefing: bool = False) -> dict:
    """Background job: refresh the calendar when Outlook is open, write the day's briefing once."""
    result = {"at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if outlook_running():
        result["calendar"] = sync_calendar()
    else:
        result["calendar"] = "skipped: Outlook isn't running (mail search still works from its database)"
    today_file = os.path.join(BRIEF_DIR, f"{date.today().isoformat()}.md")
    if force_briefing or (not os.path.exists(today_file) and datetime.now().hour >= BRIEF_HOUR):
        briefing()
        result["briefing"] = today_file
    con = store()
    _meta(con, "last_sync", result)
    con.commit()
    return result
