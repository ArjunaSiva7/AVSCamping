*Description*:
This describes steps to follow to assign families to campsites. The goal here is to assign specific campsites for families

*Inputs*:
- Families: A list of families that include the family members, the children grades, the number of attendees and what site type that family was assigned to. This is the output of the lottery, so it also carries each family's *Code*, *Cabin Waitlist* position and *Locked* flag. Preserve all of those columns as-is.
  - Children and their grades come from the single *Children* column, holding pipe separated Name:Grade pairs ordered youngest grade first, e.g. `Ada Siva:2|Ravi Siva:4`. Grades may be `K` or `TK`, and a pair may have an empty grade. Parse that column to do the grade based grouping below, and write it back unchanged.
- Campsites: A sheet describing the campsites available, and adjacency information on which sites are near each other. This sheet indicates the number of campsites of each type. They may be named accordingly based on the type of site they are. See *Campsites Schema* below for the expected columns.
- Output: A path to a sheet or some other file to place the output. By default, use the Families input.
- Adjustments: A sheet, list of text, or a combination of tweaks that inform the assignment strategy. This is often used to override the default strategy when a specific family requests to be near another family.


*Procedure*:
- Assign families to specific sites using the *Assignment Strategy* below, in two passes: first decide which families share which campsite (*Sharing A Tent Campsite*), then decide where those groups sit on the map (*Keeping Grades Near Each Other*).
- Leave the "Assignment" column empty for families whose *Site Type* is blank or does not match any campsite `section`: report them rather than guessing a site.
- Tent site types coming out of the lottery are numbered tickets on the tent section name (Tent Site-1, Tent Site-2, ...) reflecting signup order, not real campsites. Use that order when placing tent families, and expect more tickets than there are tent sites.
- You will likely run out of tent campsite space. Put left-over families on TENTWAITLIST-<number>
- Once you are done, save the result including all family details to *Output* including the specific site assignment as column "Assignment".

*Campsites Schema*:
The campsite sheet is a CSV, one row per individual campsite, e.g. River-Bend-campsites-2026.csv in the AVSRiverBendFall2026 repo for the 2026 River Bend trip. Expected columns:
- site: the campsite identifier, e.g. `H-21`, `T-4`, `CC-11`. Unique, and the value written to the "Assignment" column.
- section: the site type this campsite belongs to, e.g. `Tent Site`, `Oxbow RV`, `RV Site`, `R Site`, `Stumptown`, `Camp Canoe`, `Fish Camp`, `VWs`. Match this against the *Site Type* each family was assigned in the lottery.
- x_pixels, y_pixels (older sheets: x_px, y_px) and x_percent, y_percent: the campsite's coordinates on the campground map image. Useful for sanity-checking layout and for approximating nearness when `adjacent_sites` is sparse.
- capacity: maximum number of people on that campsite. Only populated for tent sites, where multiple families share a site; blank for the single-family site types.
- description: free text about the site, e.g. sun/shade, features, check-in and check-out times. May repeat the max capacity. Only populated for tent sites.
- adjacent_sites: the neighbouring campsites, as a comma separated list of `site` values, e.g. `"T-3, T-5"`. This is the adjacency information used to place families near each other; it is symmetric, so treat it as an undirected neighbour list.

*Assignment Strategy*:
You'll be assigning campsites according to the following strategy:

Note: You might be operating on an output that has already had prior runs on it as this is an iterative process. Try to avoid messing with existing assignments unless you have to. Families whose *Locked* flag is set have already been notified: never move them, and treat their sites as taken before placing anyone else.

- Tent campsites can usually accommodate multiple families; the total attendees on a tent site must stay within that site's `capacity`. All non-tent campsites take only one family -- do not exceed 1 family for those, and ignore their blank `capacity`.
- Look at *Adjustments* for any tweaks on the strategy. An *Adjustment* wins over every rule below.
- Non-tent families were assigned based on site availability. You will likely run out of space for tent sites.

*Grouping Grade*:
Every family gets exactly one grouping grade, and that is the only grade used to decide who camps with or near whom:
- It is the grade of the family's youngest child, i.e. the lowest grade in *Children*, ordering `TK` < `K` < `1` < `2` < ... So a family with a 2nd grader and a 4th grader groups with the 2nd graders.
- Ignore children whose grade is empty. A family with no usable grade at all (no children, or all grades blank) forms its own "unknown" group: never fold it into a numbered grade group.

*Sharing A Tent Campsite*:
Same-grade grouping is a hard rule, not a preference. It outranks packing density:
- All families sharing one tent campsite must have the same grouping grade. Leaving capacity unused on a tent site is the correct outcome when the only families left to place have a different grouping grade -- do not fill the gap by mixing grades, and do not reorder grades to make a site fit exactly.
- Walk the tent tickets in lottery order (Tent Site-1, Tent Site-2, ...). For each ticket in turn:
  - If a tent campsite already opened for that family's grouping grade has room for all its attendees, put the family there. Prefer the site with the least room left that still fits, so the roomier sites stay free for larger families.
  - Otherwise open an unused tent campsite whose `capacity` fits the family, preferring one adjacent to a campsite already opened for that grouping grade.
  - If neither is possible, skip the family for now and keep going -- a later, smaller family may still fit the space that is left. Skipped families become the tent waitlist.
- Tent waitlist: after the walk, number the families that never got a campsite `TENTWAITLIST-1`, `TENTWAITLIST-2`, ... in tent lottery order.

*Keeping Grades Near Each Other*:
Once you know which families share which campsite, place those groups on the map so a grade's families are neighbours where the site sizes allow:
- Order the campsites of a section into a walking order by following `adjacent_sites` (fall back to the map coordinates where adjacency is sparse), then lay the groups along that order by ascending grouping grade, with the unknown group last.
- Grades adjacent in school (1st next to 2nd) are better neighbours than distant ones, so keep the ascending order rather than scattering groups.
- Sites differ in `capacity`, so a large group may have to sit out of order on a big site. Move only that group, and keep the rest of the sequence in grade order. Never break a group up or mix grades to improve adjacency.
- For non-tent sections, one family per campsite: order that section's families by grouping grade and lay them along the section's walking order the same way.
- This step only relabels which campsite a group occupies. It must not change who shares a campsite or who is waitlisted, and it must never move a *Locked* family.
