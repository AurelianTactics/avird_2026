# Backlog Ideas
Unsorted, rough backlog items for potential future implementation

## List
* NLP EDA
    * classification
    * narrative data ideas
        ontology of narrative
        classification and attributes
        who classifies it and how much and why
* Using topic plus some of the NLP based tools (like BertTOpic)
* data availability by entity to see which entities share what
* narrative plus xyz fields (within ODD, driver / operator, engagement status) to see what rows shoudl be cleneed
* by entity and the % of the severity versus overall
* incidents by month by severity
* WHich source the comnplaint came from by entity could be worht following up on
* teh spacy maneuver and phrase matcher might ahve some fun things to try later
* somethign displacy for the website make sense?
    * idk if not super useful for non data scientist but maybe something similar for prhase matching based on RAG ro what not
* not super thrilled with how BERTopic came out
    * maybe mroe follow up or different tools
* better constructed target
    * seriousness uesing actual data + an LLM
    * use the pre crash movemetns for weird maneuvers
    * can revisit the other things I did
* incremental analysis as a skill when new dasta is released
    * what is new? what is interesting
* data dictionary is wrong and not noting the different versions
* Keybert / bertopic / embeddings
    * have some stretch things in the plan
    * could try different embedding models
* for dedupe of narrative might be some matching stuff that can be filtered out. Seems like some of the narrative (like a large chunk) can be carried over
* need to do incident tracking for the conclusions
* more interesting target / of interest
* treatment could be use rules, then fuzzy, then agentic for the enxt part
* parts of analysis with the cleaned and consolidated columns
* the side analysis can be done again with beter subset and with more general front, rear, side
* how to handle duplicate incident ids. Use latest? see what the data says
* treat and process which entity should be assigned to
* follow up: of the low speed / no speed how many were SV properly at low speed / no speed and how many may have caused the accident
* review EDA code with agent again
* test cases for teh EDA files
* bunch of analysis will be more interesting when a target is known so can do the ones of interest
* location data of lat, long, address not htere. maybe use the Waymo and company data if stilla vailable
* legacy features that are similar but different between versions that could be combined / treated
	weather and roadway and air bags deployed, vehicle towed, passenger belted
* misc idea: for redacted can do something dumb / silly where LLM reconstruct the text in a serious or jokey way based on the other data
* combine the two contact area and speeds to get a sense of incident
	maybe a simple animation with the narrative
* could do a one pager of incident main details
	city, state, roadway type, service, time, date, Roadway Description, weather, crash with, highest injury, property damage, CP/SV Pre-Crash Movement, air bags deployed, vehicle towed, CP/SV contact area, SV passengers or not, precrash speed, law enforcement investigating
		maybe not in data anymore: speed limit, posted speed limit 
	stretch (not in data but can be gotten): night/day, temperature
	maybe filter by the data as well
* distributions over key fields
* for website: 
    * time-of-day/region/company breakdowns
    * brainstorm more ideas
    * graphs by month
    * can subset by company or location or both
* can use data availability to get more data (ie FOIA for police report) or see what is online
* state or local permit can likely be turned into entities and then tallied. maybe web research. bit rough here
    * by hand probably simpler but maybe coudl go to agent for something to show off
    * maybe in general some of teh cleaning can be reviewed by LLM
* make a skill out of it
* data filters by string rather than drop downs maybe
* LDA and NMF topic analysis could be expanded upon (K sweeps, coherance and other metric plots, more random seeds, more hyperparam tuning)
    * way to have the agent do more of this
* maybe can do somethign with mileage. would ideally need mileage of all the vehicles to understand if any affect
* from target analysis:
    crash with other fixed object and and other see narrative might be worth reasing
    certain car or cars accounting for more rates
    contact areas and the movemetns from both
        maybe for the website
    for incident time anything in there?
    this with pre contact moving only
    have thea gent run this analysi and see waht is important
* MCP, queryable findings with dynamic results
* follow up: of the low speed / no speed how many were SV properly at low speed / no speed and how many may have caused the accident
* better context curation
    * incorporate ideas from the research into this
* better at reading findings and iterating to next part of EDA
* see what one shot agent can do
* explanation of technical terms like ODD
    Operational Design Domain (ODD) defines the specific operating conditions—such as weather, time of day, road types, and speed—under which an autonomous vehicle (AV) is designed to function safely
* make the data dictionary more friendly and render for front end / RAG
* comparison between the two data sets by grup yb /d escribe
* on hover can get the data items into the data dictionary
* db init set up and repo structure is too broad. If doing another DB then make it more clear