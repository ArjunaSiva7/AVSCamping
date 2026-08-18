*Description:*
This describes steps to follow for the AVS camping lottery for assigning campsite allocations.

*Inputs:*
- Signups: An input sheet of signups which include names of signups, their campsite preferences, first submitted timestamp, number of attendees and any other relevant details. 
- Campsites: A sheet describing the campsites available. This sheet indicates the number of campsites of each type, and where known the maximum occupancy of each type. They may be named accordingly based on the type of site they are. See *Campsites Schema* in assignments.md for the expected columns.
- Directory: A directory of all families that can be used to cross reference against signups.
- Output: A path to a sheet or some other file to place the output.


*Tips*:
- As you do your work, save your updates to the output file as it progresses. This allows tweaking and adjusting the process.
- Note: The lottery may have been run before, in which case preserve existing fields, lottery *Codes*. Fill in for families that haven't gotten through the procedure yet and you may have to re-do lottery assignments as new codes may bump families already assigned. 
  - Never regenerate a *Code* that is already present in the output: read it back and reuse it. Only generate codes for families that don't have one yet.
  - Families whose *Locked* column is set have already been notified of their assignment. Never change the *Site Type* of a locked family, and treat their site as consumed capacity before assigning anyone else. New signups can only take what is left over.
  - Report a diff at the end of a re-run: every family whose *Site Type* changed, with the old and new value, so the changes can be communicated.


*Procedure*:
Follow the procedure as follows. 
- Prep: Frontload loading and accessing the associated inputs. Inputs may be websites requiring login, so frontload that login process.
- Load: Load the directory, and cross reference signups against families. 
  - Bias toward exact matches and then use fuzzier matches after that for those who signed up with shortened versions of their names. 
  - Flag cases where a family may have signed up more than once (either the same parent, or all parents).
    - De-duplicate by default: collapse those to a single entry per family before running the lottery, so a family only ever gets one *Code* and one assignment. Keep the earliest submitted timestamp, merge the details, and prefer the most complete or most recent set of preferences. Note the de-duplication and any conflicting preferences in *Notes*.
  - Load information on the names of children, their grades, and the parent emails
  - Signups with no match in the directory are still included in the lottery, flagged in *Notes* for follow-up.
- Lottery: Run the lottery itself. The algorithm is described in a separate section below under *Lottery Algorithm*.
- Partition: Partition families into two groups, *A* - ones that specified Tent camping as their first (and/or only) preference and *B* - the rest (who preferred a cabin/glamping option).
- Assign Glamping Sites: For each family in group *B*, starting first using the *Code* assigned to each family sorted starting with highest and then lower codes. Assign site types as follows:
  - Based on the family's preferences from first to last: 
    - If that site type is a Tent type, add the family to group *A*. 
    - Else, If that site type is available and its maximum occupancy fits the family's number of attendees, assign that type to that family. Note: We are not assigning specific sites, only the site _types_. Keep track of how many sites of that type are left as you are assigning.
    - Else, (if that site type is not available, or is too small for the party) go on to the next site type and try assigning that.
    - If you have run out of site types, the two following steps are independent and both apply: 
      - Record a cabin waitlist position in the *Cabin Waitlist* column, as CABINWAITLIST-<number>, numbering from 1 in the order families are processed, for the first 20 such families. Families beyond the first 20 get no waitlist position. Do not put the waitlist position in *Site Type* -- a waitlisted family keeps their waitlist position even if they also get a tent site below, so that they can be upgraded if a cabin frees up. On a re-run, renumber waitlist positions from scratch for families that are not *Locked*.
      - Check the family's response in the signup whether they are willing to accept a tent site. If they will accept a tent add them to group *A*. Otherwise leave them unassigned to a site type.
- Assign Tent Sites: Look at families in group *A*, including those who were newly added from the step above.
 - Order group *A* by each family's own first submitted timestamp from the signup, regardless of whether they started in group *A* or were demoted from group *B*. Being demoted neither advances nor penalizes a family's place in the tent order. Where timestamps tie, break the tie by *Code*, highest first.
 - For each family starting with the sorted from first to last submitted timestamp for each family, do the following:
    - Assign them the tent site type suffixed by an incrementing number according to how many tent campers are assigned, numbering from 1 (e.g. TENT-1, TENT-2, ...).
 - The number is an ordering ticket, not a specific campsite, so do not cap it at the real number of tent sites: every family in group *A* gets one. Actual campsite placement, tent site sharing, and the tent overflow waitlist (TENTWAITLIST) are all decided later in the assignment stage described in assignments.md.

- Output: Save everything to the specified output file. Include site type assignments, and the family details including children names and their associated grades. Use the following columns for the output:
   Parent X Name, Parent X Email, Parent Y Name, Parent Y Email, Code, Site Type, Cabin Waitlist, Locked, Attendees, Signup Timestamp, Notes, Child A Name, Child A Grade, Child B Name, Child B Grade, Child C Name, Child C Grade, ...
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
- Using a 24 letter code should have no collisions but just in case, re-generate a new code in case there's a collision.
- Use a recorded random seed so the draw can be reproduced, and generate codes only for families that don't already have one.
