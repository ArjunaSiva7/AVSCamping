*Description:*
This describes steps to follow for the AVS camping lottery for assigning campsite allocations.

*Inputs:*
- Signups: An input sheet of signups which include names of signups, their campsite preferences, first submitted timestamp and any other relevant details. 
- Campsites: A sheet describing the campsites available. This sheet indicates the number of campsites of each type. They may be named accordingly based on the type of site they are. 
- Directory: A directory of all families that can be used to cross reference agaisnt signups.
- Output: A path to a sheet or some other file to place the output.


*Tips*:
- As you do your work, save your updates to the output file as it progresses. This allows tweaking and adjusting the process.
- Note: The lottery may have been run before, in which case preserve existing fields and lottery assignments and fill in for families that haven't gotten through the procedure yet. 


*Procedure*:
Follow the procedure as follows. 
- Prep: Frontload loading and accessing the associated inputs. Inputs may be websites requiring login, so frontload that login process.
- Load Load the directory, and cross reference signups against families. 
  - Bias toward exact matches and then use fuzzier matches after that for those who signed up with shortened versions of their names. 
  - Flag cases where a family may have signed up more than once (either the same parent, or all parents).
  - Load information on the names of children, their grades, and the parent emails
- Lottery: Run the lottery itself. The algorithm is described in a separate section below under *Lottery Algorithm*.
- Partition: Partition families into two groups, *A* - ones that specified Tent camping as their first (and/or only) preference and *B* - the rest (who preferred a cabin/glamping option).
- Assign Glamping Sites: For each family in group *B*, starting first using the *Code* assigned to each family sorted starting with highest and then lower codes. Assign site types as follows:
  - Based on the family's preferences from first to last: 
    - If that site type is a Tent type, add the family to group *A*. 
    - Else, If that site type is available, assign that type to that family. Note: We are not assigning specific sites, only the site _types_. Keep track of how many sites of that type are left as you are assigning.
    - Else, (if that site type is not available) go on to the next site type and try assigning that.
    - If you have run out of site types: 
      - For the first 20 families, add them to a special site type, WAITLIST.
      - Check the family's response in the signup whether they are willing to accept a tent site. If they will accept a tent add them to group *A*. Otherwise leave the unassigned to a site type.
- Assign Tent Sites: Look at families in group *A*, including those who were newly added from the step above.
 - For each family starting with the sorted from first to last submitted timestamp for each family, do the following:
    - Assign them the tent site type suffixed by an incrementing number according to how many tent campers are assigned.

- Output: Save everything to the speciifed output file. Include site type assignments, and the family details including children names and their associated grades. Use the following columns for the output:
   Parent X Name, Parent X Email, Parent Y Name, Parent Y Email, Site Type, Signup Timestamp, Child A Name, Child A Grade, Child B Name, Child B Grade, Child C Name, Child C Grade, ...

*Lottery Algorithm*:
The algorithm here describes how to generate a *Code* and is described as follows:
The lottery is based on a 24 letter code. Based on an alphabetic sort, the higher the code, the more likely a family has gotten their preferences.
- For each family, randomly assign a 24 letter code with one cavaet: Families will have indicated whether they wanted a cabin last year and didn't get one. For those, give them a 50% higher likelihood to have a higher code. Use your judgement on how to make that work mathematically.
- Using a 24 digit should have no collisions but just in case, re-generate a new code in case there's a collision.
