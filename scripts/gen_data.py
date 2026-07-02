"""Generate the map data into public/ for the Vite build.

Runs the two data builders and drops their output where Vite expects static assets:
  public/interactive_map.svg  public/spaces.json  public/wystawcy_auto.json  public/logos/

Vite copies public/ verbatim into dist/ (the app fetches these by fixed relative URL, so
they must not be bundled/hashed). Front-end bundling (JS/CSS/deps) is Vite's job, not this
script's. Invoked by `npm run gen` (and thus `npm run build` / `npm run dev`).
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fetcher   # noqa: E402
import matcher   # noqa: E402

PUBLIC = ROOT / "public"
DATA = ROOT / "data"
CACHE = ROOT / ".cache"


def main():
    shutil.rmtree(PUBLIC, ignore_errors=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    fetcher.run(out_dir=PUBLIC, cache_dir=CACHE)
    matcher.build(str(DATA / "input.svg"),
                  str(PUBLIC / "interactive_map.svg"),
                  str(PUBLIC / "spaces.json"))
    print(f"Data generated -> {PUBLIC}")


if __name__ == "__main__":
    main()
