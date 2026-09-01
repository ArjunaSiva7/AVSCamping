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

    sites = OrderedDict()
    for label, x, y in usable:
        sites[site_key(label)] = (label, x * sx, y * sy)
    return sites, no_coords, "%s/%s (%s)" % (x_col, y_col, kind), kind


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


def format_children(raw):
    """`Jane Doe:1|Mike Chen:4` -> `Jane Doe (1), Mike Chen (4)`."""
    parts = []
    for chunk in (raw or "").split("|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, _, grade = chunk.partition(":")
        name, grade = name.strip(), grade.strip()
        if not name:
            continue
        parts.append("%s (%s)" % (name, grade) if grade else name)
    return ", ".join(parts)


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
        kids = format_children(row.get(children_col)) if children_col else ""
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


def build_block(site_label, families, opts):
    """Lines of one box as (text, kind, starts_new_family)."""
    lines = []
    if opts.site_header:
        header = site_label
        if len(families) > 1:
            header = "%s  (%d families)" % (site_label, len(families))
        lines.append((header, "header", False))
    for index, (_, parents, kids) in enumerate(families):
        first = True
        for line in wrap(parents, opts.wrap) or [parents]:
            lines.append((line, "family", index > 0 and first))
            first = False
        if kids and opts.show_children:
            for line in wrap(kids, opts.wrap, indent="  "):
                lines.append((line, "children", False))
    return lines


def measure(draw, lines, fonts, opts):
    """(width, height, per-line heights, per-line leading gaps) of a block."""
    widths, heights, gaps = [], [], []
    for text, kind, starts_family in lines:
        w, h = draw.textbbox((0, 0), text or " ", font=fonts[kind])[2:]
        widths.append(w)
        heights.append(h + opts.line_gap)
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


def choose_position(px, py, box_w, box_h, placed, points, bounds, opts):
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
                covered = sum(1 for qx, qy in points
                              if x <= qx <= x + box_w and y <= qy <= y + box_h)
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
            boxes.append((box["px"], box["py"], (x, box["y"], box["w"], box["h"]),
                          box["lines"], box["heights"], box["gaps"]))
    return canvas, boxes, "%d left / %d right" % (len(left), len(right))


def layout_on_map(base, blocks, points, opts):
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
        points = [(x + margin, y + margin) for x, y in points]

    edge = max(2.0, opts.border_width)
    bounds = (edge, edge, base.width - edge, base.height - edge)
    placed, boxes = [], []
    # Biggest boxes claim space first; they are the hardest to fit later.
    for box in sorted(blocks, key=lambda b: -(b["w"] * b["h"])):
        rect = choose_position(box["px"], box["py"], box["w"], box["h"],
                               placed, points, bounds, opts)
        placed.append(rect)
        boxes.append((box["px"], box["py"], rect, box["lines"], box["heights"], box["gaps"]))
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
    routes = [(leader_points(px, py, rect, opts))
              for px, py, rect, _, _, _ in boxes]

    if opts.shadow:
        shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
        pen = ImageDraw.Draw(shadow)
        off = opts.shadow_offset
        for x, y, w, h in (rect for _, _, rect, _, _, _ in boxes):
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

    for px, py, rect, lines, heights, gaps in boxes:
        x, y, w, h = rect
        draw.rectangle((x, y, x + w, y + h), fill=opts.box_fill + (opts.box_alpha,),
                       outline=opts.border_color + (255,),
                       width=max(1, int(round(opts.border_width))))
        cursor = y + opts.padding
        for (text, kind, _), line_h, gap in zip(lines, heights, gaps):
            if gap:
                mid = cursor + gap / 2.0
                draw.line((x + opts.padding, mid, x + w - opts.padding, mid),
                          fill=opts.separator_color + (255,),
                          width=max(1, int(round(opts.border_width / 2))))
                cursor += gap
            draw.text((x + opts.padding, cursor), text, font=fonts[kind],
                      fill=colors[kind] + (255,))
            cursor += line_h

    r = opts.dot_radius
    if r > 0:
        for px, py, _, _, _, _ in boxes:
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

    def add_stream(self, entries, data):
        return self.add(b"<< " + entries + b" /Length %d >>\nstream\n" % len(data)
                        + data + b"\nendstream")

    def save(self, path):
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


def render_pdf(base, boxes, fonts, opts, path):
    """Write the map plus vector boxes and live text to a PDF."""
    width, height = base.size
    scale = (opts.pdf_page_width * 72.0 / width if opts.pdf_page_width
             else 1.0 / opts.ui_scale)
    page_w, page_h = width * scale, height * scale

    def sx(x):
        return x * scale

    def sy(y):
        return (height - y) * scale  # PDF's origin is bottom-left

    ascents = {kind: font.getmetrics()[0] for kind, font in fonts.items()}
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
        for _, _, (x, y, w, h), _, _, _ in boxes:
            for step in (0.0, 0.5, 1.0):
                grow = opts.shadow_blur * step
                ox, oy = opts.shadow_offset, opts.shadow_offset
                body += b"%s %s %s %s re f\n" % (
                    n(sx(x + ox - grow)), n(sy(y + h + oy + grow)),
                    n((w + 2 * grow) * scale), n((h + 2 * grow) * scale))
        body += b"Q\n"

    routes = [leader_points(px, py, rect, opts) for px, py, rect, _, _, _ in boxes]
    if opts.shadow and opts.halo_width > 0:
        body += rgb(opts.halo_color, stroke=True)
        body += b"%s w\n" % n(max(0.1, (opts.leader_width + opts.halo_width) * scale))
        for route in routes:
            body += polyline(route)
    body += rgb(opts.leader_color, stroke=True)
    body += b"%s w\n" % n(max(0.1, opts.leader_width * scale))
    for route in routes:
        body += polyline(route)

    for px, py, rect, lines, heights, gaps in boxes:
        x, y, w, h = rect
        body += b"q /GS1 gs\n"
        body += rgb(opts.box_fill) + rgb(opts.border_color, stroke=True)
        body += b"%s w\n" % n(max(0.1, opts.border_width * scale))
        body += b"%s %s %s %s re B\nQ\n" % (n(sx(x)), n(sy(y + h)),
                                             n(w * scale), n(h * scale))
        cursor = y + opts.padding
        for (text, kind, _), line_h, gap in zip(lines, heights, gaps):
            if gap:
                mid = cursor + gap / 2.0
                body += rgb(opts.separator_color, stroke=True)
                body += b"%s w\n" % n(max(0.1, opts.border_width * scale / 2))
                body += b"%s %s m %s %s l S\n" % (n(sx(x + opts.padding)), n(sy(mid)),
                                                  n(sx(x + w - opts.padding)), n(sy(mid)))
                cursor += gap
            size = opts.font_size * (0.92 if kind == "children" else 1.0) * scale
            body += b"BT %s %s Tf %s%s %s Td (%s) Tj ET\n" % (
                PDF_FONT_RESOURCE[kind], n(size), rgb(colors[kind]),
                n(sx(x + opts.padding)), n(sy(cursor + ascents[kind])), pdf_text(text))
            cursor += line_h

    if opts.dot_radius > 0:
        body += rgb(opts.dot_color)
        for px, py, _, _, _, _ in boxes:
            body += pdf_circle(sx(px), sy(py), opts.dot_radius * scale)

    jpeg = io.BytesIO()
    base.convert("RGB").save(jpeg, "JPEG", quality=opts.pdf_quality, optimize=True)
    jpeg = jpeg.getvalue()

    pdf = PdfWriter()
    catalog = pdf.add(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages = pdf.add(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    page = pdf.add(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %s %s] "
                   b"/Resources << /XObject << /Im0 5 0 R >> "
                   b"/Font << /F1 6 0 R /F2 7 0 R >> "
                   b"/ExtGState << /GS1 8 0 R /GS2 9 0 R >> >> /Contents 4 0 R >>"
                   % (n(page_w), n(page_h)))
    pdf.add_stream(b"", bytes(body))
    pdf.add_stream(b"/Type /XObject /Subtype /Image /Width %d /Height %d "
                   b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode"
                   % (width, height), jpeg)
    for face in (b"/Helvetica", b"/Helvetica-Bold"):
        pdf.add(b"<< /Type /Font /Subtype /Type1 /BaseFont %s "
                b"/Encoding /WinAnsiEncoding >>" % face)
    pdf.add(b"<< /Type /ExtGState /ca %s /CA 1 >>" % n(opts.box_alpha / 255.0))
    pdf.add(b"<< /Type /ExtGState /ca 0.10 /CA 0.10 >>")  # drop shadow
    assert (catalog, pages, page) == (1, 2, 3), "object numbers are referenced by hand"
    pdf.save(path)
    return page_w / 72.0, page_h / 72.0


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
    g.add_argument("--layout", choices=("gutter", "map"), default="gutter",
                   help="'gutter' stacks the boxes in margins down the far left and "
                        "far right, leaving the map itself clear, and grows the canvas "
                        "until they fit; 'map' sits each box beside its campsite "
                        "[%(default)s]")
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
                   help="JPEG quality of the map inside the PDF [%(default)s]")

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

    sites, no_coords, coord_desc, _ = load_campsites(
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
            blocks.append({"px": px, "py": py, "w": box_w, "h": box_h,
                           "lines": lines, "heights": heights, "gaps": gaps})
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
            base, blocks, [(x, y) for _, x, y in sites.values()], opts)
    if (base.width, base.height) != map_size:
        print("canvas     grown to %dx%d for the boxes (%s)"
              % (base.width, base.height, how))

    if opts.out.lower().endswith(".pdf"):
        page = render_pdf(base, boxes, fonts, opts, opts.out)
        written = "  (%.1f x %.1f in, searchable text)" % page
    else:
        out = draw_map(base, boxes, fonts, opts)
        if opts.out.lower().endswith((".jpg", ".jpeg")):
            out.convert("RGB").save(opts.out, quality=92)
        else:
            out.save(opts.out)
        written = ""

    placed = [rect for _, _, rect, _, _, _ in boxes]
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
