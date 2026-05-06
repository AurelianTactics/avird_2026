# EDA To Do
Potential follow up EDA items to do

## Initial Explore
* eda\ADS_to_2026_03_16\01_eda_initial_explore_2026.ipynb

### Should be simple then can react

* distributions over key fields
* time-of-day/region/company breakdowns
    * brainstorm more ideas
* what can be treated, maybe try some simple treatment ideas based on value counts
    * Make and model can be consolidated: some duplicate options
    * State or Local Permit: can likely be cleaned up, many dupes for near things, even a simple string treatment
    * Operating Entity: can be cleaned up, paroticularly if the gourpoing
    * see if this can be given to AI for one off function or flexible function to run on updates
    * investigating agency can be cleaned up to consolidate duplicates
    * state
* if vehicle stopped or not and analysis
* graphs by month
    * can subset by company or location or both
* ADAS/ADS System Version/ADAS/ADS Hardware Version/ADAS/ADS Software Version: see who the redatcted belongs to
* WHich source the comnplaint came from by entity could be worht following up on
* same incident id: see how many duplicates
* combine the two contact area and speeds to get a sense of incident
	maybe a simple animation with the narrative
    * contact area analysis (match AV and other)
    * subset by type
    * VALIDATE THIS code seems odd on it. don't think it's matching
        * yeah this is wrong
    * contact as % against each other should be more in depth
    * way to do contact and who was moving and what not, might be able to do more with that
* data availability field: maybe quick summary
	maybe a stretch thing of where to get more (ie if a plicy report is available)
		investigating agency too
* by entity and the % of the severity versus overall
* incidents by month by severity
* injury severity and passenger versus CP person / pedestrian
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

### Target related
* make my own target(s)
    * of severity / interest
    * certain drivers
    * subset by interesting fields versus a target
* potential target
	highest injury
	SV Pre-Crash Movement
	property damage
	air bag deployed
	was towed
	pre crash speed
	law enforcement investigating
	within ODD

### Explore the data a bit more
* figure which entity to group on
* dig more into the driver column and what it means and how it can be used for a target
    * Driver / Operator Type: probalby need to filter by something ueful
    * maybe better to use the Automation System Engaged rather then rely on this? or at least try to match them up to see if it makes sense
* can add things like ODD and definitions
* maybe can do somethign with mileage. would ideally need mileage of all the vehicles to understand if any affect

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

# when done
* see what from EDA and the backlog would be interesting for something more formalized on the site
* make a file for a decent ish report
    

# Backlog
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

