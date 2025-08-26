# fetch_ratings

`fetch_ratings.py` is a utility script that analyzes an llm generated csv based on the `main.py` results in `saved_places.json`.

It parses the csv, feeds the metadata to the SerpApi python sdk, then ranks the results by stars and number of reviews.

For example, this is the top 3 results with a header row:

```text
id,name,address,latitude,longitude,saved_date,region,country_code,google_maps_url
saved_063,Palace Theatre,"160 W 47th St, New York, NY 10036, United States",40.7588363,-73.9840424,2025-01-04T01:51:05+00:00,New York,US,http://maps.google.com/?cid=3167862741085097019
saved_280,Tabata Ramen,"1435 2nd Ave, New York, NY 10021, United States",40.7706692,-73.9572646,2022-07-11T17:41:40+00:00,New York,US,http://maps.google.com/?cid=1791102614726687178
saved_283,Bea,"403 W 43rd St, New York, NY 10036, United States",40.7594201,-73.9924645,2022-07-10T23:47:41+00:00,New York,US,http://maps.google.com/?cid=15755615194939967845
```

becomes

```json
{
  "timestamp": "2025-08-26T17:32:50.021341+00:00",
  "total_places": 62,
  "successful_fetches": 62,
  "results": [
    {
      "place_name": "Radio City Music Hall",
      "rating": 4.8,
      "reviews": 25106,
      "google_maps_url": "https://www.google.com/maps/search/Radio+City+Music+Hall/@40.759976,-73.9799772,15.1z?hl=en"
    },
    {
      "place_name": "Strand Book Store",
      "rating": 4.8,
      "reviews": 15830,
      "price": "$$",
      "google_maps_url": "https://www.google.com/maps/search/Strand+Book+Store/@40.7332515,-73.9909532,15.1z?hl=en"
    },
    // ...
  ]
}
```

## Setup

* Install the prereqs mentioned in the primary [README.md](../README.md)
* Run the `main.py` per the same instructions
* Create an account on SerpApi and copy the private key into an `.env` file (cf. [.env.example](../.env.example))

## Quickstart

After [setting up](#setup), asking Claude et al to summarize a location (e.g., NY, NY), run:

```bash
uv run ./scripts/fetch_ratings.py
```

Results are stored in `results/` as `ratings_yyyymmdd.json`.
