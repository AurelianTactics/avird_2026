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
* if " " or null incident Id treat as different unless entity, incident date, time and vin are all the same (all should pass)
* if the same one, then use the latest report date and report submission date, report id, report version DESC
    * keep the first (ie the latest). then fill NA from earlier. FOr narrative append and keep all (unless narrative matches exactly an earlier narrative).
        * have some sort of seperator maybe for these?
    * will want a function for this
* working on a function, check the results

### Target related
* DONE filtering options
    * remove duplicate incidents, leave the last
        * to do: look int o those
    * DONE made code for one entity
    * DONE 'Driver / Operator Type': user can filter but I shoudl cinlude them all
    * DONE 'Engagement Status' very few not engaged, not worth filtering
    * DONE within ODD: very few non yes and still might be worth including. keep them in
* make my own target(s)
    * do the entity, other treatement, and the incident duplicates
        * can do the below and then think how I want to do my first report
    * of severity / interest
    * Highest Injury Severity Alleged
    * SV moving at a speed
    * Crash With: Non-Motorist: Pedestrian
    * Any Air Bags Deployed?
    * Was Vehicle Towed?
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
* do the entity, other treatement, and the incident duplicates
    * can do the below and then think how I want to do my first report
* dig more into the driver column and what it means and how it can be used for a target
    * Driver / Operator Type: probalby need to filter by something ueful
    * maybe better to use the Automation System Engaged rather then rely on this? or at least try to match them up to see if it makes sense
* can add things like ODD and definitions
* maybe can do somethign with mileage. would ideally need mileage of all the vehicles to understand if any affect
* heatmap for CP and SV pre crash movements
    * maybe relate to the contact areas stuff as well
* who is redacting the narrative by main entity

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
* by entity and the % of the severity versus overall
* incidents by month by severity
* WHich source the comnplaint came from by entity could be worht following up on
* data availability by entity to see which entities share what
* narrative plus xyz fields (within ODD, driver / operator, engagement status) to see what rows shoudl be cleneed
* see if can create some fun topics

## treatment follow up
* make an overall entity
* lot of duplicate entity id
* see how the fuzzy treatment options dis

## NLP EDA To Do
* see list of things to try in my brainstorm
* LDA
* other topic ways
* classification
* narrative data ideas
	ontology of narrative
	classification and attributes
	who classifies it and how much and why
    make embeddings and project into lower space
* injury severity and passenger versus CP person / pedestrian. I think this needs multiple columns:
    * Highest Injury Severity Alleged, 'Crash With' (and related to tell if Crash partner was a vehicle or person), 'Narrative', 'SV Were All Passengers Belted?',  'CP Any Air Bags Deployed?',  'SV Any Air Bags Deployed?',

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



# Backlog
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


# Learnings
* lot of interesting python packages for fuzzy matching / data clearning
