*Description*:
This describes steps to follow to assign families to campsites. The goal here is to assign specific campsites for families

*Inputs*:
- Families: A list of families that include the family members, the children grades, the number of attendees and what site type that family was assigned to. This is the output of the lottery, so it also carries each family's *Code*, *Cabin Waitlist* position and *Locked* flag. Preserve all of those columns as-is.
  - Children and their grades come from the single *Children* column, holding pipe separated Name:Grade pairs ordered youngest grade first, e.g. `Ada Siva:2|Ravi Siva:4`. Grades may be `K` or `TK`, and a pair may have an empty grade. Parse that column to do the grade based grouping below, and write it back unchanged.
- Campsites: A sheet describing the campsites available, and adjacency information on which sites are near each other. This sheet indicates the number of campsites of each type. They may be named accordingly based on the type of site they are. See *Campsites Schema* below for the expected columns.
- Output: A path to a sheet or some other file to place the output. By default, use the Families input.
- Summary Output: A path for the per-campsite summary CSV described in *Per-Campsite Summary* below. By default, write it next to *Output* as `<output name>-sites.csv`.
- Adjustments: A sheet, list of text, or a combination of tweaks that inform the assignment strategy. This is often used to override the default strategy when a specific family requests to be near another family.


*Procedure*:
- Assign families to specific sites using the *Assignment Strategy* below, in three passes: first give each grade its own stretch of the map (*Keeping Grades Near Each Other*), then fill that stretch with the grade's families (*Sharing A Tent Campsite*), then spend campsites' `extra_capacity` on the families still left over (*Spending Extra Capacity*).
- Leave the "Assignment" column empty for families whose *Site Type* is blank or does not match any campsite `section`: report them rather than guessing a site.
- Tent site types coming out of the lottery are numbered tickets on the tent section name (Tent Site-1, Tent Site-2, ...) reflecting signup order, not real campsites. Use that order when placing tent families, and expect more tickets than there are tent sites.
- You will likely run out of tent campsite space. Put left-over families on TENTWAITLIST-<number>
- Once you are done, save the result including all family details to *Output* including the specific site assignment as column "Assignment".
- Then write the per-campsite summary to *Summary Output*, derived from that same result so the two files can never disagree. Regenerate it in full on every run.

*Campsites Schema*:
The campsite sheet is a CSV, one row per individual campsite, e.g. River-Bend-campsites-2026.csv in the AVSRiverBendFall2026 repo for the 2026 River Bend trip. Expected columns:
- site: the campsite identifier, e.g. `H-21`, `T-4`, `CC-11`. Unique, and the value written to the "Assignment" column.
- section: the site type this campsite belongs to, e.g. `Tent Site`, `Oxbow RV`, `RV Site`, `R Site`, `Stumptown`, `Camp Canoe`, `Fish Camp`, `VWs`. Match this against the *Site Type* each family was assigned in the lottery.
- x_pixels, y_pixels (older sheets: x_px, y_px) and x_percent, y_percent: the campsite's coordinates on the campground map image. Useful for sanity-checking layout and for approximating nearness when `adjacent_sites` is sparse.
- capacity: maximum number of people on that campsite at no extra charge. Only populated for tent sites, where multiple families share a site; blank for the single-family site types.
- extra_capacity: further people the campsite will take on top of `capacity`, usually at a per-person surcharge. Blank or `0` means the site has none. `capacity` + `extra_capacity` is the campsite's *extended capacity*: the hard ceiling, never to be exceeded, and only to be reached under *Spending Extra Capacity* below.
- description: free text about the site, e.g. sun/shade, features, check-in and check-out times. May repeat the max capacity. Only populated for tent sites.
- adjacent_sites: the neighbouring campsites, as a comma separated list of `site` values, e.g. `"T-3, T-5"`. This is the adjacency information used to place families near each other; it is symmetric, so treat it as an undirected neighbour list.

*Assignment Strategy*:
You'll be assigning campsites according to the following strategy:

Note: You might be operating on an output that has already had prior runs on it as this is an iterative process. Try to avoid messing with existing assignments unless you have to. Families whose *Locked* flag is set have already been notified: never move them, and treat their sites as taken before placing anyone else.

- Tent campsites can usually accommodate multiple families; the total attendees on a tent site must stay within that site's `capacity`, and may only go past it into its extended capacity where *Spending Extra Capacity* allows. All non-tent campsites take only one family -- do not exceed 1 family for those, and ignore their blank `capacity`.
- Look at *Adjustments* for any tweaks on the strategy. An *Adjustment* wins over every rule below.
- Non-tent families were assigned based on site availability. You will likely run out of space for tent sites.

*Grouping Grade*:
Every family gets exactly one grouping grade, and that is the only grade used to decide who camps with or near whom:
- It is the grade of the family's youngest child, i.e. the lowest grade in *Children*, ordering `TK` < `K` < `1` < `2` < ... So a family with a 2nd grader and a 4th grader groups with the 2nd graders.
- Ignore children whose grade is empty. A family with no usable grade at all (no children, or all grades blank) forms its own "unknown" group: never fold it into a numbered grade group.

*Keeping Grades Near Each Other*:
Grades claim their space on the map before any family is seated, so no grade can end up marooned inside another grade's stretch:
- Order the campsites of a section into a walking order by following `adjacent_sites` (fall back to the map coordinates where adjacency is sparse). This walking order is the only notion of "near" that matters.
- Cut that walk into one contiguous block of campsites per grouping grade, in ascending grade order, with the unknown grade last. So walking the section you meet every TK campsite, then every K campsite, then every 1st-grade campsite, and so on -- a grade's campsites are never split by another grade's.
- Size each block by how much room the grade needs: give it a share of the section's total `capacity` proportional to that grade's total attendees, taking whole campsites off the front of the remaining walk. Every grade with families gets at least one campsite.
- Size blocks on `capacity` alone, ignoring `extra_capacity`. Extra capacity is a reserve spent later, on the grade that turns out to need it, not free space a grade is handed up front.
- Do not swap or reorder blocks to make the `capacity` fit a grade better, and do not carve a grade's block out of two separate stretches. A grade whose families are too large for the campsites in its block waitlists them (see below) -- that is the correct outcome, and it is what keeps the map readable.

*Sharing A Tent Campsite*:
Same-grade grouping is a hard rule, not a preference. It outranks packing density:
- All families sharing one tent campsite must have the same grouping grade. Leaving capacity unused on a tent site is the correct outcome when the only families left to place have a different grouping grade -- do not fill the gap by mixing grades, and do not reorder grades to make a site fit exactly.
- Take each grade in turn and walk its tent tickets in lottery order (Tent Site-1, Tent Site-2, ...), seating each family on a campsite from that grade's block only, and within that campsite's `capacity`. Prefer the campsite in the block with the least room left that still fits the whole family, so the roomier ones stay free for larger families.
- If no campsite in the block fits the family, skip it for now and keep going -- a later, smaller family of the same grade may still fit the space that is left. Skipped families become the tent waitlist.
- Once every grade has been seated, a grade that still has families waiting may take a campsite that its neighbouring grade left completely empty, and only the campsite on the shared edge of the two blocks: an unused campsite is worth more than a perfect split, and moving the edge keeps both blocks contiguous. If the edge campsite is occupied but the neighbouring grade has an empty campsite deeper in its block that fits the edge's families, slide those families onto it first, then hand over the freed edge. Repeat while such a move seats someone.
- Tent waitlist: number the families that never got a campsite `TENTWAITLIST-1`, `TENTWAITLIST-2`, ... in tent lottery order across all grades. Draw this list only after *Spending Extra Capacity* has run, so nobody is waitlisted while paid room is still going spare.
- For non-tent sections, one family per campsite: seat that section's families inside their grade's block the same way.
- Never move a *Locked* family: treat its campsite as belonging to its grade's block and seat it there first.

*Spending Extra Capacity*:
A campsite's `extra_capacity` is room beyond its `capacity` that the campground will sell at a per-person surcharge. Spend it to seat families who would otherwise be waitlisted, never merely to pack a site tighter:
- Run this pass last, after every grade has been seated within `capacity` and after the empty-edge campsite moves above have been made. Free room is always spent before paid room.
- Walk the families still waiting in tent lottery order. For each, consider only campsites in that family's own grade block, and seat it where the whole family fits within extended capacity (`capacity` + `extra_capacity`).
- Bias hard towards keeping a grade together. Rank the candidate campsites: first the ones already holding families of this family's grouping grade, and among those the one left with the least unused extended capacity; only if none of them can stretch far enough does an empty campsite in the block get stretched. Filling out a site the grade is already on is worth more than opening a new one.
- Extended capacity never buys an exception to the same-grade rule: never seat a family on a campsite holding another grade, and never stretch a campsite outside the family's own block. Leaving paid room unspent is the correct outcome when the only families left have a different grouping grade.
- Treat a blank or `0` `extra_capacity` as no reserve at all, and never exceed extended capacity. A family that still does not fit stays on the tent waitlist.
- Never move a *Locked* family, but a campsite it sits on may still be stretched to seat another family of the same grouping grade.
- Every campsite pushed past its `capacity` owes a surcharge, so it has to be visible: the *Per-Campsite Summary* carries the `extra_capacity` alongside the occupancy, and those sites are the ones to report back after a run.

*Per-Campsite Summary*:
A second CSV written to *Summary Output*, one row per campsite, so the trip can be read site by site instead of family by family. Columns:
- Site: the campsite's `site` value from the Campsites sheet.
- Section: that campsite's `section`.
- Grouping Grade: the grouping grade of the families on the site (they all share one, per *Sharing A Tent Campsite*). Empty for an empty campsite; `unknown` for the unknown group.
- Families: the families on the site, pipe separated. Label each family `Parent X Name & Parent Y Name`, dropping the ` & ...` when there is no second parent, e.g. `Arjuna Siva & Priya Siva|Sam Lee`.
- Children: the children on the site, pipe separated `Name:Grade` pairs in the same form as the Families input, listed family by family in the same order as *Families*, e.g. `Ada Siva:2|Ravi Siva:4|Mia Lee:2`.
- Capacity: the campsite's `capacity`. Blank for the single-family sections, which have no capacity in the Campsites sheet.
- Extra Capacity: the campsite's `extra_capacity`, copied through as-is. Blank where the Campsites sheet leaves it blank.
- Occupancy: the total *Attendees* of the families on the site. `0` for an empty campsite.

Rules:
- Every campsite in the Campsites sheet gets a row, including the ones nobody was seated on -- an empty site is the thing a reader most wants to spot. Keep the rows in the walking order used in *Keeping Grades Near Each Other* so the file reads along the map, grade block by grade block.
- Add a row per tent waitlist ticket at the end, with `TENTWAITLIST-<number>` in *Site*, the section the family was ticketed for in *Section*, blank *Capacity* and *Extra Capacity*, and the family's attendees in *Occupancy*. Do the same for families left unassigned because their *Site Type* was blank or unmatched, using an empty *Site*.
- *Occupancy* must never exceed *Capacity* + *Extra Capacity* where a capacity is set, and a row must never hold more than one family where *Capacity* is blank. If either happens, the assignment is wrong -- fix the assignment rather than the summary.
- A row whose *Occupancy* is above its *Capacity* but within *Capacity* + *Extra Capacity* is a site into its paid extra room, which is expected after *Spending Extra Capacity*. List those sites, and how many people over `capacity` each is, when reporting the run: the families on them owe the campground a per-person surcharge.
