# AVSCamping

Procedures for running the AVS camping trip campsite lottery and campsite assignments.

The files here are specs written to be executed by an agent (or followed by hand). They are not code; there is nothing to build or run in this repo. Trip-specific data lives in a separate per-trip repo.

## The two stages

Run them in order — the second consumes the output of the first.

1. **[lottery.md](lottery.md)** — assigns each family a site *type* (a cabin/glamping type, a tent ticket, or a cabin waitlist position). This is where the random lottery *Code* is drawn and where fairness rules live.
2. **[assignments.md](assignments.md)** — assigns each family a *specific* campsite within their type, grouping families by children's grades and honouring adjacency requests.

## Inputs

Both specs list their own inputs. The ones that change per trip:

- **Signups** — the signup sheet: names, campsite preferences, first submitted timestamp, number of attendees, whether they missed out on a cabin last year, and whether they'd accept a tent.
- **Directory** — the family directory, used to cross reference signups and pull children's names, grades, and parent emails. Defaults to the [AVS parent directory](https://portals.veracross.com/avs/parent/directory/households), which needs a login; a sheet or file can be supplied instead.
- **Campsites** — one row per campsite, with section, capacity, and adjacency. See *Campsites Schema* in [assignments.md](assignments.md) for the columns. For the 2026 River Bend trip this is `River-Bend-campsites-2026.csv` in the [AVSRiverBendFall2026](https://github.com/ArjunaSiva7/AVSRiverBendFall2026) repo, alongside the campground map image.
- **Adjustments** (assignment stage only) — tweaks that override the default strategy, e.g. a family asking to be placed near another family.
- **Output** — a path to the sheet or file to write to. The lottery's output is the assignment stage's Families input.

## Things worth knowing before you run it

- **Both stages are re-runnable and expected to be re-run** as late signups arrive. Existing lottery *Codes* are never redrawn, and a family whose `Locked` column is set has already been notified — their site type must not change, and their site counts as taken before anyone else is placed.
- **Save as you go.** Write progress to the output file as you work so the process can be inspected and adjusted mid-run.
- **Record the random seed** used to draw codes, so a disputed lottery result can be reproduced.
