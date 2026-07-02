# Bazyliszek — interactive exhibitor map

An interactive floor-plan of the event: an SVG map where every stall is clickable and
linked to the exhibitor directory (name, description, social links, logo). Fully static
and self-contained — built with Vite and deployed to GitHub Pages.

## Structure

```
scripts/   fetcher.py    – pulls exhibitor data + logos from the Google Sheet
           matcher.py    – tags the floor-plan SVG's stall shapes and labels
           gen_data.py   – runs both, writing generated data into public/
web/       index.html    – Vite entry
           map.js        – app (imports panzoom, SweetAlert2, Open Sans, map.css)
           map.css       – styles
data/      input.svg     – source floor-plan (Affinity export)
public/    generated map data (git-ignored) — Vite copies it verbatim into dist/
dist/      Vite build output (git-ignored, rebuilt on deploy)
.cache/    cached spreadsheet download (git-ignored)
vite.config.js  package.json  pyproject.toml  ...
.github/workflows/deploy.yml – builds and deploys to GitHub Pages
```

**Two-stage build:** Python generates the *data* (`public/interactive_map.svg`,
`spaces.json`, `wystawcy_auto.json`, `logos/`), then **Vite** bundles the *front-end*
(minifies + hashes JS/CSS, bundles the npm deps and the Open Sans font, copies `public/`
into `dist/`). No CDN — everything is bundled and works offline.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python 3.14 + deps from `uv.lock`)
- [Node.js](https://nodejs.org/) 22+ and npm
- The exhibitor **Google Sheet must be publicly exportable**.
- `SHEET_ID` — the sheet id via environment (intentionally **not** hardcoded so the repo
  can be public):

  ```sh
  export SHEET_ID=your_google_sheet_id
  ```

  In CI it comes from a GitHub Actions **repository variable** (Settings → Secrets and
  variables → Actions → Variables → `SHEET_ID`). It's config, not a credential.

## Setup & build

```sh
npm ci                 # or: npm install
npm run build          # runs the Python data step (uv) then `vite build` -> dist/
```

The first run downloads the source spreadsheet (~57 MB) into `.cache/`; delete that file
to force a fresh pull.

## Develop / preview

```sh
npm run dev            # regenerate data + Vite dev server (HMR)
npm run preview        # serve the built dist/ locally
```

The built site is fully self-contained and works offline (fonts/JS/CSS all bundled).

## Data scripts standalone

```sh
uv run scripts/gen_data.py    # -> public/ (both fetcher + matcher)
```

## Deploy

Push to the default branch (`main`); the Actions workflow installs uv + Node, runs
`npm run build`, and publishes `dist/` to GitHub Pages. Nothing generated is committed —
it's rebuilt every deploy.

> Note: the local branch may be `master`. Rename it (`git branch -m master main`) and set
> `main` as the GitHub default branch, or the workflow trigger won't fire.

## Regenerating `data/input.svg`

Out of scope for this repo. `matcher.py` assumes an Affinity export with **flatten
transforms** on (stalls at literal coordinates, blue-stroked stalls / gray-fill zones);
see the docstring in `scripts/matcher.py` for the shape contract it relies on.
