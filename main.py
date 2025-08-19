#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "geopy>=2.4.1",
#     "httpx>=0.26.0",
# ]
# [tool.uv]
# exclude-newer = "2025-08-31T00:00:00Z"
# ///

"""
Oh My Stars - Google Takeout Maps Data Processor

Usage:
    main.py extract-labeled-places

Commands:
    extract-labeled-places: Extract and group starred/labeled places by region
"""

import json
import logging
import ssl
import sys
import time
from datetime import UTC, datetime, timezone
from geopy.distance import geodesic
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import Nominatim
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class GeocodingCache:
    """Simple file-based cache for geocoding results"""

    def __init__(self, cache_file: Path = Path("data/geocoding_cache.json")):
        self.cache_file = cache_file
        self.cache = self._load_cache()

    def _load_cache(self) -> dict[str, str]:
        if self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                logger.warning("Could not load geocoding cache, starting fresh")
        return {}

    def get(self, coordinates: tuple[float, float]) -> str | None:
        key = f"{coordinates[0]:.6f},{coordinates[1]:.6f}"
        return self.cache.get(key)

    def set(self, coordinates: tuple[float, float], city: str):
        key = f"{coordinates[0]:.6f},{coordinates[1]:.6f}"
        self.cache[key] = city
        self._save_cache()

    def _save_cache(self):
        self.cache_file.parent.mkdir(exist_ok=True)
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f, indent=2)


class LabeledPlacesExtractor:
    """Extract and process labeled places from Google Takeout data"""

    def __init__(self):
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        self.geocoder = Nominatim(user_agent="oh-my-stars/1.0", ssl_context=ssl_context)
        self.cache = GeocodingCache()

    def extract_city_from_address(self, address: str) -> str | None:
        """Extract city from address string"""
        if not address:
            return None

        parts = [part.strip() for part in address.split(',')]

        # TODO: switch to case statement
        # Look for patterns like "City, State" or "City, State ZIP"
        for part in parts:
            # Skip if it looks like a street address
            if any(indicator in part.lower() for indicator in ['st', 'ave', 'rd', 'dr', 'blvd', 'way', 'place', 'pl']):
                continue
            # Skip ZIP codes
            if part.replace(' ', '').replace('-', '').isdigit():
                continue
            # Skip country names
            if part.upper() in ['USA', 'US', 'UNITED STATES']:
                continue
            # Skip state abbreviations (this is simplified)
            if len(part) == 2 and part.isupper():
                continue

            # This might be a city
            if len(part) > 2 and not part.replace(' ', '').isdigit():
                return part

        return None

    def reverse_geocode_city(self, lat: float, lon: float) -> str | None:
        """Get city name from coordinates using Nominatim"""
        coordinates = (lat, lon)

        # Check cache first
        cached_city = self.cache.get(coordinates)
        if cached_city:
            return cached_city

        try:
            # Respect rate limits
            time.sleep(1)

            location = self.geocoder.reverse((lat, lon), exactly_one=True, language='en')
            if location and location.raw.get('address'):
                address = location.raw['address']
                city = address.get('city') or address.get('town') or address.get('village') or address.get('municipality')

                if city:
                    state = address.get('state')
                    country = address.get('country_code', '').upper()
                    if state and country:
                        city_key = f"{city}, {state}, {country}"
                    elif country:
                        city_key = f"{city}, {country}"
                    else:
                        city_key = city

                    self.cache.set(coordinates, city_key)
                    return city_key

        except (GeocoderTimedOut, GeocoderUnavailable) as e:
            logger.warning(f"Geocoding failed for {lat}, {lon}: {e}")

        return None

    def calculate_center_point(self, places: list[dict]) -> tuple[float, float]:
        """Calculate geographic center of a list of places"""
        if not places:
            return 0.0, 0.0

        total_lat = sum(place['latitude'] for place in places)
        total_lon = sum(place['longitude'] for place in places)

        return total_lat / len(places), total_lon / len(places)

    def process_labeled_places(self, input_file: Path, output_dir: Path) -> bool:
        """Main processing function"""
        try:
            # Load input data
            with open(input_file) as f:
                data = json.load(f)

            logger.info(f"Loaded {len(data['features'])} labeled places")

            # Extract places
            places = []
            regional_groups = {}

            for i, feature in enumerate(data['features']):
                try:
                    # Extract basic info
                    coords = feature['geometry']['coordinates']
                    props = feature['properties']

                    place = {
                        'id': f"place_{i + 1}",
                        'name': props.get('name', 'Unnamed'),
                        'longitude': coords[0],
                        'latitude': coords[1],
                        'address': props.get('address', ''),
                    }

                    # Determine city
                    city = None
                    if place['address']:
                        city = self.extract_city_from_address(place['address'])

                    if not city:
                        logger.info(f"Reverse geocoding for {place['name']}")
                        city = self.reverse_geocode_city(place['latitude'], place['longitude'])

                    if not city:
                        city = "Unknown Location"
                        logger.warning(f"Could not determine city for {place['name']}")

                    place['city'] = city
                    places.append(place)

                    # Group by region
                    if city not in regional_groups:
                        regional_groups[city] = []
                    regional_groups[city].append(place)

                except Exception as e:
                    logger.error(f"Error processing feature {i}: {e}")
                    continue

            # Calculate regional centers
            regions = {}
            for city, city_places in regional_groups.items():
                center_lat, center_lon = self.calculate_center_point(city_places)
                regions[city] = {
                    'center': {'latitude': center_lat, 'longitude': center_lon},
                    'place_count': len(city_places),
                    'places': [place['id'] for place in city_places],
                }

            # Prepare output
            output_dir.mkdir(exist_ok=True)

            # Write labeled places
            labeled_places_output = {
                'metadata': {
                    'extraction_date': datetime.now(UTC).isoformat(),
                    'total_places': len(places),
                    'source_file': str(input_file),
                },
                'places': places,
            }

            with open(output_dir / 'labeled_places.json', 'w') as f:
                json.dump(labeled_places_output, f, indent=2)

            # Write regional centers
            regional_centers_output = {
                'metadata': {
                    'extraction_date': datetime.now(UTC).isoformat(),
                    'total_places': len(places),
                    'total_regions': len(regions),
                },
                'regions': regions,
            }

            with open(output_dir / 'regional_centers.json', 'w') as f:
                json.dump(regional_centers_output, f, indent=2)

            logger.info(f"Successfully processed {len(places)} places into {len(regions)} regions")
            logger.info(f"Output written to {output_dir}")

            return True

        except Exception as e:
            logger.error(f"Error processing labeled places: {e}")
            return False


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return

    command = sys.argv[1]

    # TODO: glob for default filename
    if command == "extract-labeled-places":
        input_file = Path("takeout/maps/saved/My labeled places/Labeled places.json")
        output_dir = Path("data")

        if not input_file.exists():
            logger.error(f"Input file not found: {input_file}")
            sys.exit(1)

        extractor = LabeledPlacesExtractor()
        success = extractor.process_labeled_places(input_file, output_dir)
        sys.exit(0 if success else 1)

    else:
        print(__doc__.strip())


if __name__ == "__main__":
    main()
