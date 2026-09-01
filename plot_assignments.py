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
import math
import os
import re
import sys
import textwrap
from collections import OrderedDict

from PIL import Image, ImageDraw, ImageFont

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
    "font_size": 12.0,
    "offset": 22.0,
    "padding": 7.0,
    "line_gap": 3.0,
    "family_gap": 7.0,
    "border_width": 2.0,
    "leader_width": 2.0,
    "dot_radius": 4.0,
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


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------

def draw_map(base, boxes, fonts, opts):
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    colors = {"header": opts.header_color, "family": opts.text_color,
              "children": opts.children_color}

    # Every leader first, so a line never appears to stop at an unrelated box.
    for px, py, rect, _, _, _ in boxes:
        ax, ay = anchor_point(px, py, rect)
        draw.line((px, py, ax, ay), fill=opts.leader_color + (255,),
                  width=max(1, int(round(opts.leader_width))))

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
    p.add_argument("--out", required=True, help="output image path")

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
    g.add_argument("--side", choices=("auto", "right", "left", "above", "below"),
                   default="auto", help="which side of the campsite the box sits on")
    g.add_argument("--padding", type=float, help="padding inside the box")
    g.add_argument("--line-gap", type=float, help="extra pixels between lines")
    g.add_argument("--family-gap", type=float, help="extra pixels between families in a box")
    g.add_argument("--no-declutter", dest="declutter", action="store_false",
                   help="do not nudge boxes apart to avoid overlaps")
    g.add_argument("--declutter-steps", type=int, default=12,
                   help="how far to nudge a box sideways when looking for space [%(default)s]")
    g.add_argument("--declutter-pushes", type=int, default=4, choices=(1, 2, 3, 4),
                   help="how far a box may be pushed away from its site [%(default)s]")
    g.add_argument("--margin", type=float, default=0,
                   help="pixels of blank border added around the map, giving edge "
                        "boxes somewhere to go [%(default)s]")
    g.add_argument("--margin-color", type=parse_color, default=(255, 255, 255))
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
    g.add_argument("--dot-color", type=parse_color, default=(178, 34, 34))
    g.add_argument("--dot-radius", type=float)

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

    margin = max(0.0, opts.margin)
    if margin:
        canvas = Image.new("RGBA", (int(round(map_size[0] + 2 * margin)),
                                    int(round(map_size[1] + 2 * margin))),
                           opts.margin_color + (255,))
        canvas.paste(base, (int(round(margin)), int(round(margin))))
        base = canvas
        sites = OrderedDict((k, (label, x + margin, y + margin))
                            for k, (label, x, y) in sites.items())
    by_site, meta = load_assignments(opts.assignments, opts.assignment_col, opts.children_col)

    print("map        %s  %dx%d%s  (ui-scale %.2f, font %.0f)"
          % (opts.map_path, map_size[0], map_size[1],
             " + %.0fpx margin" % margin if margin else "",
             opts.ui_scale, opts.font_size))
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

    # Biggest boxes claim space first; they are the hardest to fit later.
    pending, unplaced_rows, unplaced_reasons = [], [], []
    for key, entries in by_site.items():
        if key in sites:
            label, px, py = sites[key]
            families = [(raw, parents, kids) for raw, parents, kids, _ in entries]
            lines = build_block(label, families, opts)
            box_w, box_h, heights, gaps = measure(ruler, lines, fonts, opts)
            pending.append((box_w * box_h, px, py, box_w, box_h, lines, heights, gaps))
        else:
            reason = ("site has no coordinates in the campsites CSV"
                      if key in no_coords else "site not found in the campsites CSV")
            for raw, _, _, row in entries:
                unplaced_rows.append(row)
                unplaced_reasons.append("%s: %s" % (raw, reason))
    pending.sort(key=lambda item: -item[0])

    points = [(x, y) for _, x, y in sites.values()]
    edge = max(2.0, opts.border_width)
    bounds = (edge, edge, base.width - edge, base.height - edge)
    placed, boxes = [], []
    for _, px, py, box_w, box_h, lines, heights, gaps in pending:
        rect = choose_position(px, py, box_w, box_h, placed, points, bounds, opts)
        placed.append(rect)
        boxes.append((px, py, rect, lines, heights, gaps))

    out = draw_map(base, boxes, fonts, opts)
    if opts.out.lower().endswith((".jpg", ".jpeg")):
        out.convert("RGB").save(opts.out, quality=92)
    else:
        out.save(opts.out)

    residual = sum(overlap_area(a, b) for i, a in enumerate(placed) for b in placed[i + 1:])
    print("drew       %d box(es) -> %s%s"
          % (len(boxes), opts.out,
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
