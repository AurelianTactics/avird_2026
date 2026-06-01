# phase 1 eda summary of all my notes across different files
Scrap file to organize my thoughts. Will be worked into non transient items

For sure
    * treatment steps
        * columns that need treatment
        * duplicate incidents
            * rate of incidents with 2 or more incident ids (possible dupes) 0.42596153846153845 1329 3120
        * different columns accross time, some columns not there, some similar but recorded differently
        * entity two down into one, many text issues
            * seems like generally use the Operating Entity but this should be treated and made into an overall entity that can be assigned to
        * fuzzy cleaning generally worked

    * many interesting things redacted
        * some narratives, all tesla, like a bunch of location and other useful infor

	* mention the highe level for each notebook (have AI summarize)

	* eda\ADS_to_2026_03_16\03_eda_basic_topics_2026.ipynb
		*some of the NMF with more ngrams hints more at differe phases of the waymo, may be worht looking ito. ie, lot of parking lot and arizon then more passenger caur and waymo, gm and zoox seem to be isolated

	* eda\ADS_to_2026_03_16\04_eda_target_exploration.ipynb
		* the process and ideas, the future things
		* the describe of what was found and the means and the logic behind what was chosen
		* Precrash movement notes:
			could add a possible targets based on some of the more dangerous ones like U turna nd causing an accident. will backlog for now
			I think there's some interesting stuff here worth putting on tehn websiest
			heatmap for this
	* eda\ADS_to_2026_03_16\05_eda_spacy_2026.ipynb
		* what i did
		* Rule-based matching: `Matcher` + `PhraseMatcher` has an intersting table
	* eda\ADS_to_2026_03_16\06_eda_target_injury_2026 copy.ipynb
		* high level what I like to do, even if not so useful here

Follow up with treated
    eda\ADS_to_2026_03_16\01_eda_initial_explore_2026.ipynb
        * Like half the incidents SV not moving.
        * Large % of moving incidents at a low speeds
        * contact area matching and heatmap
	eda\ADS_to_2026_03_16\02_eda_utils_validate_2026.ipynb
		* moving stopped and severity (maybe have target it it as well)


Misc
* many columns with NA, partly due to hwo the data is, partly due to different versions


# Unsorted
eda\ADS_to_2026_03_16\01_eda_initial_explore_2026.ipynb

'''
Value counts notes
table by entity and by time
Make and model can be consolidated: some duplicate options
can add things like ODD and definitions
maybe can do somethign with mileage. would ideally need mileage of all the vehicles to understand if any affect
Driver / Operator Type: probalby need to filter by something ueful
ADAS/ADS System Version/ADAS/ADS Hardware Version/ADAS/ADS Software Version: see who the redatcted belongs to
State or Local Permit: can likely be cleaned up, many dupes for near things, even a simple string treatment

Operating Entity: can be cleaned up, paroticularly if the gourpoing
	to do: figure which entity to group on

WHich source the comnplaint came from by entity could be worht following up on
Incident Date: by month count could be a simple chart
Incident time: do a chart / diagram of this to see if anyhing interesting
	maybe by night and dark as well
same incident id: see how many duplicates

ug location data of lat, long, address not htere. maybe use the Waymo and company data if stilla vailable

City and state could be some simple plots. see if can AI code something more dynamic for the front end too

could do a one pager of incident main details
	city, state, roadway type, service, time, date, Roadway Description, weather, crash with, highest injury, property damage, CP/SV Pre-Crash Movement, air bags deployed, vehicle towed, CP/SV contact area, SV passengers or not, precrash speed, law enforcement investigating
		maybe not in data anymore: speed limit, posted speed limit 
	stretch (not in data but can be gotten): night/day, temperature
	maybe filter by the data as well

potential target
	highest injury
	SV Pre-Crash Movement
	property damage
	air bag deployed
	was towed
	pre crash speed
	law enforcement investigating
	within ODD

misc idea: for redacted can do something dumb / silly where LLM reconstruct the text in a serious or jokey way based on the other data

combine the two contact area and speeds to get a sense of incident
	maybe a simple animation with the narrative

data availability: maybe quick summary
	maybe a stretch thing of where to get more (ie if a plicy report is available)
		investigating agency too

narrative data ideas
	ontology of narrative
	classification and attributes
	who classifies it and how much and why

investigating agency can be cleaned up to consolidate duplicates

legacy features that are similar but different between versions that could be combined / treated
	weather and roadway and air bags deployed, vehicle towed, passenger belted

* Like half the incidents SV not moving.
* Large % of moving incidents at a low speeds
* follow up: of the low speed / no speed how many were SV properly at low speed / no speed and how many may have caused the accident
'''

* Driver type: not worth using a filter for a target. maybe for user purposes but autonomous mode seems to be on or part of the incideent in man ycases
* engagemetns tatus: nto many verified not engaged, keep using

### Notes
* so dropping by duplicate incident id doesn't necessarily make sesne for the ' '. seems different by Incident Date and INicident time shoudl be fine
* so with same incident ID, then get the latest report. could optionally fill in the NA's from teh old one
    * soem seem to have fill NA, some don't
* need to keep all the narrative stuff
    * so treatment steps are
* I think the logic is:
    * if " " or null 'Same Incident ID' treat as different unless 'Reporting Entity', 'Incident Date', 'Incident Time (24:00)' and 'VIN'are all the same (all should pass based on how I spot checked the data)
    * if the same 'Same Incident ID', then use the latest report date and 'Report Submission Date', 'Report ID', Report Version',
        * keep the latest report. then fill NA from earlier if any using the next most recent. For 'Narrative' append and keep all (unless narrative matches exactly an earlier narrative) in a new 'Narrative - Same Incident ID'
            * have some sort of seperator maybe for the combined narratives.
        * will want a function for this


eda\ADS_to_2026_03_16\03_eda_basic_topics_2026.ipynb

* sklearn lda: decent topics, matches with the entities at least
* sklearn nmf: seems to get the redacted more concisely but waymo spread out a bunch
* 

eda\ADS_to_2026_03_16\04_eda_narrative_embeddings_2026.ipynb
* keybert
    about what you would expect, lot of waymo and historical data. nothing really too unusual there. more what is in the data overall

### notes
* generally pretty good. company specific generally, some catdch alls for redacted or filed an ew incidcent
* for companies with a lot of entries like waymo then has some location and teh contact partener. some good stuff. sometiems what hte vehicle was doing as well "stoped, "parked"


eda\ADS_to_2026_03_16\04_eda_target_exploration.ipynb

ideas for target with this


1. 'No Injury Reported':
From 'Highest Injury Severity Alleged'. Is 1 if in ['No Injuries Reported', 'Property Damage. No Injured Reported'] else 0

2. Injury reported
0 by default. 1 if in this list 'Minor' 'Minor W/ Hospitalization', 'Moderate', 'Moderate W/ Hospitalization', 'Fatality', 'Serious', 'Moderate W/O Hospitalization'

3. Multi class injury
0 by default. 1 if Minor or the related, 2 if moderate or related, 3 if serious, 4 if fatality

4. 'Binary Airbag Deployed'
Has to be gotten from multiple columns. If a yes in any of these three columns then 1. Else 0.
'Any Air Bags Deployed?'
CP Any Air Bags Deployed?
SV Any Air Bags Deployed?


5. 'Binary Vehicle Towed'
Has to be gotten from multiple columns. If yes in any of these then 1, else 0
Was Any Vehicle Towed?
CP Was Vehicle Towed?

6. 'SV Speed >= x'
Let x default to 10 MPH. Use column SV Precrash Speed (MPH). If >= x then , else 0

7. 'Potential Non-Trivial Accident'

If targets 2 through 6 are equal to 1 then 1. Else 0. ALso if 'Crash With' column is 'Non-Motorist: Pedestrian' then also 1.


Targets analysis
Most are fine. i think the injury is the more important one
the towed is not superuseful I think. seems to happen a lot
speed one could probably rely on a better source. I think 10 MPH or 15 or 20 MPH would be fine

eda\ADS_to_2026_03_16\05_eda_spacy_2026.ipynb
* dang the person stuff is way off
* cross tab is useful, maybe something to add to the website


eda\ADS_to_2026_03_16\07_eda_target_injury_2026.ipynb
'''
Human rough notes

notes on target EDA
by reporting entity, waymo seems to have smaller positive rate, Zoox and Cruise higher. TEsla slightly higher
monthly reports have the lowest rate. guess other oens are update dmore frequently due to severity
	clean operating entity
		waymo around average, zoox and cruise higher, tesla a bit higher

month relative stable, maybe more in nov or dec. higher rate in 2022 and 2023, maybe from cruise?

intersection highest rate, a bit above street.
work zone a bit higher but small, same with traffic circle
higher speeds generally except not 70 + for some reason
	would want to bucke this more

huh not much there with weather

crash with seems to have as expected but small sample
	ie hire rate with non motorist, motorcycle, cyclist

pre CP crash movement has some stuff that might be interesting
	for SV seems to be making turns mainly and some others
hardly any CP airbags or towing, but htis data is largely old only
	new one seems to have higher accident rates with the airbags going off which maeks esne
	twoed as well

huh SV speed doesn't seem to matter. maybe slightly but generally not moving that fast
	so fast CP hitting slow SV

law enforcement investigating hire but still only 20%

not much tghere with the roadway condition




Univariate
not much tehre. mabye posted speed limit
maybe incicednt time 

LGBM gets something decent
	can see some stuff ther but not clear why soem of the features are important

LR
	some of the crash with makes sense and the not bellted un clear why some of the others re important

important features
	passengers belted (maeks sense), pre crash movement and crash with make sense
	some after the facto fcators matter more


backlog:
crash with other fixed object and and other see narrative might be worth reasing
certain car or cars accounting for more rates
contact areas and the movemetns from both
	maybe for the website
for incident time anything in there?
this with pre contact moving only
have thea gent run this analysi and see waht is important

'''