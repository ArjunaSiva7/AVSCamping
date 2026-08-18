*Description*:
This describes steps to follow to assign families to campsites. The goal here is to assign specific campsites for families

*Inputs*:
- Families: A list of families that include the family members, the children grades, the number of attendees and what site type that family was assigned to. This is the output of the lottery, so it also carries each family's *Code*, *Cabin Waitlist* position and *Locked* flag. Preserve all of those columns as-is.
- Campsites: A sheet describing the campsites available, and adjacency information on which sites are near each other. This sheet indicates the number of campsites of each type. They may be named accordingly based on the type of site they are. 
- Output: A path to a sheet or some other file to place the output. By default, use the Families input.
- Adjustments: A sheet, list of text, or a combination of tweaks that inform the assignment strategy. This is often used to override the default strategy when a specific family requests to be near another family.


*Procedure*:
- Start one by one for each family assigning them to a specific site using the *Assignment Strategy* below. 
- You will likely need to iterate, shuffle or move families around to adhere to the strategy
- You will likely run out of tent campsite space. Put left-over families on TENTWAITLIST-<number>
- Once you are done, save the result including all family details to *Output* including the specific site assignment as column "Assignment".

*Assignment Strategy*:
You'll be assigning campsites according to the following strategy:

Note: You might be operating on an output that has already had prior runs on it as this is an iterative process. Try to avoid messing with existing assignments unless you have to. Families whose *Locked* flag is set have already been notified: never move them, and treat their sites as taken before placing anyone else.

- Tent campsites can usually accommodate multiple families. Put families in the same grade together when sharing a tent campsite. Use the attendee counts to decide how many families fit: the total attendees on a tent site should stay within that site's occupancy where it is known. All non-tent campsites take only one family -- do not exceed 1 family for those.
- You will want to place families with children in the same grades together within each campsite type. E.g. Aim to put 1st graders families together.
- For families with multiple children, bias towards putting the younger children closer together unless otherwise noted by *Adjustments*. E.g. a Family with a 2nd grader and 4th grader, put them by default with the 2nd graders.
- Look at *Adjustments* for any tweaks on the strategy.
- Try to pack in families as much as possible. 
- Non-tent families were assigned based on site availability. You will likely run out of space for tent sites.
