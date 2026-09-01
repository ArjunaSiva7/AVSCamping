*Description:*
This describes steps to follow for the AVS camping lottery for assigning campsite allocations.

*Inputs:*
- Signups: An input sheet of signups which include names of signups, their campsite preferences, first submitted timestamp, number of attendees and any other relevant details. 
- Special Assignments: Any context about special assignments. For example, there may be one or more families that paid via fundraising for a guranteed cabin.
- Campsites: A sheet describing the campsites available. This sheet indicates the number of campsites of each type, and where known the maximum occupancy of each type. They may be named accordingly based on the type of site they are. See *Campsites Schema* in assignments.md for the expected columns.
- Directory: A directory of all families that can be used to cross reference against signups. By default, use the AVS parent directory on the web at https://portals.veracross.com/avs/parent/directory/households. It requires a login, so handle that in the Prep step below. A directory may also be supplied as a sheet or file instead, which takes precedence over the default.
- Output: A path to a sheet or some other file to place the output.


*Tips*:
- As you do your work, save your updates to the output file as it progresses. This allows tweaking and adjusting the process.
- Note: The lottery may have been run before, in which case preserve existing fields, lottery *Codes*. Fill in for families that haven't gotten through the procedure yet and you may have to re-do lottery assignments as new codes may bump families already assigned. 
  - Never regenerate a *Code* that is already present in the output: read it back and reuse it. Only generate codes for families that don't have one yet.
  - Families whose *Locked* column is set have already been notified of their assignment. Never change the *Site Type* of a locked family, and treat their site as consumed capacity before assigning anyone else. New signups can only take what is left over.
  - Report a diff at the end of a re-run: every family whose *Site Type* changed, with the old and new value, so the changes can be communicated.


*Procedure*:
Follow the procedure as follows. 
- Prep: Frontload loading and accessing the associated inputs. Inputs may be websites requiring login, so frontload that login process. This includes logging in to the web *Directory* and confirming the household listings are reachable before starting the lottery.
- Load: Load the directory, and cross reference signups against families. 
  - Bias toward exact matches and then use fuzzier matches after that for those who signed up with shortened versions of their names. 
  - Auto de-dupe where possible: automatically detect signups that belong to the same family — same directory household, same email address, or the same/other parent of an already-matched household — and collapse them to a single entry per family before running the lottery, so a family only ever gets one *Code* and one assignment. Keep the earliest submitted timestamp, merge the details, and prefer the most complete or most recent set of preferences. Note the de-duplication and any conflicting preferences in *Notes*. Only flag for manual follow-up the cases that cannot be resolved automatically.
  - Load information on the names of children, their grades, and the parent emails
  - Signups with no match in the directory are still included in the lottery, flagged in *Notes* for follow-up.
- Lottery: Run the lottery itself. The algorithm is described in a separate section below under *Lottery Algorithm*.
- Partition: Partition families into two groups, *A* - ones that specified Tent camping as their first (and/or only) preference and *B* - the rest (who preferred a cabin/glamping option).
  - Families who left their preferences blank, or whose preferences can't be interpreted, go into neither group. Leave their *Site Type* empty, flag them in *Notes* as missing preferences, and follow up with them rather than guessing a preference on their behalf.
- Assign Glamping Sites: For each family in group *B*, starting first using the *Code* assigned to each family sorted starting with highest and then lower codes. Assign site types as follows:
  - Based on the family's preferences from first to last: 
    - If that site type is a Tent type, add the family to group *A*. 
    - Else, If that site type is available and its maximum occupancy fits the family's number of attendees, assign that type to that family. Note: We are not assigning specific sites, only the site _types_. Keep track of how many sites of that type are left as you are assigning.
      - Site types are tracked by the `section` values in the Campsites sheet. Where one lodging option on the signup form maps to more than one section (e.g. two sections both holding that cabin style), keep a per-section count and fill one section before starting the next, so the *Site Type* written out is always a single section name.
    - Else, (if that site type is not available, or is too small for the party) go on to the next site type and try assigning that.
    - If you have run out of site types, the two following steps are independent and both apply: 
      - Record a cabin waitlist position in the *Cabin Waitlist* column, as CABINWAITLIST-<number>, numbering from 1 in the order families are processed. Every family that didn't win a cabin gets a position -- there is no cap on the waitlist. Do not put the waitlist position in *Site Type* -- a waitlisted family keeps their waitlist position even if they also get a tent site below, so that they can be upgraded if a cabin frees up. On a re-run, renumber waitlist positions from scratch for families that are not *Locked*.
      - Check the family's response in the signup whether they are willing to accept a tent site. If they will accept a tent add them to group *A*. Otherwise leave them unassigned to a site type.
- Assign Tent Sites: Look at families in group *A*, including those who were newly added from the step above.
 - Order group *A* by each family's own first submitted timestamp from the signup, regardless of whether they started in group *A* or were demoted from group *B*. Being demoted neither advances nor penalizes a family's place in the tent order. Where timestamps tie, break the tie by *Code*, highest first.
 - For each family starting with the sorted from first to last submitted timestamp for each family, do the following:
    - Assign them the tent `section` name from the Campsites sheet, suffixed by an incrementing number according to how many tent campers are assigned, numbering from 1 (e.g. Tent Site-1, Tent Site-2, ...).
 - The number is an ordering ticket, not a specific campsite, so do not cap it at the real number of tent sites: every family in group *A* gets one. Actual campsite placement, tent site sharing, and the tent overflow waitlist (TENTWAITLIST) are all decided later in the assignment stage described in assignments.md.

- Output: Save everything to the specified output file. Include site type assignments, and the family details including children names and their associated grades. Use the following columns for the output:
   Parent X Name, Parent X Email, Parent Y Name, Parent Y Email, Code, Site Type, Cabin Waitlist, Locked, Attendees, Signup Timestamp, Notes, Children
  - Children is a single column holding any number of children as pipe separated Name:Grade pairs, ordered youngest grade first, e.g. `Ada Siva:2|Ravi Siva:4`. This keeps the column set fixed no matter how many children a family has. Use `K` for kindergarten and `TK` for transitional kindergarten, and leave the grade empty after the colon if it is unknown, e.g. `Sam Lee:`. If a child's name contains a colon or pipe, strip it.
  - Parent names use the names as they appear in the *Directory* (Parent X = the parent who signed up, Parent Y = the other parent in the household), not the free-typed signup name — the directory is the canonical spelling and casing. When the signup name differs materially from the directory name, record the signup name in *Notes*. Signups with no directory match keep the name they signed up with.
  - Site Type holds the `section` name from the Campsites sheet (e.g. `Stumptown`, `Fish Camp`, `VWs`), not the signup form's lodging label, so it can be matched directly against campsites in the assignment stage. Tent families get the tent section name plus their ordering ticket number (e.g. `Tent Site-12`).
  - Code holds the lottery code from the *Lottery Algorithm* below and must always be written out, since re-runs depend on reading it back.
  - Attendees is the number of people in the family's party. It is carried through to the assignment stage, where it bounds how many families share a tent site.
  - Locked is empty by default and set once a family has been notified of their assignment. Leave any existing value untouched.
  - Notes carries flags raised while loading, such as de-duplicated signups, conflicting preferences, and signups with no directory match.
  - Also record the random seed used for code generation alongside the output, so a draw can be reproduced if it is disputed.

*Lottery Algorithm*:
The algorithm here describes how to generate a *Code* and is described as follows:
The lottery is based on a 24 letter code. Based on an alphabetic sort, the higher the code, the more likely a family has gotten their preferences.
- Codes are 24 characters drawn uniformly from the uppercase alphabet A-Z, and are compared with a plain case-sensitive sort.
- For each family, randomly assign a code with one caveat: Families will have indicated whether they wanted a cabin last year and didn't get one. For those, draw two codes and keep the higher of the two. That gives a boosted family a 2 in 3 chance of outranking any given unboosted family, i.e. roughly 50% better odds.
- Families listed in *Special Assignments* (e.g. paid via fundraiser for a guaranteed cabin) are set to the highest possible code (ZZZZ..., then ZZZ...Y for a second special family, and so on) so they win their first choice. The occupancy check is waived for them — a special family may plan to split between the cabin and a tent — and the reason is recorded in *Notes*. This supersedes the never-regenerate rule for their existing code.
- Using a 24 letter code should have no collisions but just in case, re-generate a new code in case there's a collision.
- Use a recorded random seed so the draw can be reproduced, and generate codes only for families that don't already have one.
