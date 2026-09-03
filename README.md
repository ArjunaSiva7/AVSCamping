# AVSCamping

Procedures for running the AVS camping trip campsite lottery and campsite assignments.

The two stage files here are specs written to be executed by an agent (or followed by hand) rather than code. The one exception is [plot_assignments.py](plot_assignments.py), a helper for the last step. Trip-specific data lives in a separate per-trip repo.

## The two stages

Run them in order — the second consumes the output of the first.

1. **[lottery.md](lottery.md)** — assigns each family a site *type* (a cabin/glamping type, a tent ticket, or a cabin waitlist position). This is where the random lottery *Code* is drawn and where fairness rules live.
2. **[assignments.md](assignments.md)** — assigns each family a *specific* campsite within their type, grouping families by children's grades and honouring adjacency requests.

Then, to see the result: **[plot_assignments.py](plot_assignments.py)** draws the finished
assignments onto the campground map, one box per campsite listing each family on that site
with their children and grades.

```bash
python3 plot_assignments.py \
    --campsites River-Bend-campsites-2026.csv \
    --map River-Bend-Map-2026-8x.png \
    --assignments assignments.csv \
    --out River-Bend-assignments-2026.pdf \
    --photos "River Bend Campsite Images 2026" \
    --unplaced-out unplaced.csv
```

Needs Pillow, and nothing else. Notes:

- Each box sits **beside its own campsite**, offset until it clears both the other boxes and
  the campsite labels printed on the map itself, and joined to its site by an elbow connector.
  `--site-label-size` is the assumed height of those map labels; `--layout gutter` instead
  stacks every box in margins down the far left and far right, growing the canvas until they
  fit, which leaves the map completely untouched at the cost of much longer connectors.
- `--photos DIR` gives every campsite with a photo **a page of its own** in the PDF — the
  photo, who is camping there, and a link back to the map — and turns that campsite's box on
  the map into a link to that page. Filenames are matched loosely against the site id, so
  `H1.jpg`, `H-1.jpg` and `h 1.JPG` all resolve to campsite H-1; a one-off cabin named on disk
  after what the map calls it (`Magic Bus.jpeg`, `The Outpost.jpg`) is matched on its section
  instead, which only applies to sections holding a single campsite. Photos matching no
  campsite, and assigned campsites with no photo, are both reported rather than passing
  silently. `--photo-max-pixels` caps the resolution embedded, since a photo only prints a few
  inches wide.
- Each child's name and grade is **coloured by grade**, so one grade's families can be picked
  out at a glance. The palette is fixed, so a grade keeps its colour between runs.
- `--gutter-split balanced` (the default) evens out the two column heights. `--gutter-split
  side` keeps every leader on its own half of the map, but only makes sense when the campsites
  are spread evenly — River Bend's cluster on the right, so it produces one 63-box column.

- A `.pdf` output is **searchable** — the map goes in as an image, but the boxes are vectors
  and the labels are real text, so a family can ctrl-F for their own name instead of squinting
  at the map. Any other extension writes a flat image. `--pdf-page-width` sets the page size in
  inches; by default the page is sized so labels land at roughly `--font-size` points, whatever
  the map image's resolution.
- It prefers the campsites sheet's `x_percent`/`y_percent` over `x_pixels`/`y_pixels`, so the
  same sheet works against a rescaled map image. `--coords` overrides the guess.
- `--margin` pads blank space around the map for boxes to spill into. On a crowded map this is
  the difference between overlapping boxes and none; the trade-off is a larger output image.
- Anyone it cannot place — tent waitlist tickets, or a site missing from the campsites sheet —
  is reported on stderr and, with `--unplaced-out`, written to a CSV. Check that list: a site
  that has gone missing shows up here rather than being silently dropped.
- `--help` lists the styling and layout knobs (fonts, colours, wrapping, box placement).

## Inputs

Both specs list their own inputs. The ones that change per trip:

- **Signups** — the signup sheet: names, campsite preferences, first submitted timestamp, number of attendees, whether they missed out on a cabin last year, and whether they'd accept a tent.
- **Directory** — the family directory, used to cross reference signups and pull children's names, grades, and parent emails. Defaults to the [AVS parent directory](https://portals.veracross.com/avs/parent/directory/households), which needs a login; a sheet or file can be supplied instead.
- **Campsites** — one row per campsite, with section, capacity, and adjacency. See *Campsites Schema* in [assignments.md](assignments.md) for the columns. For the 2026 River Bend trip this is `River-Bend-campsites-2026.csv` in the [AVSRiverBendFall2026](https://github.com/ArjunaSiva7/AVSRiverBendFall2026) repo, alongside the campground map image.
- **Adjustments** (assignment stage only) — tweaks that override the default strategy, e.g. a family asking to be placed near another family.
- **Output** — a path to the sheet or file to write to. The lottery's output is the assignment stage's Families input.
- **Summary Output** (assignment stage only) — where to write the per-campsite summary CSV: one row per campsite with the families and children on it, its capacity, and its occupancy. Defaults to `<output name>-sites.csv`.

## Things worth knowing before you run it

- **Both stages are re-runnable and expected to be re-run** as late signups arrive. Existing lottery *Codes* are never redrawn, and a family whose `Locked` column is set has already been notified — their site type must not change, and their site counts as taken before anyone else is placed.
- **Save as you go.** Write progress to the output file as you work so the process can be inspected and adjusted mid-run.
- **Record the random seed** used to draw codes, so a disputed lottery result can be reproduced.
