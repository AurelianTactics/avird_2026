# working
* W5 branch
    * DONE prompt below for the plan
 /compound-engineering:ce-plan Let's make a plan to do W5 from
  docs\brainstorms\2026-06-05-website-mvp-requirements.md . I was thinking get those visual views and pre crash
  movement redacted stats from the main treated data.

  Let's have that be the first part of the plan. The second part of the plan I was picturing a text box that would
  allow you to do simple queries like 'Only waymo vehicles in Arizona' and regenerate the plots.

    * DONE review the plan
    * LATER agent review of the plan
    * DONE review the heatmap output
        * DONE review the pages
        * DONE rename the groupings page. Call it like AV Company Stats
        * “only Waymo vehicles in Arizona” does not work
            * see what it shows, maybe filter by that
            * ug, removed LLM call now just deterministic nonsense
        * DONE open on the front / side rear
        * DONE the CP / SV should be larger and not abbreviations and explain what they mean
        * DONE the pre crash movements maybe larger grouping
            * for the full thing maybe have other? there are too many low value ones and I can't read the CP columns correctly
            * ... on the columns is not helpful, cant see
            * try to organize them a bit better maybe not sure what the ordering is
        * DONE can I do an image that when you over over the heatmap thing shows what parts collided into each other
        * DONE what about an animation for the maneuvers. maybe on a hover over or a click
    * more fixes
        * TEST if I was going to show the %, how would taht work? count's are nice but % might be nice too but % of what? Overall incidents by that SV or CP I think. could do overall % or by row or column but that might be misleading. Could I show the count and the (%) with no decimals?
        * I think I need more of an explanation of what the text box on the heatmap pages does. Both to me in chat and on the webpage. Some other things related to this:
            * I'm concerned about the decision for if the LLM part does not work not to go back to default but to go to some sort of deterministic or text matching logic. I think that may make sense in a real application but here I'm trying to learn the LLM and langgraph part. I know I can do rules based things.
            * it is fine if the text part does not work. If the LLM is down or there is an issue, that is fine. Feel free to print a concise error message along with the default. The only rule based fallback I want is just to show the default
            * What are the filter options? I think the system prompt says there are only 3 options? That is fine if that's the case just want it to be explicit.

    * review the text to SQL part
        * discuss why certain things where chosen versus an out of the box tool
        * For the heatmap code I want to understand the process of going from text to filtering. I especially want to understand the part that Langgraph does.
    * confirm the cost and limiting
* DONE LLM judge / argument
    * RUNNING on step where instantiated DB and verify
    * DONE next would be the run in browser and see=
    * then review
        * LATER CE review
        * DONE my code review
            * DONE fault analysis
                * bunch of improvement ideas added to backlog
            * online tool
        * REVIEW UI review review
            * thinking tabs maybe then spreading down. at the least not at the top. then each tabl could have an explanation
            * important info carries over at the top like the narrative
* confirm limiting and cost
    * heatmap
    * DONE llm judge
        * SEE NOTES FOR IDEAS
* merge in
    * heatmap
    * TEST LLM judge
        * ERROR DEBUG HERE
* agent review of LLM judge / argument and the heatmap;



# Post MVP Ideas
* using the ontology work with a graphDB and RAG maybe
    * DONE get a better sense of how they are combined
    * DONE HIGH LEVEL IDEAS: RAG embeddings versus asking the graph and that chain of things
        * exact SQL, agent from a template, agent skills, agent builds etc
    * see conversation with claude on this
        * text to SQL, (W5 should have this)
        * plain RAG over narratives, embed then retreival
            * small set for evaluation for stages 1 and 2 maybe
        * knowledge graph queries (would need the ontology instantied and the DB)
        * route across agents for which to select
        * hybrid / graph RAG and agentic orchestration
        * Prompt:
            * I want to learn more about database options and agentic integration. Let's make a plan. I'm not saying we will do all parts of these plans but I want to see the progression if I was going to implement it. I'm interested in what validations, prompts, context building, agentic self validation loops, and 'golden datasets' I would need to do for each part.
                * Text to SQL: Sort of accomplished maybe in the heatmap page. Is this enough for the basics or should I expand? Existing is more like text to bound parts of a SQL query. I wouldn't mind learning this a bit better with a real example. Maybe make it more open ended and be able to query any part of the treated table?
                * Plan RAG over narratives, embed then retrieval.
                * Knowledge graph queries on the ontology data.
                * route across agents for which of the above and below options to select
                * Hybrid graph / RAG and agentic orchestration.

- replan on what you want to accomplish here and re-prioritize
    * IN PROGRESS thinking W5 here
        * see if can do a text box so can filter the data down in certain ways. shows query. probably preferable to the
    * IN PROGRESS the LLM as a judge ideas
        * who is at fault
        * the argument
        * revisit the old code
    * W3 and W4: maybe re modify
    * then W6
    * then maybe a break
* maybe pull in the waymo data from the waymo data hub?
    * the API info from the map at least or maybe some other stuff
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

# done

- DONE finish up ontology work
    - something to visualize
        - DONE view the results
        - results are good but not using the website for some reason, redo
    - a write up of the strengths and weaknesses
        - write this up
    * agent review of the work

