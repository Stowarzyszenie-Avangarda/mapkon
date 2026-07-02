"""Parse an SVG floor-plan for stall shapes and the label drawn inside each one.

This is pure geometry: it does NOT know about exhibitor names. It finds every stall
shape and the text drawn on it (a number like "110", or a name like "RGFK" for stalls
that are presented by name). The viewer (map.html) joins those drawn labels to the
directory in wystawcy.json at runtime.

Two things make matching non-trivial:
  * Stalls are drawn as <rect> AND as rectangle-shaped <path> (the guest stalls; one is
    even rotated). Both are handled as polygons.
  * The SVG is exported from Affinity with "Flatten transforms", so almost everything
    sits at literal coordinates -- except a few rotated labels that keep a rotation on
    their parent <g>. We nudge a single point through any transforms it carries; that's
    plain arithmetic, no matrices, no numpy.

A label belongs to the smallest shape that contains its anchor. Long names overflow their
stall, so a label sitting just outside a shape (within MAX_LABEL_GAP) still attaches to
the nearest one.

Outputs (consumed by map.html):
  interactive_map.svg  -- the SVG with matched shapes tagged (class/id/data-label)
  spaces.json          -- [{ "id": "space-110", "label": "110", "numeric": true }, ...]
"""

import json
import math
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

INPUT_SVG = sys.argv[1] if len(sys.argv) > 1 else "input.svg"
OUTPUT_SVG = sys.argv[2] if len(sys.argv) > 2 else "interactive_map.svg"
OUTPUT_JSON = sys.argv[3] if len(sys.argv) > 3 else "spaces.json"

STALL_STROKE = "stroke:rgb(16,92,146)"  # the blue outline shared by every numbered stall
ZONE_FILL = "fill:rgb(201,197,200)"     # the gray fill of attraction/zone squares (Kidzone, RPG…)
MAX_LABEL_GAP = 120                     # px a label may overflow outside its stall
FONT_FAMILY = "'Open Sans', sans-serif"  # map.html loads this webfont
FONT_SCALE = 0.9                        # Open Sans renders larger
FONT_WEIGHT = "800"                      # Open Sans ExtraBold (loaded by map.html)


def number(value):
    return float(re.sub(r"px$", "", (value or "0").strip()) or 0)


# --- transforms (applied to one point at a time, never matrix-by-matrix) ----

def apply_transform(value, x, y):
    """Move a single point through an element's `transform` (ops apply right-to-left)."""
    for name, args in reversed(re.findall(r"(\w+)\s*\(([^)]*)\)", value or "")):
        n = [float(v) for v in re.split(r"[,\s]+", args.strip()) if v]
        if name == "matrix":  # [a, b, c, d, e, f]
            a, b, c, d, e, f = n
            x, y = a * x + c * y + e, b * x + d * y + f
        elif name == "translate":
            x, y = x + n[0], y + (n[1] if len(n) > 1 else 0)
        elif name == "scale":
            x, y = x * n[0], y * (n[1] if len(n) > 1 else n[0])
        elif name == "rotate":
            angle = math.radians(n[0])
            cx, cy = (n[1], n[2]) if len(n) == 3 else (0, 0)
            px, py = x - cx, y - cy
            x = cx + px * math.cos(angle) - py * math.sin(angle)
            y = cy + px * math.sin(angle) + py * math.cos(angle)
    return x, y


def to_absolute(element, x, y):
    node = element
    while node is not None:
        if getattr(node, "get", None) and node.get("transform"):
            x, y = apply_transform(node.get("transform"), x, y)
        node = node.parent
    return x, y


# --- shapes -----------------------------------------------------------------

def path_corners(d):
    """The corner points of a rectangle-shaped <path> (M x y L x y ...)."""
    nums = [float(v) for v in re.findall(r"-?\d*\.?\d+", d or "")]
    pts = list(zip(nums[0::2], nums[1::2]))
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def is_stall(element):
    style = element.get("style") or ""
    if STALL_STROKE not in style and ZONE_FILL not in style:  # blue stall or gray zone
        return False
    if element.name == "rect":
        return True
    return element.name == "path" and len(path_corners(element.get("d", ""))) == 4


def polygon(element):
    if element.name == "rect":
        x, y = number(element.get("x")), number(element.get("y"))
        w, h = number(element.get("width")), number(element.get("height"))
        local = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    else:
        local = path_corners(element.get("d", ""))
    return [to_absolute(element, px, py) for px, py in local]


def contains(poly, x, y):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def gap(box, x, y):
    """Distance from a point to a bounding box (0 if inside)."""
    left, top, right, bottom = box
    dx = max(left - x, 0, x - right)
    dy = max(top - y, 0, y - bottom)
    return math.hypot(dx, dy)


# --- build ------------------------------------------------------------------

def slugify(key):
    return re.sub(r"[^A-Za-z0-9]+", "-", key).strip("-") or "space"


def sort_key(space):
    lead = re.match(r"\d+", space["label"])
    return (lead is None, int(lead.group()) if lead else 0, space["label"])


def flatten_text(soup):
    """Collapse per-glyph <tspan> positioning that Affinity adds for non-ASCII letters.

    Affinity pins diacritics (ę, ł, …) to absolute x positions computed for 'ArialMT';
    once the browser substitutes plain Arial those positions drift and glyphs collide.
    Replacing each <text> with its plain string lets the browser lay the word out itself.
    """
    for text in soup.find_all("text"):
        if text.find("tspan"):
            label = text.get_text()
            text.clear()
            text.append(label)


def set_font(soup, family, scale, weight):
    """Swap Affinity's exported Arial for a webfont (loaded by map.html).

    Open Sans has a larger x-height than Arial, so the same nominal size looks
    bigger than in Affinity -- shrink each font-size by `scale` to compensate --
    and force `weight` since the exported labels carry no font-weight of their own.
    """
    for text in soup.find_all("text"):
        style = text.get("style")
        if not (style and "font-family" in style):
            continue
        style = re.sub(r"font-family:[^;]*;?", f"font-family:{family};", style)
        style = re.sub(r"font-size:\s*([\d.]+)px",
                       lambda m: f"font-size:{float(m.group(1)) * scale:g}px", style)
        style = re.sub(r"font-weight:[^;]*;?", "", style)
        text["style"] = f"font-weight:{weight};{style}"


def build(input_svg, output_svg, output_json):
    soup = BeautifulSoup(Path(input_svg).read_text(encoding="utf-8"), "xml")
    flatten_text(soup)
    set_font(soup, FONT_FAMILY, FONT_SCALE, FONT_WEIGHT)

    shapes = []
    for el in soup.find_all(["rect", "path"]):
        if is_stall(el):
            poly = polygon(el)
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            box = (min(xs), min(ys), max(xs), max(ys))
            area = (box[2] - box[0]) * (box[3] - box[1])
            shapes.append({"el": el, "poly": poly, "box": box, "area": area})

    grouped = {}  # shape index -> {"shape", "texts": [...]}
    for text in soup.find_all("text"):
        if not text.get_text().strip():
            continue
        ax, ay = to_absolute(text, number(text.get("x")), number(text.get("y")))

        inside = [(s["area"], i) for i, s in enumerate(shapes)
                  if contains(s["poly"], ax, ay)]
        if inside:
            idx = min(inside)[1]
        else:  # overflowing label: snap to the nearest stall if close enough
            dist, idx = min((gap(s["box"], ax, ay), i) for i, s in enumerate(shapes))
            if dist > MAX_LABEL_GAP:
                continue
        grouped.setdefault(idx, {"shape": shapes[idx], "texts": []})["texts"].append(text)

    spaces = []
    used = set()
    for entry in grouped.values():
        el = entry["shape"]["el"]
        label = " ".join(t.get_text().strip() for t in entry["texts"])

        slug, candidate, i = slugify(label), slugify(label), 2
        while candidate in used:  # WIP source data may repeat labels
            candidate, i = f"{slug}-{i}", i + 1
        used.add(candidate)

        el["class"] = "map-space"
        el["id"] = f"space-{candidate}"
        el["data-label"] = label
        for t in entry["texts"]:
            t["pointer-events"] = "none"  # let clicks fall through to the shape
        spaces.append({"id": f"space-{candidate}", "label": label,
                       "numeric": bool(re.fullmatch(r"[\d/ ]+", label))})

    spaces.sort(key=sort_key)

    Path(output_svg).write_text(str(soup), encoding="utf-8")
    Path(output_json).write_text(json.dumps(spaces, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print(f"Matched {len(spaces)} stalls "
          f"({sum(s['numeric'] for s in spaces)} numbered, "
          f"{sum(not s['numeric'] for s in spaces)} named) -> {output_svg}, {output_json}")


if __name__ == "__main__":
    build(INPUT_SVG, OUTPUT_SVG, OUTPUT_JSON)
