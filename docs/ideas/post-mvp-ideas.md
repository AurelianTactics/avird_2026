# to fix
* DONE change the about page
* DONE change the avird-2026 title page
Let's make some fixes
Add a MIT license to the repo and copywrite the webpage.
Is this really designed by the claude code plugin frontend design?
The incident date is not sorted correctly. Showing Sept 2025 instead of March2026 as teh latest incident
The group by query is wrong. There are no property damage incidents despite there being some in the data. Look at the value counts for the raw data and make sure you are capturing the correct values under "Highest Injury Severity Alleged".
Let's add the report ID to the main landing table and have that be the link to the incidents.
On the incident pages let's link to the same incidents but other reports. Move the narrative to the top as well
* DONE add a license MIT License
* DONE this really the claude front end
* DONE incident date not sorted correctly, have some sort of id
* DONE really no property damage incidents




# Post MVP Ideas
- replan on what you want to accomplish here and re-prioritize
    * thinking W5 here
        * see if can do a text box so can filter the data down in certain ways. shows query. probably preferable to the
    * then W6
    * then maybe a break
- review old brainstorm, backlog, and other ideas

## More Website ideas
- can play with the data page
    - ie put in a filter and see the different results
- RAG
- can talk to the data

## other ideas
- MCP
- DONE more eda / ontology
    - maybe that ontology package
- get more data

## Rough working 6/10/26
* DONE verification loop work
    * DONE verify the outputs
        * DONE verify the webpages
    * DONE review the commits
    * DONE review the skills, hooks tools
    * DONE can it actuall run the loop and hooks without my approval?
* DONE Ask
    * did the website really use the claude tool for frontend design?
    * explain the interplay between the implemented hooks, tools, and skills
* DONE deploy phase 1 and 2 to prd
* DONE fix the about page wording
* check where ruff linter hook is
* the other website MVP brainstorm ideas up to W6
* likely then RAG / talk with data plan next
    * can start the planning on this whenever
* replan from there