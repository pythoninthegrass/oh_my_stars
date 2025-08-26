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
WORK_DIR = Path(__file__).resolve().parents[1]
CSV_PATH = WORK_DIR / 'data' / 'ny_saved_places.csv'
CACHE_PATH = WORK_DIR / 'data' / 'serpapi_cache.json'


def load_data():
    """Load CSV data and initialize cache database."""
    df = pd.read_csv(CSV_PATH)
    cache_db = TinyDB(CACHE_PATH)
    return df, cache_db, Query()


def create_cache_key(place_name, lat, lng):
    """Generate unique cache key for place."""
    return f"{place_name}|{lat}|{lng}"


def normalize_price(price):
    """Replace unicode en dash with regular dash in price strings."""
    return price.replace('\u2013', '-') if isinstance(price, str) else price


def extract_from_cached_data(cached_data, place_name):
    """Extract clean result from cached data."""
    clean_result = {'place_name': place_name}

    # Extract top-level fields
    for field in ['rating', 'reviews', 'google_maps_url', 'price']:
        if field in cached_data and cached_data[field] is not None:
            value = normalize_price(cached_data[field]) if field == 'price' else cached_data[field]
            clean_result[field] = value

    # Extract from full_result if data is missing
    missing_fields = [f for f in ['rating', 'reviews', 'price'] if f not in clean_result]
    if missing_fields and 'full_result' in cached_data:
        full_result = cached_data['full_result']

        # Try place_results first
        if 'place_results' in full_result and full_result['place_results']:
            place_data = full_result['place_results']
            for field in missing_fields:
                value = place_data.get(field)
                if value is not None:
                    clean_result[field] = normalize_price(value) if field == 'price' else value

        # Try local_results if still missing
        elif 'local_results' in full_result and full_result['local_results']:
            first_result = full_result['local_results'][0]
            for field in missing_fields:
                if field not in clean_result:
                    value = first_result.get(field)
                    if value is not None:
                        clean_result[field] = normalize_price(value) if field == 'price' else value

        # Try google_maps_url from search_metadata
        if 'google_maps_url' not in clean_result and 'search_metadata' in full_result:
            url = full_result['search_metadata'].get('google_maps_url')
            if url:
                clean_result['google_maps_url'] = url

    return clean_result


def should_skip_retry(cached_result, place_name, idx, total):
    """Check if place should be skipped due to max retries exceeded."""
    if not (cached_result and 'error' in cached_result['data']):
        return False, 0

    retry_count = cached_result['data'].get('retry_count', 0)
    if retry_count >= MAX_RETRIES:
        print(f"Skipping {place_name} - max retries ({MAX_RETRIES}) exceeded ({idx + 1}/{total})")
        return True, retry_count

    print(f"Retrying {place_name} (attempt {retry_count + 1}/{MAX_RETRIES}) ({idx + 1}/{total})")
    return False, retry_count


def build_search_params(place_name, lat, lng):
    """Build search parameters for SerpAPI."""
    params = {
        'engine': 'google_maps',
        'q': place_name,
        'type': 'search',
    }

    if lat is not None and lng is not None:
        params['ll'] = f"@{lat},{lng},15.1z"

    return params


def extract_api_data(result, place_name):
    """Extract relevant data from SerpAPI result."""
    extracted_data = {'place_name': place_name}

    # Extract google_maps_url
    if 'search_metadata' in result:
        google_maps_url = result['search_metadata'].get('google_maps_url')
        if google_maps_url:
            extracted_data['google_maps_url'] = google_maps_url

    # Extract from place_results (preferred)
    if 'place_results' in result and result['place_results']:
        print(f"DEBUG: Found place_results for {place_name}")
        place_data = result['place_results']
        rating, reviews, price = [place_data.get(field) for field in ['rating', 'reviews', 'price']]
        print(f"DEBUG: place_results data - rating: {rating}, reviews: {reviews}, price: {price}")

        extracted_data.update(
            {
                field: normalize_price(value) if field == 'price' and value is not None else value
                for field, value in [('rating', rating), ('reviews', reviews), ('price', price)]
                if value is not None
            }
        )

    # Extract from local_results (fallback)
    elif 'local_results' in result and result['local_results']:
        print(f"DEBUG: Found local_results for {place_name}")
        first_result = result['local_results'][0]
        rating, reviews, price = [first_result.get(field) for field in ['rating', 'reviews', 'price']]
        print(f"DEBUG: local_results data - rating: {rating}, reviews: {reviews}, price: {price}")

        extracted_data.update(
            {
                field: normalize_price(value) if field == 'price' and value is not None else value
                for field, value in [('rating', rating), ('reviews', reviews), ('price', price)]
                if value is not None
            }
        )
    else:
        print(f"DEBUG: No results found for {place_name} - keys: {list(result.keys())}")

    return extracted_data


def create_clean_result(extracted_data, place_name):
    """Create clean result with only requested fields."""
    clean_result = {'place_name': place_name}
    return {
        **clean_result,
        **{
            field: extracted_data[field]
            for field in ['rating', 'reviews', 'google_maps_url', 'price']
            if field in extracted_data and extracted_data[field] is not None
        },
    }


def cache_result(cache_db, place_query, cache_key, data, cached_result=None):
    """Cache the result, removing any existing entry first."""
    if cached_result:
        cache_db.remove(place_query.key == cache_key)
    cache_db.insert({'key': cache_key, 'data': data})


def create_error_data(place_name, lat, lng, error, retry_count):
    """Create error data structure."""
    return {
        'place_name': place_name,
        'latitude': lat,
        'longitude': lng,
        'error': str(error),
        'retry_count': retry_count + 1,
        'last_retry_at': datetime.now(UTC).isoformat(),
    }


def calculate_sort_key(result):
    """Calculate weighted sort key for results ranking."""
    rating = result.get('rating', 0)
    reviews = result.get('reviews', 0)

    match reviews:
        case n if n >= 10000:
            confidence_boost = 0.3
        case n if n >= 5000:
            confidence_boost = 0.25
        case n if n >= 1000:
            confidence_boost = 0.2
        case n if n >= 500:
            confidence_boost = 0.15
        case n if n >= 200:
            confidence_boost = 0.1
        case n if n >= 100:
            confidence_boost = 0.05
        case n if n >= 50:
            confidence_boost = 0
        case n if n >= 10:
            confidence_boost = -0.1
        case _:
            confidence_boost = -0.3

    weighted_score = rating + confidence_boost
    return (-weighted_score, -reviews)


def save_results(results, df):
    """Save results to JSON file with timestamp."""
    timestamp = datetime.now(UTC).strftime('%Y%m%d')
    output_path = WORK_DIR / 'results' / f'ratings_{timestamp}.json'

    with open(output_path, 'w') as f:
        json.dump(
            {
                'timestamp': datetime.now(UTC).isoformat(),
                'total_places': len(df),
                'successful_fetches': len([r for r in results if 'error' not in r]),
                'results': results,
            },
            f,
            indent=2,
        )

    return output_path


def print_summary(results, df, cache_db, place_query, output_path):
    """Print processing summary."""
    cached_count = len(
        [
            1
            for _, place in df.iterrows()
            if cache_db.get(
                place_query.key == create_cache_key(place.get('name', ''), place.get('latitude'), place.get('longitude'))
            )
        ]
    )
    fetched_count = len(df) - cached_count

    print(f"\nCompleted! Processed {len(results)} places:")
    print(f"  - Used cached results: {cached_count}")
    print(f"  - New API calls made: {fetched_count}")
    print(f"  - Results saved to: {output_path}")


def main():
    df, cache_db, Place = load_data()
    results = []
    client = serpapi.Client(api_key=API_KEY)

    for idx, (_, place) in enumerate(df.iterrows()):
        place_name, lat, lng = [place.get(field) for field in ['name', 'latitude', 'longitude']]
        place_name = place_name or ''
        cache_key = create_cache_key(place_name, lat, lng)
        cached_result = cache_db.get(Place.key == cache_key)

        # Use cached result if valid
        if cached_result and 'error' not in cached_result['data']:
            print(f"Using cached result for {place_name} ({idx + 1}/{len(df)})")
            results.append(extract_from_cached_data(cached_result['data'], place_name))
            continue

        # Check retry limits for error cases
        should_skip, retry_count = should_skip_retry(cached_result, place_name, idx, len(df))
        if should_skip:
            results.append(cached_result['data'])
            continue

        # Make API call
        search_params = build_search_params(place_name, lat, lng)

        try:
            result = client.search(search_params)
            extracted_data = extract_api_data(result, place_name)

            # Create cache data and clean result
            cache_data = {**extracted_data, 'full_result': dict(result)}
            clean_result = create_clean_result(extracted_data, place_name)
            results.append(clean_result)

            # Cache the successful result
            cache_result(cache_db, Place, cache_key, cache_data, cached_result)
            print(f"Fetched and cached ratings for {place_name} ({idx + 1}/{len(df)})")
            time.sleep(0.1)

        except Exception as e:
            print(f"Error fetching ratings for {place_name}: {e}")
            error_data = create_error_data(place_name, lat, lng, e, retry_count)
            results.append(error_data)

            # Cache the error
            cache_result(cache_db, Place, cache_key, error_data, cached_result)

    # Sort and save results
    results.sort(key=calculate_sort_key)
    output_path = save_results(results, df)
    print_summary(results, df, cache_db, Place, output_path)


if __name__ == "__main__":
    main()
