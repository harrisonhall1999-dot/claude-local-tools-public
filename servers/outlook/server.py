"""Outlook MCP server (read-only): your school mail and calendar from classic Outlook on this Mac.

Use this instead of asking the user to export emails or calendars, or to paste them. It reads the
copy Outlook already syncs to the Mac, so it works without the Microsoft 365 connector.
No model, no RAM to speak of.

- Mail lists/search come from Outlook's database: instant, and they work with Outlook closed.
  Each row has a preview (~250 chars). Open a full message with ol_read only when the preview
  isn't enough.
- ol_read, ol_attachments and calendar syncs ask Outlook over AppleScript; Outlook opens if needed.
- A background job (`outlook schedule on`) refreshes the calendar every 30 min and writes a daily
  briefing; start with ol_briefing for "what's going on today / this week".

Read-only: nothing can send, reply, move, delete or mark mail. For drafting a reply, write the
text in chat for the user to send. Mail is private: keep it out of gemini and other cloud tools
(local_llm is fine for bulk summarizing). Use out_path for long lists so rows go to disk.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.mcpserver import MCPServer

import core

mcp = MCPServer("outlook")


def _err(e: Exception) -> str:
    return f"Error: {e}"


def _rows(rows: list, out_path: str, empty: str) -> str:
    if out_path:
        return core.write_csv(rows, out_path)
    return json.dumps(rows, indent=1, ensure_ascii=False) if rows else empty


@mcp.tool()
def ol_search(query: str = "", sender: str = "", folder: str = "", days: float = 30,
              since_hours: float = 0, unread_only: bool = False, flagged_only: bool = False,
              focused_only: bool = False, limit: int = 25, out_path: str = "") -> str:
    """Search or list mail, newest first: id, received, folder, from, to, subject, preview,
    unread/flagged/attachments, focused (vs Other), thread id. Instant, local.
    query: words that must all appear in subject, preview or sender (not full bodies).
    folder: e.g. "Inbox", "Sent Items", "Archive" (default: all but Deleted/Junk/Drafts).
    since_hours overrides days. For more than ~40 rows pass out_path (.csv) to keep them out of
    context. Then ol_read(id) for a full message, ol_thread(id) for its conversation."""
    try:
        rows = core.search_mail(query, sender, folder, since_hours, days, unread_only, flagged_only,
                                focused_only, limit)
        return _rows(rows, out_path, "No matching mail.")
    except Exception as e:
        return _err(e)


@mcp.tool()
def ol_read(message_id: int, strip_quoted: bool = True, max_chars: int = 8000) -> str:
    """Full text of one message: subject, from, to, cc, received, attachment names, plain-text
    body. strip_quoted drops the earlier messages quoted below a reply (use ol_thread to see
    those individually). ~1 s; opens Outlook if it's closed."""
    try:
        return json.dumps(core.read_mail(message_id, strip_quoted, max_chars), indent=1, ensure_ascii=False)
    except Exception as e:
        return _err(e)


@mcp.tool()
def ol_thread(message_id: int) -> str:
    """Every message in the same conversation as message_id, oldest first (metadata + preview)."""
    try:
        return _rows(core.thread(message_id), "", "No thread found.")
    except Exception as e:
        return _err(e)


@mcp.tool()
def ol_attachments(message_id: int, out_dir: str) -> str:
    """Save a message's attachments to out_dir and return their paths (then read them with
    read_document / to_markdown rather than opening them here)."""
    try:
        return core.save_attachments(message_id, out_dir)
    except Exception as e:
        return _err(e)


@mcp.tool()
def ol_calendar(start: str = "today", days: int = 7, query: str = "", calendar: str = "",
                details: bool = False) -> str:
    """Calendar events with recurring series expanded: start, end, all_day, summary, location,
    calendar (incl. shared ones), organizer, busy (BUSY/TENTATIVE/FREE/OOF), recurring.
    start: "today", "tomorrow" or YYYY-MM-DD. query matches title, location, organizer, notes.
    details=True adds attendee lists and the invite text (longer). Synced window is ~2 weeks back
    to ~4 months ahead; refreshes first if the last sync is over 30 min old (~10 s)."""
    try:
        status = core.ensure_fresh(30)
        rows = core.calendar(start, days, query, calendar, details)
        return f"({status})\n" + _rows(rows, "", "No events in that range.")
    except Exception as e:
        return _err(e)


@mcp.tool()
def ol_free(day: str = "today", days: int = 1, start_hour: int = 9, end_hour: int = 18,
            min_minutes: int = 30) -> str:
    """Open time slots between busy/tentative events, for scheduling. Events marked free and
    all-day events don't block."""
    try:
        core.ensure_fresh(30)
        return _rows(core.free_slots(day, start_hour, end_hour, min_minutes, days), "", "No free slots.")
    except Exception as e:
        return _err(e)


@mcp.tool()
def ol_changes(since_hours: float = 24) -> str:
    """Calendar changes found between syncs: future events added, moved/renamed/relocated, or
    removed (cancelled). Needs the background sync (or earlier ol_calendar calls) to compare."""
    try:
        return _rows(core.calendar_changes(since_hours), "", "No calendar changes logged in that window.")
    except Exception as e:
        return _err(e)


@mcp.tool()
def ol_briefing(refresh: bool = False) -> str:
    """Today's briefing (Markdown): today's and tomorrow's events, rest of the week, calendar
    changes, unread Focused mail from the last 24 h with previews and ids, flagged mail.
    Written each morning by the background job; refresh=True rebuilds it now (~10 s)."""
    try:
        path = os.path.join(core.BRIEF_DIR, "latest.md")
        from datetime import date
        stale = not os.path.exists(os.path.join(core.BRIEF_DIR, f"{date.today().isoformat()}.md"))
        if refresh or stale:
            return core.briefing()
        with open(path) as f:
            return f.read()
    except Exception as e:
        return _err(e)


@mcp.tool()
def ol_sync() -> str:
    """Refresh the calendar store now (the background job does this every 30 min)."""
    try:
        return json.dumps(core.sync_calendar(), indent=1)
    except Exception as e:
        return _err(e)


if __name__ == "__main__":
    mcp.run()
