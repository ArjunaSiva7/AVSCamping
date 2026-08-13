*Description*:
This describes steps to follow to assignee families to campsites. The goal here is to assign specific campsites for families

*Inputs*:
- Families: A list of families that include the family members, the children grades and what site type that family was assigned to. 
- Campsites: A sheet describing the campsites available, and adjancency information on which sites are near eachother. This sheet indicates the number of campsites of each type. They may be named accordingly based on the type of site they are. 
- Output: A path to a sheet or some other file to place the output. By default, use the Families input.
- Adjustments: A sheet, list of text, or a combination of tweaks that inform the assignment strategy. This is often used to override the default strategy when a specific family requests to be another family.


*Procedure*:
- Start one by one for each family assigning them to a specific site using the *Assignment Strategy* below. 
- You will likely need to iterate, shuffle or move families around to adhere to the strategy
- You will likey run out of tent campsite space. Put left-over families on TENTWAITLIST-<number>
- Once you are done, save the result including all family details to *Output* including the specific site assignment as column "Assignment".

*Assignment Strategy*:
You'll be assigning campsites according to the following strategy:

Note: You might be operating on an output that has already had prior runs on it as this is an iterative process. Try to avoid messing with existing assignments unless you have to.

- Tent campsites can usually accommodate multiple families. Put families in the same grade together when sharing a tent campsite. All non-tent campsites take only one family -- do not exceed 1 family for those.
- You will want to place families with children in the same grades together within each campsite type. E.g. Aim to put 1st graders families together.
- For families with multiple children, bias towards putting the younger children closer together unless otherwise noted by *Adjustments*. E.g. a Family with a 2nd grader and 4th grader, put them by default with the 2nd graders.
- Look at *Adjustments* for any tweaks on the strategy.
- Try to pack in families as much as possible. 
- Non-tent families were assigned based on site availability. You will likely run out of space for tent sites.
