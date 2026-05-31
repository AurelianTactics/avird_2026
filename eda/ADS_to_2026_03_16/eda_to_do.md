# EDA To Do
Potential follow up EDA items to do

## Initial Explore
* eda\ADS_to_2026_03_16\01_eda_initial_explore_2026.ipynb

### Should be simple then can iterate

* DONE if vehicle stopped or not and analysis
* DONE ADAS/ADS System Version/ADAS/ADS Hardware Version/ADAS/ADS Software Version: see who the redatcted belongs to
* DONE same incident id: see how many duplicates
* DONE data availability field: maybe quick summary
	maybe a stretch thing of where to get more (ie if a plicy report is available)
		investigating agency too
* DONE Incident Date: by month count could be a simple chart
* DONE word cloud
* DONE Incident time: do a chart / diagram of this to see if anyhing interesting
	maybe by night and dark as well
    hard to tell if anythig interesting by time of day without knowing more of when miles doen and road usage
* DONE table by entity and by time
* DONE incidents by month
* DONE table by entity
* DONE City and state could be some simple plots. see if can AI code something more dynamic for the front end too
* DONE other potential text fields that could benefit from what is being done with 'Narrative' field
* DONE SEE BRAINSTORM what else can be done with narrative
* DONE SEE BRAINSTORM other simple text things
    * research and more ideas

### incident duplication results
* DONE incident duplicate ides
    * if " " or null incident Id treat as different unless entity, incident date, time and vin are all the same (all should pass)
    * if the same one, then use the latest report date and report submission date, report id, report version DESC
        * keep the first (ie the latest). then fill NA from earlier. FOr narrative append and keep all (unless narrative matches exactly an earlier narrative).
            * have some sort of seperator maybe for these?
        * will want a function for this
    * working on a function, check the results

### Target related
* DONE make my own target(s)
    * DONE do the entity, other treatement, and the incident duplicates
        * can do the below and then think how I want to do my first report
    * DONE explore the data and then see which of these can be made into a binary 1/0 or multi class
        * Highest Injury Severity Alleged
        * SV moving at a speed
            * try a bucket
        * Crash With: Non-Motorist: Pedestrian
        * Any Air Bags Deployed?
        * Was Vehicle Towed?
        * BACKLOG of severity / interest
    * DONE combination of the above maybe: injury severity and passenger versus CP person / pedestrian. I think this needs multiple columns:
        * Highest Injury Severity Alleged, 'Crash With' (and related to tell if Crash partner was a vehicle or person), 'Narrative', 'SV Were All Passengers Belted?',  'CP Any Air Bags Deployed?',  'SV Any Air Bags Deployed?',
    * DONE see results for the pre crash movements, maybe add some of hte ocmbinations to the target
    * DONE making some functions, review and see the results
        * look over the code, maybe make the serious one a bit tighter. seems to flag a bit

* DONE then when the target created, try some basic EDA to see which things may be useful
    * DONE decide which targets to keep
        * Injury Reported,	SV Speed >= 15
    * DONE make the plan with the below
    * DONE against target (displays, percents), univariate (AUC, KS, mutual information, chi2, overall score, correlation), quick RF / LR / lightbm test (with SHAP), maybe interactions (heatmap & 2 stub tree), brainstowrm some more
    * DONE goal here would be more a useful script and easy readout rather than a notebook maybe
        * maybe broken up into multiple things, I think I have a good enough feel on these to make this more reproducible
    * DONE plan
    * DONE work
    * DONE ce review
        * docs/reviews/2026-05-25-code-review-injury-target.md
    * my review
        * hundreds of artifacts, even the fucking value counts. this needs to be done better
            prompt:
            This is unwieldy. For some reasons there are hundreds of artifacts. Even the value counts and describe across hundres of files. Maybe parts of this should be a notebook? The benefit to an artifact from a .py file is it is easy to run and reproduce but if it loses to much usability and eligibility then it's not worth doing as a .py file and can do as a .ipynb file.
    * findings
* DONE filtering options
    * remove duplicate incidents, leave the last
        * to do: look int o those
    * DONE made code for one entity
    * DONE 'Driver / Operator Type': user can filter but I shoudl cinlude them all
    * DONE 'Engagement Status' very few not engaged, not worth filtering
    * DONE within ODD: very few non yes and still might be worth including. keep them in
* DONE potential target
	highest injury
	SV Pre-Crash Movement
	property damage
	air bag deployed
	was towed
	pre crash speed
	law enforcement investigating
    ODD




### Explore the data a bit more
* DONE BOTH figure which entity to group on
* DONE do the entity, other treatement, and the incident duplicates
    * can do the below and then think how I want to do my first report
* DONE dig more into the driver column and what it means and how it can be used for a target
    * Driver / Operator Type: probalby need to filter by something ueful
    * maybe better to use the Automation System Engaged rather then rely on this? or at least try to match them up to see if it makes sense
* DONE can add things like ODD and definitions
* DONE CAN ADD TO WEBSITE heatmap for CP and SV pre crash movements
    * maybe relate to the contact areas stuff as well
    * CP Pre-Crash Movement
    * SV Pre-Crash Movement
* DONE who is redacting the narrative by main entity


## try with an LLM
* DONE what can be treated, maybe try some simple treatment ideas based on value counts
    * Make and model can be consolidated: some duplicate options
    * State or Local Permit: can likely be cleaned up, many dupes for near things, even a simple string treatment
    * Operating Entity: can be cleaned up, paroticularly if the gourpoing
    * see if this can be given to AI for one off function or flexible function to run on updates
    * investigating agency can be cleaned up to consolidate duplicates
    * state
* DONE combine the two contact area and speeds to get a sense of incident
	maybe a simple animation with the narrative
    * contact area analysis (match AV and other)
    * subset by type
    * VALIDATE THIS code seems odd on it. don't think it's matching
        * yeah this is wrong
    * contact as % against each other should be more in depth
    * way to do contact and who was moving and what not, might be able to do more with that

* DONE see if can create some fun topics


## treatment follow up
* DONE make an overall entity
* DONE lot of duplicate entity id
* DONE see how the fuzzy treatment options dis

## NLP EDA To Do
* DONE LDA: count vectorizer, understand the args
* DONE NMF: tf-idf understand the args
* DONE spaCy capability tour (linguistic features, NER, Matcher/PhraseMatcher, displaCy, similarity)
    * eda/eda_utils_spacy.py + eda/ADS_to_2026_03_16/05_eda_spacy_2026.ipynb
    * artifacts under eda/ADS_to_2026_03_16/artifacts_spacy/
* DONE keybert
    * backlog: should be cached better with the embedding on this
* DONE other topic ways
    * bertopic
* DONE make embeddings and project into lower space
* DONE spacy
* classification
* narrative data ideas
	ontology of narrative
	classification and attributes
	who classifies it and how much and why


## Improve Agent context
* Plan out how to give the agent better context
    * data\nhtsa\SGO-2021-01_Data_Element_Definitions.pdf to a more usable format
    * column names to a usable directory with progressive disclosure
    * basic findings to a usable directory with progressive disclosure
* how to update CLAUDE.MD so the EDA context can be expanded
* research some best practies

# when done
* see what from EDA and the backlog would be interesting for something more formalized on the site
* make a file for a decent ish report
    * look through all your notes in notebooks and elsewhere
    
# Website
* can look at all incidents but also need to group them
* thinking maybe basic graphs and then for the website a dropdown of key things or scrollable and the user can select which type of incidents to have at the top
* heatmap of the contact areas with options
    * first is side, rear, front
    * then by contact areas
* the cleaned version of the data
    * some ideas here: eda\ADS_to_2026_03_16\01_eda_initial_explore_2026.ipynb
* maybe dynamic stuff like heatmap et all based on the user filters (maybe in a text box)
* heatmap (or maybe more intersting) of the pre crash movements
* not quite tehre but maybe the spacy crosstab by org and the entity types can be interesting tos ee what is going on
* eda_utils_spacy.build_maneuver_matcher might be something fun for the website
* redacted narratives. seems like Tesla only one recent and active
    * show the percent and count by entity, maybe recently as well too


# Backlog
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

# Learnings
* lot of interesting python packages for fuzzy matching / data clearning
