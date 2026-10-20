"""Study-aid MCP server: turn study material into an Anki deck.

Local, no model needed. Builds a real Anki package (.apkg) you import by
double-clicking, so Claude can turn an outline or a list of Q&A into
flashcards for bar/exam prep without you retyping them.
"""

import os
import time

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("study")


@mcp.tool()
def make_anki(deck_name: str, cards: list[dict], output_path: str = "") -> str:
    """Build an Anki deck (.apkg) from a list of cards.

    Each card is {"front": "...", "back": "...", "tags": "optional space-separated"}.
    Import the .apkg into Anki by double-clicking it. Basic (front/back) notes.

    Args:
        deck_name: The deck's name as it will appear in Anki.
        cards: List of {"front", "back", optional "tags"} dicts.
        output_path: Where to write the .apkg; defaults to ~/Downloads/<deck>.apkg.

    Returns:
        Where the deck was written and how many cards it has.
    """
    import genanki

    if not cards:
        return "Error: no cards given"
    seed = (deck_name + str(time.time()))
    model = genanki.Model(
        abs(hash("basic-" + deck_name)) % (10 ** 10),
        "Basic (Claude Local Tools)",
        fields=[{"name": "Front"}, {"name": "Back"}],
        templates=[{"name": "Card 1",
                    "qfmt": "{{Front}}",
                    "afmt": "{{FrontSide}}<hr id=answer>{{Back}}"}],
    )
    deck = genanki.Deck(abs(hash(seed)) % (10 ** 10), deck_name)
    n = 0
    for c in cards:
        front, back = str(c.get("front", "")).strip(), str(c.get("back", "")).strip()
        if not front or not back:
            continue
        tags = str(c.get("tags", "")).split()
        deck.add_note(genanki.Note(model=model, fields=[front, back], tags=tags))
        n += 1
    if not n:
        return "Error: no cards had both a front and a back"
    out = os.path.expanduser(output_path) if output_path else \
        os.path.expanduser(f"~/Downloads/{deck_name}.apkg")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    genanki.Package(deck).write_to_file(out)
    return f"Wrote {out} ({n} cards). Double-click it to import into Anki."


if __name__ == "__main__":
    mcp.run()
