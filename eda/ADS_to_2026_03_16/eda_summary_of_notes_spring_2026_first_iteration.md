# phase 1 eda summary of all my notes across different files
Rough file to organize my thoughts

## To include in documentation and/ orreport notebook
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
		* some of the NMF with more ngrams hints more at differe phases of the waymo, may be worht looking ito. ie, lot of parking lot and arizon then more passenger caur and waymo, gm and zoox seem to be isolated
		* for companies with a lot of entries like waymo then has some location and teh contact partener. some good stuff. sometiems what hte vehicle was doing as well "stoped, "parked"

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
	* eda\ADS_to_2026_03_16\07_eda_target_injury_2026.ipynb
		* high level what I like to do, even if not so useful here
		* different columns against the target
			* clean operating entity
				waymo around average incident rate, zoox and cruise higher, tesla a bit higher
			* intersection highest rate, a bit above street.
				work zone a bit higher but small, same with traffic circle
				higher speeds generally except not 70 + for some reason
					would want to bucke this more
			* huh SV speed doesn't seem to matter. maybe slightly but generally not moving that fast
				so fast CP hitting slow SV
			* uh not much there with weather and rodway condition
			* crash with seems to have as expected but small sample
				ie hire rate with non motorist, motorcycle, cyclist
			* pre CP crash movement has some stuff that might be interesting
				for SV seems to be making turns mainly and some others
		* model features that might be important
			important features
				passengers belted (maeks sense), pre crash movement and crash with make sense
				some after the facto fcators matter more

## To rerun in code on treated data in report notebook
    eda\ADS_to_2026_03_16\01_eda_initial_explore_2026.ipynb
        * Like half the incidents SV not moving.
        * Large % of moving incidents at a low speeds
        * contact area matching and heatmap
	eda\ADS_to_2026_03_16\02_eda_utils_validate_2026.ipynb
		* moving stopped and severity (maybe have target it it as well)

# Misc things to incorporate
* many columns with NA, partly due to hwo the data is, partly due to different versions
