#!/usr/bin/env python3
"""Draw campsite assignments onto the campground map.

Takes the campsites CSV (site id + its location on the map), the campground map
image, and the assignments CSV produced by assignments.md, and writes a copy of
the map with a labelled box next to each assigned campsite. One family per row;
families sharing a tent site share a box.

Example:
    python3 plot_assignments.py \
        --campsites River-Bend-campsites-2026.csv \
        --map River-Bend-Map-2026-8x.png \
        --assignments assignments.csv \
        --out River-Bend-assignments-2026.png
"""

from __future__ import annotations

import argparse
import collections
import csv
import io
import math
import os
import re
import sys
import textwrap
from collections import OrderedDict

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Candidate columns, tried in order, matched case/punctuation insensitively.
# Percent/normalized coordinates come first: they survive a rescaled map image,
# absolute pixels do not.
SITE_COLUMNS = ("site", "site_id", "campsite", "name")
X_COLUMNS = ("x_percent", "x_pct", "x_norm", "x_normalized", "x_frac", "x_px", "x_pixels", "x")
Y_COLUMNS = ("y_percent", "y_pct", "y_norm", "y_normalized", "y_frac", "y_px", "y_pixels", "y")
ASSIGNMENT_COLUMNS = ("assignment", "assignments", "site", "campsite")
CHILDREN_COLUMNS = ("children", "kids")

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)
BOLD_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)

# One colour per grade, so a family's children can be picked out by grade at a
# glance. Ordered TK, K, 1..12; anything unrecognised falls through to the grey.
# Chosen for separation at small sizes and all dark enough to read on white -
# no yellows or pale tints.
GRADE_ORDER = ["TK", "K"] + [str(g) for g in range(1, 13)]
GRADE_COLORS = [
    (0, 90, 156),     # TK  steel blue
    (176, 36, 36),    # K   red
    (26, 122, 62),    # 1   green
    (124, 58, 155),   # 2   purple
    (183, 87, 12),    # 3   orange
    (14, 118, 130),   # 4   teal
    (140, 74, 56),    # 5   brown
    (57, 59, 121),    # 6   navy
    (168, 44, 116),   # 7   magenta
    (85, 107, 47),    # 8   olive
    (132, 60, 57),    # 9   maroon
    (33, 97, 140),    # 10  slate blue
    (99, 62, 128),    # 11  plum
    (110, 84, 32),    # 12  bronze
]
UNKNOWN_GRADE_COLOR = (105, 105, 105)

# Defaults expressed against a 1000px-tall map; scaled by --ui-scale.
SCALED_DEFAULTS = {
    "font_size": 6.0,
    "offset": 22.0,       # gap to the campsite, --layout map only
    "padding": 3.5,
    "line_gap": 1.5,
    "family_gap": 3.5,
    "border_width": 1.0,
    "leader_width": 1.0,
    "dot_radius": 2.5,
    "box_gap": 6.0,       # between boxes stacked in a gutter
    "gutter_gap": 16.0,   # between the map edge and its gutter
    "halo_width": 3.0,    # white casing under a leader, so it reads over map art
    "shadow_offset": 2.0,
    "shadow_blur": 3.0,
    "site_label_size": 20.0,  # the map's own campsite labels, kept clear
}


# --------------------------------------------------------------------------
# CSV helpers
# --------------------------------------------------------------------------

def read_csv(path):
    """Read a CSV into a list of dicts, tolerating a UTF-8 BOM."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def norm_key(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_column(fieldnames, candidates, explicit=None, what="column"):
    """Resolve a column name from `candidates`, or verify an explicit choice."""
    lookup = {norm_key(f): f for f in fieldnames}
    if explicit:
        if explicit in fieldnames:
            return explicit
        if norm_key(explicit) in lookup:
            return lookup[norm_key(explicit)]
        raise SystemExit("%s %r not found; available columns: %s"
                         % (what, explicit, ", ".join(fieldnames)))
    for cand in candidates:
        if norm_key(cand) in lookup:
            return lookup[norm_key(cand)]
    return None


def site_key(value):
    """Canonical site id, so `t-4`, `T-4 ` and `T 4` all match."""
    return re.sub(r"[\s_]+", "", (value or "").strip().upper())


def to_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def coord_kind_of(column, values, mode):
    """Decide whether coordinates are fractions, percentages or pixels."""
    if mode != "auto":
        return mode
    key = norm_key(column)
    if "percent" in key or key.endswith("pct"):
        return "pct"
    if "norm" in key or "frac" in key:
        return "norm"
    if "px" in key or "pixel" in key:
        return "px"
    peak = max(values) if values else 0.0
    if peak <= 1.5:
        return "norm"
    if peak <= 100.0:
        return "pct"
    return "px"


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

def load_campsites(path, image_size, mode, site_col=None, x_col=None, y_col=None):
    """Return ({site_key: (label, x_px, y_px)}, no_coord_keys, description)."""
    rows = read_csv(path)
    if not rows:
        raise SystemExit("campsites CSV %r is empty" % path)

    fields = list(rows[0].keys())
    site_col = find_column(fields, SITE_COLUMNS, site_col, "site column")
    x_col = find_column(fields, X_COLUMNS, x_col, "x column")
    y_col = find_column(fields, Y_COLUMNS, y_col, "y column")
    if not site_col:
        raise SystemExit("no site column in %s (looked for %s)" % (path, ", ".join(SITE_COLUMNS)))
    if not x_col or not y_col:
        raise SystemExit("no x/y columns in %s (looked for %s / %s)"
                         % (path, ", ".join(X_COLUMNS), ", ".join(Y_COLUMNS)))

    usable, no_coords = [], OrderedDict()
    for row in rows:
        label = (row.get(site_col) or "").strip()
        if not label:
            continue
        x, y = to_float(row.get(x_col)), to_float(row.get(y_col))
        if x is None or y is None:
            no_coords[site_key(label)] = label
            continue
        usable.append((label, x, y))
    if not usable:
        raise SystemExit("no rows in %s have usable %s/%s values" % (path, x_col, y_col))

    kind = coord_kind_of(x_col, [max(abs(x), abs(y)) for _, x, y in usable], mode)
    width, height = image_size
    if kind == "norm":
        sx, sy = float(width), float(height)
    elif kind == "pct":
        sx, sy = width / 100.0, height / 100.0
    else:
        sx = sy = 1.0

    section_col = find_column(fields, ("section", "site_type", "type"))
    sections = OrderedDict()
    for row in rows:
        label = (row.get(site_col) or "").strip()
        if label and section_col:
            sections[site_key(label)] = (row.get(section_col) or "").strip()

    sites = OrderedDict()
    for label, x, y in usable:
        sites[site_key(label)] = (label, x * sx, y * sy)
    return sites, no_coords, "%s/%s (%s)" % (x_col, y_col, kind), sections


def loose_key(text):
    """Letters and digits only, upper case, with a leading `THE` dropped."""
    key = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    return key[3:] if key.startswith("THE") and len(key) > 3 else key


def match_photo(stem, by_site, by_section):
    """The campsite a photo filename refers to, or None.

    Site ids come first, so `H1.jpg` and `H-1.jpg` both land on H-1. Failing
    that, the one-off cabins are named on disk after what the map calls them
    rather than after their site id -- `Magic Bus.jpeg`, `The Outpost.jpg`,
    `CC-11 Counselor's Cabin.jpg` -- so fall back to matching the section name,
    which only ever applies to sections holding a single campsite.
    """
    key = loose_key(stem)
    if key in by_site:
        return by_site[key]
    if key in by_section:
        return by_section[key]
    hits = {site for name, site in by_section.items()
            if name and (name in key or key in name)}
    return hits.pop() if len(hits) == 1 else None


def load_photos(directory, sites, sections):
    """{site_key: path} for every image in `directory` named after a campsite."""
    if not os.path.isdir(directory):
        raise SystemExit("photo folder %r is not a directory" % directory)

    by_site = {loose_key(key): key for key in sites}
    # Only single-campsite sections can be identified by their name alone.
    counts = collections.Counter(sections.values())
    by_section = {loose_key(name): key for key, name in sections.items()
                  if counts[name] == 1 and key in sites}

    photos, unmatched = {}, []
    for name in sorted(os.listdir(directory)):
        stem, ext = os.path.splitext(name)
        if ext.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        site = match_photo(stem, by_site, by_section)
        if site:
            photos[site] = os.path.join(directory, name)
        else:
            unmatched.append(name)
    if unmatched:
        print("note: %d photo(s) match no campsite in the sheet: %s"
              % (len(unmatched), ", ".join(unmatched)), file=sys.stderr)
    return photos


def parent_columns(fieldnames):
    """`Parent ...` columns holding names, in sheet order; email/phone excluded."""
    named, fallback = [], []
    for field in fieldnames or []:
        if not re.match(r"^\s*parent\b", field or "", re.IGNORECASE):
            continue
        key = norm_key(field)
        if "email" in key or "phone" in key or "mail" in key:
            continue
        (named if key.endswith("name") else fallback).append(field)
    return named or fallback


def grade_color(grade):
    """The colour for one grade, stable from run to run."""
    key = (grade or "").strip().upper()
    if key in GRADE_ORDER:
        return GRADE_COLORS[GRADE_ORDER.index(key) % len(GRADE_COLORS)]
    return UNKNOWN_GRADE_COLOR


def parse_children(raw):
    """`Jane Doe:1|Mike Chen:4` -> [('Jane Doe (1)', '1'), ('Mike Chen (4)', '4')]."""
    kids = []
    for chunk in (raw or "").split("|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, _, grade = chunk.partition(":")
        name, grade = name.strip(), grade.strip()
        if not name:
            continue
        kids.append(("%s (%s)" % (name, grade) if grade else name, grade))
    return kids


def load_assignments(path, assignment_col=None, children_col=None):
    """Return ({site_key: [(raw_site, parents, children, row)]}, metadata)."""
    rows = read_csv(path)
    if not rows:
        raise SystemExit("assignments CSV %r is empty" % path)

    fields = list(rows[0].keys())
    assignment_col = find_column(fields, ASSIGNMENT_COLUMNS, assignment_col, "assignment column")
    children_col = find_column(fields, CHILDREN_COLUMNS, children_col, "children column")
    if not assignment_col:
        raise SystemExit("no assignment column in %s (looked for %s)"
                         % (path, ", ".join(ASSIGNMENT_COLUMNS)))
    parents = parent_columns(fields)
    if not parents:
        print("warning: no 'Parent ...' name columns in %s" % path, file=sys.stderr)

    by_site, unassigned = OrderedDict(), 0
    for row in rows:
        assignment = (row.get(assignment_col) or "").strip()
        if not assignment:
            unassigned += 1
            continue
        names = [n for n in ((row.get(c) or "").strip() for c in parents) if n]
        family = " & ".join(names) or "(unnamed family)"
        kids = parse_children(row.get(children_col)) if children_col else []
        by_site.setdefault(site_key(assignment), []).append((assignment, family, kids, row))

    meta = {"assignment_col": assignment_col, "children_col": children_col,
            "parent_cols": parents, "unassigned": unassigned, "rows": rows}
    return by_site, meta


# --------------------------------------------------------------------------
# Text blocks
# --------------------------------------------------------------------------

def load_font(path, size, candidates):
    for candidate in ([path] if path else []) + list(candidates):
        if candidate and os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, int(round(size)))
            except OSError:
                continue
    print("warning: no TrueType font found; using the bitmap default "
          "(--font-size has no effect)", file=sys.stderr)
    return ImageFont.load_default()


def wrap(text, width, indent=""):
    if width <= 0 or not text:
        return [text] if text else []
    return textwrap.wrap(text, width=width, initial_indent=indent,
                         subsequent_indent=indent + "  ") or []


def child_lines(kids, width):
    """Pack children into lines of coloured runs, one colour per grade.

    Children are wrapped whole rather than by word, so a name and its grade
    never split across lines and never take a second colour.
    """
    lines, current, used = [], [], 0
    for index, (text, grade) in enumerate(kids):
        piece = text if index == len(kids) - 1 else text + ", "
        if current and width > 0 and used + len(piece) > width:
            lines.append(current)
            current, used = [], 2  # continuation lines are indented
        if not current:
            current = [("  " if lines else "", None)]
            used += 2
        current.append((piece, grade_color(grade)))
        used += len(piece)
    if current:
        lines.append(current)
    return lines


def build_block(site_label, families, opts):
    """Lines of one box as (runs, kind, starts_new_family), where each run is
    (text, colour) and a colour of None means the line's default."""
    lines = []
    if opts.site_header:
        header = site_label
        if len(families) > 1:
            header = "%s  (%d families)" % (site_label, len(families))
        lines.append(([(header, None)], "header", False))
    for index, (_, parents, kids) in enumerate(families):
        first = True
        for line in wrap(parents, opts.wrap) or [parents]:
            lines.append(([(line, None)], "family", index > 0 and first))
            first = False
        if kids and opts.show_children:
            for runs in child_lines(kids, opts.wrap):
                lines.append((runs, "children", False))
    return lines


def measure(draw, lines, fonts, opts):
    """(width, height, per-line heights, per-line leading gaps) of a block."""
    widths, heights, gaps = [], [], []
    for runs, kind, starts_family in lines:
        font = fonts[kind]
        width = sum(draw.textlength(text, font=font) for text, _ in runs)
        height = draw.textbbox((0, 0), "Ag", font=font)[3]
        widths.append(width)
        heights.append(height + opts.line_gap)
        gaps.append(opts.family_gap if starts_family else 0.0)
    box_w = max(widths) + 2 * opts.padding
    box_h = sum(heights) + sum(gaps) + 2 * opts.padding
    return box_w, box_h, heights, gaps


# --------------------------------------------------------------------------
# Placement
# --------------------------------------------------------------------------

def corner_for(side, px, py, box_w, box_h, offset):
    if side == "right":
        return px + offset, py - box_h / 2.0
    if side == "left":
        return px - offset - box_w, py - box_h / 2.0
    if side == "below":
        return px - box_w / 2.0, py + offset
    return px - box_w / 2.0, py - offset - box_h  # above


def overlap_area(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    dx = min(ax + aw, bx + bw) - max(ax, bx)
    dy = min(ay + ah, by + bh) - max(ay, by)
    return dx * dy if dx > 0 and dy > 0 else 0.0


def label_keepouts(sites, opts):
    """A rectangle over each campsite's own label on the map, to be left clear.

    The map's label geometry is not in the campsites sheet, so approximate it
    from the site id's length around the recorded point.
    """
    size = opts.site_label_size
    keepouts = []
    for label, x, y in sites:
        w = max(size, 0.62 * size * len(label))
        keepouts.append((x - w / 2.0, y - size / 2.0, w, size))
    return keepouts


def choose_position(px, py, box_w, box_h, placed, keepouts, bounds, opts):
    """Greedy: the position nearest the campsite that clears everything placed."""
    x_min, y_min, x_max, y_max = bounds
    sides = ["right", "left", "below", "above"] if opts.side == "auto" else [opts.side]
    if not opts.declutter:
        x, y = corner_for(sides[0], px, py, box_w, box_h, opts.offset)
        return (max(x_min, min(x, x_max - box_w)), max(y_min, min(y, y_max - box_h)),
                box_w, box_h)

    # Search outward: sideways along the box edge first, then further from the site.
    step = box_h * 0.55 + opts.family_gap
    shifts = [0.0]
    for i in range(1, opts.declutter_steps + 1):
        shifts.extend((i * step, -i * step))
    pushes = [1.0, 2.5, 4.5, 7.0][:max(1, opts.declutter_pushes)]

    best = None
    for push in pushes:
        for side in sides:
            for shift in shifts:
                x, y = corner_for(side, px, py, box_w, box_h, opts.offset * push)
                if side in ("right", "left"):
                    y += shift
                else:
                    x += shift
                x = max(x_min, min(x, x_max - box_w))
                y = max(y_min, min(y, y_max - box_h))
                rect = (x, y, box_w, box_h)

                clash = sum(overlap_area(rect, other) for other in placed)
                covered = sum(overlap_area(rect, keep) for keep in keepouts)
                leader = math.hypot(x + box_w / 2.0 - px, y + box_h / 2.0 - py)
                score = (clash, covered, leader)
                if best is None or score < best[0]:
                    best = (score, rect)
                if clash == 0 and covered == 0:
                    return rect
    return best[1]


def anchor_point(px, py, rect):
    """Point on the box edge nearest the campsite, for the leader line."""
    x, y, w, h = rect
    return min(max(px, x), x + w), min(max(py, y), y + h)


def leader_points(px, py, rect, opts):
    """The polyline from a box to its campsite.

    An elbow leaves the box horizontally, turns once, and arrives at the
    campsite horizontally, so nothing on the page runs at a stray angle.
    """
    x, y, w, h = rect
    if opts.line_style == "straight":
        return [anchor_point(px, py, rect), (px, py)]

    start_y = min(max(py, y + opts.padding), y + h - opts.padding)
    if px >= x + w:
        start_x = x + w
    elif px <= x:
        start_x = x
    else:
        # Campsite sits under the box; a horizontal elbow has nowhere to go.
        return [anchor_point(px, py, rect), (px, py)]

    turn = start_x + (px - start_x) * min(max(opts.elbow_at, 0.0), 1.0)
    return [(start_x, start_y), (turn, start_y), (turn, py), (px, py)]


# --------------------------------------------------------------------------
# Layouts
# --------------------------------------------------------------------------

def stack_column(items, top, bottom, gap):
    """Stack boxes down one gutter, each as near its campsite's height as it
    can get without colliding with its neighbours."""
    items = sorted(items, key=lambda b: b["desired"])
    cursor = top
    for box in items:
        box["y"] = max(box["desired"], cursor)
        cursor = box["y"] + box["h"] + gap
    # Ran past the bottom: walk back up, then down again to undo any negatives.
    if items and cursor - gap > bottom:
        cursor = bottom
        for box in reversed(items):
            box["y"] = min(box["y"], cursor - box["h"])
            cursor = box["y"] - gap
        cursor = top
        for box in items:
            box["y"] = max(box["y"], cursor)
            cursor = box["y"] + box["h"] + gap
    return items


def layout_gutter(base, blocks, opts):
    """Park every box in a column down the left or right margin, and grow the
    canvas until the columns fit. Nothing is drawn over the map itself."""
    map_w, map_h = base.size
    margin, gap, gutter = max(0.0, opts.margin), opts.box_gap, opts.gutter_gap

    # Which gutter a box goes in. Splitting on the map's midline keeps every
    # leader on its own side; balancing on height instead keeps the canvas
    # shorter, at the cost of leaders that cross the map.
    ordered = sorted(blocks, key=lambda b: b["px"])
    if opts.gutter_split == "balanced":
        half = sum(b["h"] + gap for b in ordered) / 2.0
        left, right, running = [], [], 0.0
        for box in ordered:
            if running + (box["h"] + gap) / 2.0 <= half:
                left.append(box)
                running += box["h"] + gap
            else:
                right.append(box)
    else:
        middle = map_w / 2.0
        left = [b for b in ordered if b["px"] < middle]
        right = [b for b in ordered if b["px"] >= middle]

    def column_height(items):
        return sum(b["h"] for b in items) + gap * max(0, len(items) - 1)

    canvas_h = max(map_h, column_height(left), column_height(right)) + 2 * margin
    left_w = max([b["w"] for b in left], default=0.0) + (gutter if left else 0.0)
    right_w = max([b["w"] for b in right], default=0.0) + (gutter if right else 0.0)
    canvas_w = margin + left_w + map_w + right_w + margin
    map_x = margin + left_w
    map_y = margin + (canvas_h - 2 * margin - map_h) / 2.0

    canvas = Image.new("RGBA", (int(round(canvas_w)), int(round(canvas_h))),
                       opts.margin_color + (255,))
    canvas.paste(base, (int(round(map_x)), int(round(map_y))))

    boxes = []
    span = canvas_h - 2 * margin
    for items, side in ((left, "left"), (right, "right")):
        for box in items:
            box["px"] += map_x
            box["py"] += map_y
            # Position by where the campsite sits down the map, stretched over the
            # whole column. Keeps the leaders in order and stops them fanning.
            frac = (box["py"] - map_y) / map_h if map_h else 0.5
            box["desired"] = margin + frac * max(0.0, span - box["h"])
        for box in stack_column(items, margin, canvas_h - margin, gap):
            x = (map_x - gutter - box["w"]) if side == "left" else map_x + map_w + gutter
            box["rect"] = (x, box["y"], box["w"], box["h"])
            boxes.append(box)
    return canvas, boxes, "%d left / %d right" % (len(left), len(right))


def layout_on_map(base, blocks, sites, opts):
    """Sit each box beside its campsite, nudged around to avoid collisions."""
    margin = max(0.0, opts.margin)
    if margin:
        canvas = Image.new("RGBA", (int(round(base.width + 2 * margin)),
                                    int(round(base.height + 2 * margin))),
                           opts.margin_color + (255,))
        canvas.paste(base, (int(round(margin)), int(round(margin))))
        base = canvas
        for box in blocks:
            box["px"] += margin
            box["py"] += margin
        sites = [(label, x + margin, y + margin) for label, x, y in sites]

    edge = max(2.0, opts.border_width)
    bounds = (edge, edge, base.width - edge, base.height - edge)
    keepouts = label_keepouts(sites, opts)
    placed, boxes = [], []
    # Biggest boxes claim space first; they are the hardest to fit later.
    for box in sorted(blocks, key=lambda b: -(b["w"] * b["h"])):
        rect = choose_position(box["px"], box["py"], box["w"], box["h"],
                               placed, keepouts, bounds, opts)
        placed.append(rect)
        box["rect"] = rect
        boxes.append(box)
    return base, boxes, "beside each campsite"


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------

def draw_map(base, boxes, fonts, opts):
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    colors = {"header": opts.header_color, "family": opts.text_color,
              "children": opts.children_color}
    leader_w = max(1, int(round(opts.leader_width)))
    routes = [leader_points(b["px"], b["py"], b["rect"], opts) for b in boxes]

    if opts.shadow:
        shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
        pen = ImageDraw.Draw(shadow)
        off = opts.shadow_offset
        for x, y, w, h in (b["rect"] for b in boxes):
            pen.rectangle((x + off, y + off, x + w + off, y + h + off),
                          fill=(0, 0, 0, 90))
        overlay = Image.alpha_composite(
            overlay, shadow.filter(ImageFilter.GaussianBlur(opts.shadow_blur)))
        draw = ImageDraw.Draw(overlay)

    # Every leader first, so a line never appears to stop at an unrelated box.
    if opts.shadow and opts.halo_width > 0:
        for route in routes:  # white casing, so a leader stays legible over map art
            draw.line([c for point in route for c in point],
                      fill=opts.halo_color + (255,),
                      width=leader_w + max(1, int(round(opts.halo_width))),
                      joint="curve")
    for route in routes:
        draw.line([c for point in route for c in point],
                  fill=opts.leader_color + (255,), width=leader_w, joint="curve")

    for box in boxes:
        lines, heights, gaps = box["lines"], box["heights"], box["gaps"]
        x, y, w, h = box["rect"]
        draw.rectangle((x, y, x + w, y + h), fill=opts.box_fill + (opts.box_alpha,),
                       outline=opts.border_color + (255,),
                       width=max(1, int(round(opts.border_width))))
        cursor = y + opts.padding
        for (runs, kind, _), line_h, gap in zip(lines, heights, gaps):
            if gap:
                mid = cursor + gap / 2.0
                draw.line((x + opts.padding, mid, x + w - opts.padding, mid),
                          fill=opts.separator_color + (255,),
                          width=max(1, int(round(opts.border_width / 2))))
                cursor += gap
            pen_x = x + opts.padding
            for text, color in runs:
                draw.text((pen_x, cursor), text, font=fonts[kind],
                          fill=(color or colors[kind]) + (255,))
                pen_x += draw.textlength(text, font=fonts[kind])
            cursor += line_h

    r = opts.dot_radius
    if r > 0:
        for box in boxes:
            px, py = box["px"], box["py"]
            draw.ellipse((px - r, py - r, px + r, py + r), fill=opts.dot_color + (255,),
                         outline=(255, 255, 255, 255), width=max(1, int(round(r / 3))))

    return Image.alpha_composite(base, overlay)


# --------------------------------------------------------------------------
# PDF output
#
# Written by hand rather than via a PDF library, to keep Pillow the only
# dependency. The map goes in as a JPEG; the boxes are vectors and the labels
# are real Helvetica text, so the result is searchable and selectable.
# --------------------------------------------------------------------------

PDF_FONT_RESOURCE = {"family": b"/F1", "children": b"/F1", "header": b"/F2"}


def pdf_text(text):
    """Escape a string for a PDF literal, in WinAnsi (cp1252) bytes."""
    data = text.encode("cp1252", "replace")
    for ch in (b"\\", b"(", b")"):
        data = data.replace(ch, b"\\" + ch)
    return data


def n(value):
    return b"%.3f" % value


class PdfWriter:
    """The smallest indirect-object/xref writer that produces a valid PDF."""

    def __init__(self):
        self.objects = [None]  # object numbers are 1-based

    def add(self, body):
        self.objects.append(body)
        return len(self.objects) - 1

    def reserve(self):
        """Claim an object number now and fill it in later, so an object can
        refer to one written after it."""
        return self.add(None)

    def put(self, number, body):
        self.objects[number] = body
        return number

    def put_stream(self, number, entries, data):
        return self.put(number, b"<< " + entries + b" /Length %d >>\nstream\n"
                        % len(data) + data + b"\nendstream")

    def add_stream(self, entries, data):
        return self.put_stream(self.reserve(), entries, data)

    def save(self, path):
        missing = [i for i, body in enumerate(self.objects) if i and body is None]
        assert not missing, "reserved but never filled: %s" % missing
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for number, body in enumerate(self.objects[1:], start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % len(self.objects)
        for offset in offsets:
            out += b"%010d 00000 n \n" % offset
        out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                % (len(self.objects), xref))
        with open(path, "wb") as fh:
            fh.write(bytes(out))


def pdf_circle(cx, cy, r):
    """A filled circle, as the usual four Bezier arcs."""
    k = 0.55228 * r
    return b" ".join([
        n(cx + r), n(cy), b"m",
        n(cx + r), n(cy + k), n(cx + k), n(cy + r), n(cx), n(cy + r), b"c",
        n(cx - k), n(cy + r), n(cx - r), n(cy + k), n(cx - r), n(cy), b"c",
        n(cx - r), n(cy - k), n(cx - k), n(cy - r), n(cx), n(cy - r), b"c",
        n(cx + k), n(cy - r), n(cx + r), n(cy - k), n(cx + r), n(cy), b"c", b"f\n"])


def rgb(color, stroke=False):
    r, g, b = (c / 255.0 for c in color)
    return b"%s %s %s %s\n" % (n(r), n(g), n(b), b"RG" if stroke else b"rg")


def jpeg_bytes(image, quality, max_edge=0):
    """Baseline RGB JPEG, which is what a PDF's DCTDecode filter can read.

    Anything past `max_edge` is resolution nobody can see at the size a photo
    prints, so it comes off before it costs file size.
    """
    if max_edge and max(image.size) > max_edge:
        scale = max_edge / float(max(image.size))
        image = image.resize((max(1, round(image.width * scale)),
                              max(1, round(image.height * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True,
                              progressive=False)
    return buf.getvalue()


def photo_page(pdf, objects, box, photo_path, map_page, fonts, ruler, opts):
    """One page: the campsite's photo, who is on it, and a link back to the map.

    Laid out at 1 unit = 1 point, so the caption sizes are literal point sizes
    however large the map image was.
    """
    page_num, content_num, image_num, back_num = objects
    margin, gap = 36.0, 12.0
    page_w = opts.photo_page_width * 72.0
    title_size = opts.photo_caption_size * 1.45

    image = Image.open(photo_path)
    fit = min((page_w - 2 * margin) / image.width,
              opts.photo_max_height * 72.0 / image.height)
    shot_w, shot_h = image.width * fit, image.height * fit

    caption = [line for line in box["lines"] if line[1] != "header"]
    leading = {kind: ruler.textbbox((0, 0), "Ag", font=font)[3] * 1.28
               for kind, font in fonts.items()}
    caption_h = sum(leading[kind] for _, kind, _ in caption)
    back_h = opts.photo_caption_size * 1.4
    page_h = (margin + title_size + gap + shot_h + gap + caption_h
              + gap + back_h + margin)

    families = sum(1 for _, kind, starts in box["lines"] if kind == "family" and starts) + 1
    title = box["label"] if families < 2 else "%s  (%d families)" % (box["label"], families)

    body = bytearray()
    cursor = page_h - margin - title_size
    body += b"BT /F2 %s Tf %s%s %s Td (%s) Tj ET\n" % (
        n(title_size), rgb(opts.header_color), n(margin), n(cursor),
        pdf_text(title))

    cursor -= gap + shot_h
    body += b"q %s 0 0 %s %s %s cm /Im0 Do Q\n" % (
        n(shot_w), n(shot_h), n((page_w - shot_w) / 2.0), n(cursor))

    cursor -= gap
    colors = {"family": opts.text_color, "children": opts.children_color}
    for runs, kind, _ in caption:
        size = opts.photo_caption_size * (0.92 if kind == "children" else 1.0)
        cursor -= leading[kind]
        pen_x = margin
        for text, color in runs:
            body += b"BT %s %s Tf %s%s %s Td (%s) Tj ET\n" % (
                PDF_FONT_RESOURCE[kind], n(size), rgb(color or colors[kind]),
                n(pen_x), n(cursor), pdf_text(text))
            pen_x += ruler.textlength(text, font=fonts[kind])

    cursor -= gap + back_h
    back_text = "< Back to the map"
    back_w = ruler.textlength(back_text, font=fonts["family"])
    body += b"BT /F1 %s Tf %s%s %s Td (%s) Tj ET\n" % (
        n(opts.photo_caption_size), rgb(opts.leader_color), n(margin), n(cursor),
        pdf_text(back_text))

    pdf.put(page_num,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %s %s] "
            b"/Resources << /XObject << /Im0 %d 0 R >> "
            b"/Font << /F1 6 0 R /F2 7 0 R >> >> "
            b"/Contents %d 0 R /Annots [%d 0 R] >>"
            % (n(page_w), n(page_h), image_num, content_num, back_num))
    pdf.put_stream(content_num, b"", bytes(body))
    data = jpeg_bytes(image, opts.pdf_quality, opts.photo_max_pixels)
    pdf.put_stream(image_num,
                   b"/Type /XObject /Subtype /Image /Width %d /Height %d "
                   b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode"
                   % (image.width, image.height), data)
    pdf.put(back_num, link_annot((margin, cursor - 3, margin + back_w,
                                  cursor + back_h), map_page))
    return page_num


def link_annot(rect, target_page):
    x0, y0, x1, y1 = rect
    return (b"<< /Type /Annot /Subtype /Link /Border [0 0 0] "
            b"/Rect [%s %s %s %s] /A << /S /GoTo /D [%d 0 R /Fit] >> >>"
            % (n(x0), n(y0), n(x1), n(y1), target_page))


def render_pdf(base, boxes, fonts, opts, path, photos=None):
    """Write the map plus vector boxes and live text to a PDF.

    Campsites with a photo get a page of their own, linked from their box
    on the map."""
    photos = photos or {}
    width, height = base.size
    scale = (opts.pdf_page_width * 72.0 / width if opts.pdf_page_width
             else 1.0 / opts.ui_scale)
    page_w, page_h = width * scale, height * scale

    def sx(x):
        return x * scale

    def sy(y):
        return (height - y) * scale  # PDF's origin is bottom-left

    ascents = {kind: font.getmetrics()[0] for kind, font in fonts.items()}
    ruler = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    colors = {"header": opts.header_color, "family": opts.text_color,
              "children": opts.children_color}

    body = bytearray()
    body += b"q %s 0 0 %s 0 0 cm /Im0 Do Q\n" % (n(page_w), n(page_h))
    body += b"1 J 1 j\n"  # round caps and joins, so elbows do not look chipped

    def polyline(route):
        out = b"%s %s m " % (n(sx(route[0][0])), n(sy(route[0][1])))
        for x, y in route[1:]:
            out += b"%s %s l " % (n(sx(x)), n(sy(y)))
        return out + b"S\n"

    # A PDF has no blur, so the drop shadow is a few stacked translucent rects.
    if opts.shadow:
        body += b"q /GS2 gs " + rgb((0, 0, 0))
        for x, y, w, h in (b["rect"] for b in boxes):
            for step in (0.0, 0.5, 1.0):
                grow = opts.shadow_blur * step
                ox, oy = opts.shadow_offset, opts.shadow_offset
                body += b"%s %s %s %s re f\n" % (
                    n(sx(x + ox - grow)), n(sy(y + h + oy + grow)),
                    n((w + 2 * grow) * scale), n((h + 2 * grow) * scale))
        body += b"Q\n"

    routes = [leader_points(b["px"], b["py"], b["rect"], opts) for b in boxes]
    if opts.shadow and opts.halo_width > 0:
        body += rgb(opts.halo_color, stroke=True)
        body += b"%s w\n" % n(max(0.1, (opts.leader_width + opts.halo_width) * scale))
        for route in routes:
            body += polyline(route)
    body += rgb(opts.leader_color, stroke=True)
    body += b"%s w\n" % n(max(0.1, opts.leader_width * scale))
    for route in routes:
        body += polyline(route)

    for box in boxes:
        lines, heights, gaps = box["lines"], box["heights"], box["gaps"]
        x, y, w, h = box["rect"]
        body += b"q /GS1 gs\n"
        body += rgb(opts.box_fill) + rgb(opts.border_color, stroke=True)
        body += b"%s w\n" % n(max(0.1, opts.border_width * scale))
        body += b"%s %s %s %s re B\nQ\n" % (n(sx(x)), n(sy(y + h)),
                                             n(w * scale), n(h * scale))
        cursor = y + opts.padding
        for (runs, kind, _), line_h, gap in zip(lines, heights, gaps):
            if gap:
                mid = cursor + gap / 2.0
                body += rgb(opts.separator_color, stroke=True)
                body += b"%s w\n" % n(max(0.1, opts.border_width * scale / 2))
                body += b"%s %s m %s %s l S\n" % (n(sx(x + opts.padding)), n(sy(mid)),
                                                  n(sx(x + w - opts.padding)), n(sy(mid)))
                cursor += gap
            size = opts.font_size * (0.92 if kind == "children" else 1.0) * scale
            pen_x = x + opts.padding
            for text, color in runs:
                body += b"BT %s %s Tf %s%s %s Td (%s) Tj ET\n" % (
                    PDF_FONT_RESOURCE[kind], n(size), rgb(color or colors[kind]),
                    n(sx(pen_x)), n(sy(cursor + ascents[kind])), pdf_text(text))
                pen_x += ruler.textlength(text, font=fonts[kind])
            cursor += line_h

    if opts.dot_radius > 0:
        body += rgb(opts.dot_color)
        for box in boxes:
            body += pdf_circle(sx(box["px"]), sy(box["py"]), opts.dot_radius * scale)

    jpeg = io.BytesIO()
    base.convert("RGB").save(jpeg, "JPEG", quality=opts.pdf_quality, optimize=True)
    jpeg = jpeg.getvalue()

    pdf = PdfWriter()
    catalog = pdf.add(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages = pdf.reserve()
    page = pdf.reserve()
    content = pdf.reserve()
    map_image = pdf.reserve()
    for face in (b"/Helvetica", b"/Helvetica-Bold"):
        pdf.add(b"<< /Type /Font /Subtype /Type1 /BaseFont %s "
                b"/Encoding /WinAnsiEncoding >>" % face)
    pdf.add(b"<< /Type /ExtGState /ca %s /CA 1 >>" % n(opts.box_alpha / 255.0))
    pdf.add(b"<< /Type /ExtGState /ca 0.10 /CA 0.10 >>")  # drop shadow
    assert (catalog, pages, page, content, map_image) == (1, 2, 3, 4, 5), \
        "object numbers 1-9 are referenced by hand"

    # A page per campsite photo, and a link from that campsite's box to it.
    shots = [box for box in boxes if box.get("key") in photos]
    caption_fonts = {
        "family": load_font(opts.font, opts.photo_caption_size, FONT_CANDIDATES),
        "children": load_font(opts.font, opts.photo_caption_size * 0.92,
                              FONT_CANDIDATES),
        "header": load_font(opts.bold_font or opts.font, opts.photo_caption_size,
                            BOLD_FONT_CANDIDATES + FONT_CANDIDATES),
    }
    links = []
    for box in shots:
        objects = (pdf.reserve(), pdf.reserve(), pdf.reserve(), pdf.reserve())
        box["photo_page"] = photo_page(pdf, objects, box, photos[box["key"]], page,
                                       caption_fonts, ruler, opts)
        x, y, w, h = box["rect"]
        links.append(pdf.add(link_annot(
            (sx(x), sy(y + h), sx(x + w), sy(y)), box["photo_page"])))

    annots = (b" /Annots [%s]" % b" ".join(b"%d 0 R" % i for i in links)) if links else b""
    pdf.put(page, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %s %s] "
                  b"/Resources << /XObject << /Im0 5 0 R >> "
                  b"/Font << /F1 6 0 R /F2 7 0 R >> "
                  b"/ExtGState << /GS1 8 0 R /GS2 9 0 R >> >> /Contents 4 0 R%s >>"
                  % (n(page_w), n(page_h), annots))
    pdf.put_stream(content, b"", bytes(body))
    pdf.put_stream(map_image,
                   b"/Type /XObject /Subtype /Image /Width %d /Height %d "
                   b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode"
                   % (width, height), jpeg)

    order = [page] + [box["photo_page"] for box in shots]
    pdf.put(pages, b"<< /Type /Pages /Kids [%s] /Count %d >>"
            % (b" ".join(b"%d 0 R" % i for i in order), len(order)))
    pdf.save(path)
    return page_w / 72.0, page_h / 72.0, len(order)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_color(value):
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        raise argparse.ArgumentTypeError("expected a hex colour like #1a1a1a, got %r" % value)
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def build_parser():
    p = argparse.ArgumentParser(
        description="Draw campsite assignments onto the campground map.")
    p.add_argument("--campsites", required=True, help="campsites CSV (site id + map location)")
    p.add_argument("--map", required=True, dest="map_path", help="campground map image")
    p.add_argument("--assignments", required=True, help="assignments CSV")
    p.add_argument("--out", required=True,
                   help="output path; a .pdf extension writes a searchable PDF "
                        "(real text, vector boxes), anything else writes an image")

    g = p.add_argument_group("input columns")
    g.add_argument("--coords", choices=("auto", "pct", "norm", "px"), default="auto",
                   help="are campsite x/y percentages (0-100), fractions (0-1) or pixels")
    g.add_argument("--site-col", help="site id column in the campsites CSV")
    g.add_argument("--x-col", help="x column in the campsites CSV")
    g.add_argument("--y-col", help="y column in the campsites CSV")
    g.add_argument("--assignment-col", help="assignment column in the assignments CSV")
    g.add_argument("--children-col", help="children column in the assignments CSV")

    g = p.add_argument_group("layout")
    g.add_argument("--ui-scale", type=float,
                   help="scale every size below (default: map height / 1000)")
    g.add_argument("--font", help="path to a .ttf/.ttc font")
    g.add_argument("--bold-font", help="path to a bold .ttf/.ttc font")
    g.add_argument("--font-size", type=float, help="label font size")
    g.add_argument("--wrap", type=int, default=40,
                   help="wrap text at this many characters (0 disables) [%(default)s]")
    g.add_argument("--offset", type=float, help="pixels between the campsite and its box")
    g.add_argument("--layout", choices=("map", "gutter"), default="map",
                   help="'map' sits each box beside its campsite, offset to clear both "
                        "the other boxes and the map's own campsite labels; 'gutter' "
                        "stacks them in margins down the far left and far right, "
                        "leaving the map itself untouched [%(default)s]")
    g.add_argument("--box-gap", type=float,
                   help="vertical gap between boxes stacked in a gutter")
    g.add_argument("--gutter-gap", type=float,
                   help="gap between the edge of the map and its gutter of boxes")
    g.add_argument("--gutter-split", choices=("balanced", "side"), default="balanced",
                   help="'balanced' evens out the two column heights, keeping the "
                        "canvas short; 'side' sends each box to the gutter its "
                        "campsite is nearest, so no leader crosses the map - only "
                        "worth it when the campsites are spread evenly [%(default)s]")
    g.add_argument("--side", choices=("auto", "right", "left", "above", "below"),
                   default="auto",
                   help="which side of the campsite the box sits on (--layout map)")
    g.add_argument("--padding", type=float, help="padding inside the box")
    g.add_argument("--line-gap", type=float, help="extra pixels between lines")
    g.add_argument("--family-gap", type=float, help="extra pixels between families in a box")
    g.add_argument("--no-declutter", dest="declutter", action="store_false",
                   help="do not nudge boxes apart to avoid overlaps (--layout map)")
    g.add_argument("--declutter-steps", type=int, default=12,
                   help="how far to nudge a box sideways when looking for space [%(default)s]")
    g.add_argument("--declutter-pushes", type=int, default=4, choices=(1, 2, 3, 4),
                   help="how far a box may be pushed away from its site [%(default)s]")
    g.add_argument("--site-label-size", type=float,
                   help="height of the campsite labels printed on the map itself, used "
                        "to keep boxes from covering them")
    g.add_argument("--margin", type=float,
                   help="blank border around everything (default: a small border under "
                        "--layout gutter so nothing sits against the page edge, none "
                        "under --layout map); under --layout map this is also the space "
                        "boxes may spill into")
    g.add_argument("--margin-color", type=parse_color, default=(255, 255, 255))
    g.add_argument("--line-style", choices=("elbow", "straight"), default="elbow",
                   help="'elbow' joins a box to its campsite with right-angle segments; "
                        "'straight' draws one diagonal [%(default)s]")
    g.add_argument("--elbow-at", type=float, default=0.1,
                   help="where an elbow turns, as a fraction of the way from the box to "
                        "the campsite. Low values keep the turns in a band beside the "
                        "gutter and let each leader run in to its campsite dead-on; "
                        "turning mid-map instead litters the map with verticals "
                        "[%(default)s]")
    g.add_argument("--no-shadow", dest="shadow", action="store_false",
                   help="drop the shadow under each box and the white casing that keeps "
                        "leaders legible where they cross the map")
    g.add_argument("--no-site-header", dest="site_header", action="store_false",
                   help="omit the site id line at the top of each box")
    g.add_argument("--no-children", dest="show_children", action="store_false",
                   help="show parent names only")

    g = p.add_argument_group("style")
    g.add_argument("--box-fill", type=parse_color, default=(255, 255, 255))
    g.add_argument("--box-alpha", type=int, default=235, help="box opacity 0-255 [%(default)s]")
    g.add_argument("--border-color", type=parse_color, default=(20, 20, 20))
    g.add_argument("--border-width", type=float)
    g.add_argument("--text-color", type=parse_color, default=(20, 20, 20))
    g.add_argument("--children-color", type=parse_color, default=(85, 85, 85))
    g.add_argument("--header-color", type=parse_color, default=(178, 34, 34))
    g.add_argument("--separator-color", type=parse_color, default=(195, 195, 195))
    g.add_argument("--leader-color", type=parse_color, default=(178, 34, 34))
    g.add_argument("--leader-width", type=float)
    g.add_argument("--halo-width", type=float,
                   help="width of the casing drawn under each leader, on top of "
                        "--leader-width")
    g.add_argument("--halo-color", type=parse_color, default=(255, 255, 255))
    g.add_argument("--shadow-offset", type=float)
    g.add_argument("--shadow-blur", type=float)
    g.add_argument("--dot-color", type=parse_color, default=(178, 34, 34))
    g.add_argument("--dot-radius", type=float)

    g = p.add_argument_group("pdf output")
    g.add_argument("--pdf-page-width", type=float,
                   help="page width in inches (default: sized so labels come out at "
                        "roughly --font-size points, whatever the map's resolution)")
    g.add_argument("--pdf-quality", type=int, default=85,
                   help="JPEG quality of images inside the PDF [%(default)s]")
    g.add_argument("--photos", metavar="DIR",
                   help="folder of campsite photos, named after the site (H-1.jpg, "
                        "H1.jpg). Each gets a page of its own and its box on the map "
                        "becomes a link to that page")
    g.add_argument("--photo-page-width", type=float, default=7.5,
                   help="width of a photo page, in inches [%(default)s]")
    g.add_argument("--photo-max-height", type=float, default=6.0,
                   help="tallest a photo may print, in inches [%(default)s]")
    g.add_argument("--photo-caption-size", type=float, default=11.0,
                   help="caption point size on a photo page [%(default)s]")
    g.add_argument("--photo-max-pixels", type=int, default=1600,
                   help="downscale a photo's long edge to this before embedding; a "
                        "photo prints at most a few inches wide, so anything beyond "
                        "this is file size nobody can see (0 keeps the original) "
                        "[%(default)s]")

    g = p.add_argument_group("reporting")
    g.add_argument("--unplaced-out",
                   help="write the families that could not be plotted to this CSV")
    return p


def resolve_scaled(opts, image_size):
    if opts.ui_scale is None:
        opts.ui_scale = max(1.0, image_size[1] / 1000.0)
    if opts.ui_scale <= 0:
        raise SystemExit("--ui-scale must be positive")
    for name, base in SCALED_DEFAULTS.items():
        if getattr(opts, name) is None:
            setattr(opts, name, base * opts.ui_scale)
    if opts.margin is None:
        # Gutter boxes would otherwise sit hard against the page edge.
        opts.margin = opts.gutter_gap if opts.layout == "gutter" else 0.0
    return opts


def write_unplaced(path, rows, fieldnames, reasons):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fieldnames) + ["Unplaced Reason"])
        writer.writeheader()
        for row, reason in zip(rows, reasons):
            out = dict(row)
            out["Unplaced Reason"] = reason
            writer.writerow(out)


def main(argv=None):
    opts = build_parser().parse_args(argv)

    base = Image.open(opts.map_path).convert("RGBA")
    map_size = base.size
    resolve_scaled(opts, map_size)

    sites, no_coords, coord_desc, sections = load_campsites(
        opts.campsites, map_size, opts.coords, opts.site_col, opts.x_col, opts.y_col)
    by_site, meta = load_assignments(opts.assignments, opts.assignment_col, opts.children_col)

    print("map        %s  %dx%d  (ui-scale %.2f, font %.0f)"
          % (opts.map_path, map_size[0], map_size[1], opts.ui_scale, opts.font_size))
    print("campsites  %d located from %s" % (len(sites), coord_desc))
    print("families   %d assigned via %r, children from %r, parents from %s"
          % (sum(len(v) for v in by_site.values()), meta["assignment_col"],
             meta["children_col"], meta["parent_cols"] or "(none)"))
    if meta["unassigned"]:
        print("           %d row(s) had no assignment and were skipped" % meta["unassigned"])

    fonts = {
        "family": load_font(opts.font, opts.font_size, FONT_CANDIDATES),
        "children": load_font(opts.font, opts.font_size * 0.92, FONT_CANDIDATES),
        "header": load_font(opts.bold_font or opts.font, opts.font_size,
                            BOLD_FONT_CANDIDATES + FONT_CANDIDATES),
    }
    ruler = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    blocks, unplaced_rows, unplaced_reasons = [], [], []
    for key, entries in by_site.items():
        if key in sites:
            label, px, py = sites[key]
            families = [(raw, parents, kids) for raw, parents, kids, _ in entries]
            lines = build_block(label, families, opts)
            box_w, box_h, heights, gaps = measure(ruler, lines, fonts, opts)
            blocks.append({"label": label, "key": key, "px": px, "py": py,
                           "w": box_w, "h": box_h, "lines": lines,
                           "heights": heights, "gaps": gaps})
        else:
            reason = ("site has no coordinates in the campsites CSV"
                      if key in no_coords else "site not found in the campsites CSV")
            for raw, _, _, row in entries:
                unplaced_rows.append(row)
                unplaced_reasons.append("%s: %s" % (raw, reason))

    if opts.layout == "gutter":
        base, boxes, how = layout_gutter(base, blocks, opts)
    else:
        base, boxes, how = layout_on_map(
            base, blocks, list(sites.values()), opts)
    if (base.width, base.height) != map_size:
        print("canvas     grown to %dx%d for the boxes (%s)"
              % (base.width, base.height, how))

    if opts.out.lower().endswith(".pdf"):
        photos = load_photos(opts.photos, sites, sections) if opts.photos else {}
        if opts.photos:
            linked = sum(1 for box in boxes if box.get("key") in photos)
            missing = sorted(box["label"] for box in boxes if box["key"] not in photos)
            print("photos     %d matched a campsite, %d linked from the map"
                  % (len(photos), linked))
            if missing:
                print("           %d assigned campsite(s) have no photo: %s"
                      % (len(missing), ", ".join(missing)))
        page_w, page_h, count = render_pdf(base, boxes, fonts, opts, opts.out, photos)
        written = ("  (%.1f x %.1f in, %d page%s, searchable text)"
                   % (page_w, page_h, count, "" if count == 1 else "s"))
    else:
        out = draw_map(base, boxes, fonts, opts)
        if opts.out.lower().endswith((".jpg", ".jpeg")):
            out.convert("RGB").save(opts.out, quality=92)
        else:
            out.save(opts.out)
        written = ""

    placed = [b["rect"] for b in boxes]
    residual = sum(overlap_area(a, b) for i, a in enumerate(placed) for b in placed[i + 1:])
    print("drew       %d box(es) -> %s%s%s"
          % (len(boxes), opts.out, written,
             "" if residual == 0 else "  (%.2f%% of box area still overlaps)"
             % (100.0 * residual / max(1.0, sum(w * h for _, _, w, h in placed)))))

    if unplaced_rows:
        print("\n%d famil%s could not be plotted:"
              % (len(unplaced_rows), "y" if len(unplaced_rows) == 1 else "ies"), file=sys.stderr)
        grouped = OrderedDict()
        for reason in unplaced_reasons:
            site, _, why = reason.partition(": ")
            grouped.setdefault(why, []).append(site)
        for why, site_list in grouped.items():
            print("  %s -- %d: %s" % (why, len(site_list), ", ".join(sorted(set(site_list)))),
                  file=sys.stderr)
        if opts.unplaced_out:
            write_unplaced(opts.unplaced_out, unplaced_rows,
                           list(meta["rows"][0].keys()), unplaced_reasons)
            print("  written to %s" % opts.unplaced_out, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
