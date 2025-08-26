#!/usr/bin/env python

import json
import os
import pandas as pd
import serpapi
import time
from datetime import UTC, datetime
from decouple import config
from pathlib import Path
from tinydb import Query, TinyDB

API_KEY = config('API_KEY')
MAX_RETRIES = config('MAX_RETRIES', default=2, cast=int)


def main():
    work_dir = Path(__file__).resolve().parents[1]
    csv_path = work_dir / 'data' / 'ny_saved_places.csv'
    cache_path = work_dir / 'data' / 'serpapi_cache.json'

    # Initialize cache database
    cache_db = TinyDB(cache_path)
    Place = Query()

    df = pd.read_csv(csv_path)
    results = []

    client = serpapi.Client(api_key=API_KEY)

    # Process in batches to avoid rate limiting
    for idx, (_, place) in enumerate(df.iterrows()):
        place_name = place.get('name', '')
        lat = place.get('latitude', None)
        lng = place.get('longitude', None)

        # Create unique cache key based on name and location
        cache_key = f"{place_name}|{lat}|{lng}"

        # Check cache first
        cached_result = cache_db.get(Place.key == cache_key)

        # If cached result exists and doesn't have an error, use it
        if cached_result and 'error' not in cached_result['data']:
            print(f"Using cached result for {place_name} ({idx+1}/{len(df)})")
            # Extract only the requested fields from cached data
            cached_data = cached_result['data']
            clean_result = {'place_name': place_name}

            # First check top-level cached fields
            for field in ['rating', 'reviews', 'google_maps_url', 'price']:
                if field in cached_data and cached_data[field] is not None:
                    value = cached_data[field]
                    # Replace unicode en dash with regular dash for price fields
                    if field == 'price' and isinstance(value, str):
                        value = value.replace('\u2013', '-')
                    clean_result[field] = value

            # If we're missing data and have full_result, extract from it
            missing_fields = [f for f in ['rating', 'reviews', 'price'] if f not in clean_result]
            if missing_fields and 'full_result' in cached_data:
                full_result = cached_data['full_result']

                # Check place_results
                if 'place_results' in full_result and full_result['place_results']:
                    place_data = full_result['place_results']
                    for field in missing_fields:
                        value = place_data.get(field)
                        if value is not None:
                            # Replace unicode en dash with regular dash for price fields
                            if field == 'price' and isinstance(value, str):
                                value = value.replace('\u2013', '-')
                            clean_result[field] = value

                # Check local_results if still missing data
                elif 'local_results' in full_result and full_result['local_results']:
                    first_result = full_result['local_results'][0]
                    for field in missing_fields:
                        if field not in clean_result:  # only if not found in place_results
                            value = first_result.get(field)
                            if value is not None:
                                # Replace unicode en dash with regular dash for price fields
                                if field == 'price' and isinstance(value, str):
                                    value = value.replace('\u2013', '-')
                                clean_result[field] = value

                # Check for google_maps_url in search_metadata
                if 'google_maps_url' not in clean_result and 'search_metadata' in full_result:
                    url = full_result['search_metadata'].get('google_maps_url')
                    if url:
                        clean_result['google_maps_url'] = url

            results.append(clean_result)
            continue

        # If cached result has an error, check retry count
        retry_count = 0
        if cached_result and 'error' in cached_result['data']:
            retry_count = cached_result['data'].get('retry_count', 0)
            if retry_count >= MAX_RETRIES:
                print(f"Skipping {place_name} - max retries ({MAX_RETRIES}) exceeded ({idx+1}/{len(df)})")
                results.append(cached_result['data'])
                continue
            else:
                print(f"Retrying {place_name} (attempt {retry_count + 1}/{MAX_RETRIES}) ({idx+1}/{len(df)})")

        search_params = {
            'engine': 'google_maps',
            'q': place_name,
            'type': 'search',
        }

        if lat is not None and lng is not None:
            search_params['ll'] = f"@{lat},{lng},15.1z"

        try:
            result = client.search(search_params)

            # Extract relevant data from results
            extracted_data = {'place_name': place_name}

            # Get google_maps_url from search_metadata
            if 'search_metadata' in result:
                google_maps_url = result['search_metadata'].get('google_maps_url')
                if google_maps_url:
                    extracted_data['google_maps_url'] = google_maps_url

            # Check for place_results first (specific place lookup)
            if 'place_results' in result and result['place_results']:
                print(f"DEBUG: Found place_results for {place_name}")
                place_data = result['place_results']
                rating = place_data.get('rating')
                reviews = place_data.get('reviews')
                price = place_data.get('price')
                print(f"DEBUG: place_results data - rating: {rating}, reviews: {reviews}, price: {price}")

                if rating is not None:
                    extracted_data['rating'] = rating
                if reviews is not None:
                    extracted_data['reviews'] = reviews
                if price is not None:
                    # Replace unicode en dash with regular dash
                    price = price.replace('\u2013', '-')
                    extracted_data['price'] = price

            # Check for local_results (search results)
            elif 'local_results' in result and result['local_results']:
                print(f"DEBUG: Found local_results for {place_name}")
                first_result = result['local_results'][0]
                rating = first_result.get('rating')
                reviews = first_result.get('reviews')
                price = first_result.get('price')
                print(f"DEBUG: local_results data - rating: {rating}, reviews: {reviews}, price: {price}")

                if rating is not None:
                    extracted_data['rating'] = rating
                if reviews is not None:
                    extracted_data['reviews'] = reviews
                if price is not None:
                    # Replace unicode en dash with regular dash
                    price = price.replace('\u2013', '-')
                    extracted_data['price'] = price
            else:
                print(f"DEBUG: No results found for {place_name} - keys: {list(result.keys())}")

            # Store extracted data for caching (includes full_result for debugging)
            cache_data = extracted_data.copy()
            cache_data['full_result'] = dict(result)  # For debugging/reference

            # Only include requested fields in final results
            clean_result = {'place_name': place_name}
            for field in ['rating', 'reviews', 'google_maps_url', 'price']:
                if field in extracted_data and extracted_data[field] is not None:
                    clean_result[field] = extracted_data[field]

            results.append(clean_result)

            # Cache the result (remove any existing error entry first)
            if cached_result:
                cache_db.remove(Place.key == cache_key)
            cache_db.insert({
                'key': cache_key,
                'data': cache_data
            })

            print(f"Fetched and cached ratings for {place_name} ({idx+1}/{len(df)})")

            # Add delay to avoid rate limiting (1 request per n seconds)
            time.sleep(0.1)

        except Exception as e:
            print(f"Error fetching ratings for {place_name}: {e}")
            new_retry_count = retry_count + 1
            error_data = {
                'place_name': place_name,
                'latitude': lat,
                'longitude': lng,
                'error': str(e),
                'retry_count': new_retry_count,
                'last_retry_at': datetime.now(UTC).isoformat()
            }
            results.append(error_data)

            # Update cache with new retry count (remove old entry first)
            if cached_result:
                cache_db.remove(Place.key == cache_key)
            cache_db.insert({
                'key': cache_key,
                'data': error_data
            })

    # Sort results by weighted score that heavily favors places with more reviews
    def sort_key(result):
        rating = result.get('rating', 0)
        reviews = result.get('reviews', 0)

        # Calculate confidence boost based on review count using match statement
        match reviews:
            case n if n >= 10000:
                confidence_boost = 0.3   # Major boost for 10k+ reviews
            case n if n >= 5000:
                confidence_boost = 0.25  # Large boost for 5k+ reviews
            case n if n >= 1000:
                confidence_boost = 0.2   # Good boost for 1k+ reviews
            case n if n >= 500:
                confidence_boost = 0.15  # Moderate boost for 500+ reviews
            case n if n >= 200:
                confidence_boost = 0.1   # Small boost for 200+ reviews
            case n if n >= 100:
                confidence_boost = 0.05  # Tiny boost for 100+ reviews
            case n if n >= 50:
                confidence_boost = 0     # No change for 50+ reviews
            case n if n >= 10:
                confidence_boost = -0.1  # Small penalty for 10-49 reviews
            case _:
                confidence_boost = -0.3  # Large penalty for <10 reviews

        weighted_score = rating + confidence_boost

        # Use weighted score as primary sort, then raw reviews as tiebreaker
        return (-weighted_score, -reviews)

    results.sort(key=sort_key)

    # Save all results at once
    timestamp = datetime.now(UTC).strftime('%Y%m%d')
    output_path = work_dir / 'results' / f'ratings_{timestamp}.json'

    with open(output_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now(UTC).isoformat(),
            'total_places': len(df),
            'successful_fetches': len([r for r in results if 'error' not in r]),
            'results': results
        }, f, indent=2)

    # Count cached vs fetched results
    cached_count = len([1 for idx, (_, place) in enumerate(df.iterrows())
                        if cache_db.get(Place.key == f"{place.get('name', '')}|{place.get('latitude', None)}|{place.get('longitude', None)}")])
    fetched_count = len(df) - cached_count

    print(f"\nCompleted! Processed {len(results)} places:")
    print(f"  - Used cached results: {cached_count}")
    print(f"  - New API calls made: {fetched_count}")
    print(f"  - Results saved to: {output_path}")


if __name__ == "__main__":
    main()
