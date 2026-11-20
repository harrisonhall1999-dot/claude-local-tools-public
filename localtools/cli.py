#!/usr/bin/env python3
"""localtools: run Python against this project's tools so only the printout reaches Claude.

  localtools tools [WORDS] [--detail name|summary|full]   find tools (nothing is loaded)
  localtools run RECIPE_OR_SCRIPT [ARGS...]               run a saved recipe or a .py file
  localtools exec 'CODE'                                  run a snippet; `import localtools as lt` is done
  localtools recipes                                      list saved recipes (localtools/recipes/)

Scripts get the shared venv and `import localtools`. They run with your normal permissions, so
keep them read-only like the tools themselves.
"""
import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import localtools  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "tools":
        detail = "summary"
        if "--detail" in rest:
            i = rest.index("--detail")
            detail = rest[i + 1] if i + 1 < len(rest) else detail
            rest = rest[:i] + rest[i + 2:]
        print(localtools.tools(" ".join(rest), detail))
    elif cmd == "recipes":
        print("\n".join(localtools.list_recipes()) or "No recipes yet.")
    elif cmd == "run" and rest:
        target = rest[0]
        path = target if target.endswith(".py") else os.path.join(localtools.RECIPES_DIR, f"{target}.py")
        if not os.path.isfile(path):
            print(f"Error: no script or recipe {target!r}. Recipes: {', '.join(localtools.list_recipes())}")
            return 1
        sys.argv = [path, *rest[1:]]
        runpy.run_path(path, run_name="__main__")
    elif cmd == "exec" and rest:
        exec(compile(" ".join(rest), "<localtools exec>", "exec"), {"lt": localtools, "localtools": localtools})
    else:
        print(__doc__.strip())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
