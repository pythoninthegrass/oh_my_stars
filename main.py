#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "geopy>=2.4.1",
#     "httpx>=0.26.0",
#     "python-dateutil>=2.9.0",
# ]
# [tool.uv]
# exclude-newer = "2025-08-31T00:00:00Z"
# ///

"""
Oh My Stars - Google Takeout Maps Data Processor

Usage:
    main.py <command>

Commands:
    extract-labeled-places: Extract and group starred/labeled places by region
    extract-saved-places: Extract saved places with timestamps and integrate with regions
"""

import json
import logging
import ssl
import sys
import time
from datetime import UTC, datetime, timezone
from dateutil.parser import parse as parse_date
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


class SavedPlacesExtractor:
    """Extract and process saved places with timestamps from Google Takeout data"""

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

    def load_existing_regional_data(self, regional_centers_file: Path) -> dict:
        """Load existing regional centers data"""
        if regional_centers_file.exists():
            with open(regional_centers_file) as f:
                return json.load(f)
        return {"metadata": {}, "regions": {}}

    def calculate_center_point(self, places: list[dict]) -> tuple[float, float]:
        """Calculate geographic center of a list of places"""
        if not places:
            return 0.0, 0.0

        total_lat = sum(place['latitude'] for place in places)
        total_lon = sum(place['longitude'] for place in places)

        return total_lat / len(places), total_lon / len(places)

    def parse_timestamp(self, date_str: str) -> str | None:
        """Parse timestamp and convert to ISO format"""
        try:
            parsed_date = parse_date(date_str)
            return parsed_date.isoformat()
        except Exception as e:
            logger.warning(f"Failed to parse timestamp '{date_str}': {e}")
            return None

    def process_saved_places(self, input_file: Path, output_dir: Path) -> bool:
        """Main processing function for saved places"""
        try:
            # Load input data
            with open(input_file) as f:
                data = json.load(f)

            logger.info(f"Loaded {len(data['features'])} saved places")

            # Load existing regional data
            regional_centers_file = output_dir / 'regional_centers.json'
            regional_data = self.load_existing_regional_data(regional_centers_file)

            # Extract saved places
            saved_places = []
            regional_groups = {}
            timestamps = []

            # Start with existing regional groups if any
            for region_name, region_info in regional_data.get('regions', {}).items():
                regional_groups[region_name] = {
                    'labeled_places': region_info.get('places', []),
                    'saved_places': [],
                    'all_coordinates': []
                }

            for i, feature in enumerate(data['features']):
                if i % 100 == 0 and i > 0:
                    logger.info(f"Processing place {i+1}/{len(data['features'])} ({(i+1)/len(data['features'])*100:.1f}%)")

                try:
                    # Extract basic info
                    coords = feature['geometry']['coordinates']
                    props = feature['properties']
                    location = props.get('location', {})

                    # Skip places with invalid coordinates
                    if len(coords) < 2 or (coords[0] == 0 and coords[1] == 0):
                        logger.debug(f"Skipping place with invalid coordinates: {coords}")
                        continue

                    place = {
                        'id': f"saved_{i+1:03d}",
                        'name': location.get('name', 'Unnamed Place'),
                        'longitude': coords[0],
                        'latitude': coords[1],
                        'address': location.get('address', ''),
                        'country_code': location.get('country_code', ''),
                        'google_maps_url': props.get('google_maps_url', ''),
                    }

                    # Parse timestamp
                    date_str = props.get('date', '')
                    if date_str:
                        iso_date = self.parse_timestamp(date_str)
                        if iso_date:
                            place['saved_date'] = iso_date
                            timestamps.append(iso_date)

                    # Determine city
                    city = None
                    if place['address']:
                        city = self.extract_city_from_address(place['address'])

                    # Only use reverse geocoding if we have no address and a valid name
                    if not city and place['name'] != 'Unnamed Place' and len(place['name']) > 3:
                        # Check if we've already processed this exact location recently
                        location_key = f"{place['latitude']:.4f},{place['longitude']:.4f}"
                        if i % 20 == 0:  # Only geocode every 20th place to reduce API load
                            logger.info(f"Reverse geocoding for {place['name']} ({i+1}/{len(data['features'])})")
                            city = self.reverse_geocode_city(place['latitude'], place['longitude'])

                    if not city:
                        # Use country code as fallback for grouping
                        city = f"Unknown Location ({place['country_code']})" if place['country_code'] else "Unknown Location"

                    place['region'] = city
                    saved_places.append(place)

                    # Group by region
                    if city not in regional_groups:
                        regional_groups[city] = {
                            'labeled_places': [],
                            'saved_places': [],
                            'all_coordinates': []
                        }

                    regional_groups[city]['saved_places'].append(place['id'])
                    regional_groups[city]['all_coordinates'].append({
                        'latitude': place['latitude'],
                        'longitude': place['longitude']
                    })

                except Exception as e:
                    logger.error(f"Error processing saved place {i}: {e}")
                    continue

            # Calculate updated regional centers
            updated_regions = {}
            for city, group_data in regional_groups.items():
                all_coords = group_data['all_coordinates']

                # Add existing labeled place coordinates if available
                existing_region = regional_data.get('regions', {}).get(city, {})
                if existing_region and existing_region.get('places'):
                    # We'd need to load labeled places data to get coordinates
                    # For now, use the existing center if available
                    existing_center = existing_region.get('center', {})
                    if existing_center:
                        all_coords.append({
                            'latitude': existing_center['latitude'],
                            'longitude': existing_center['longitude']
                        })

                if all_coords:
                    center_lat, center_lon = self.calculate_center_point(all_coords)
                    updated_regions[city] = {
                        'center': {'latitude': center_lat, 'longitude': center_lon},
                        'labeled_place_count': len(group_data['labeled_places']),
                        'saved_place_count': len(group_data['saved_places']),
                        'total_place_count': len(group_data['labeled_places']) + len(group_data['saved_places']),
                        'labeled_places': group_data['labeled_places'],
                        'saved_places': group_data['saved_places'],
                    }

            # Prepare output
            output_dir.mkdir(exist_ok=True)

            # Calculate date range
            date_range = {}
            if timestamps:
                timestamps.sort()
                date_range = {
                    'earliest': timestamps[0],
                    'latest': timestamps[-1]
                }

            # Write saved places
            saved_places_output = {
                'metadata': {
                    'extraction_date': datetime.now(UTC).isoformat(),
                    'total_saved_places': len(saved_places),
                    'source_file': str(input_file),
                    'date_range': date_range
                },
                'places': saved_places,
            }

            with open(output_dir / 'saved_places.json', 'w') as f:
                json.dump(saved_places_output, f, indent=2)

            # Write updated regional centers
            updated_regional_output = {
                'metadata': {
                    'extraction_date': datetime.now(UTC).isoformat(),
                    'total_labeled_places': sum(r['labeled_place_count'] for r in updated_regions.values()),
                    'total_saved_places': len(saved_places),
                    'total_regions': len(updated_regions),
                    'integrated_data': True
                },
                'regions': updated_regions,
            }

            with open(output_dir / 'regional_centers.json', 'w') as f:
                json.dump(updated_regional_output, f, indent=2)

            logger.info(f"Successfully processed {len(saved_places)} saved places")
            logger.info(f"Updated {len(updated_regions)} regions with integrated data")
            logger.info(f"Date range: {date_range.get('earliest', 'N/A')} to {date_range.get('latest', 'N/A')}")
            logger.info(f"Output written to {output_dir}")

            return True

        except Exception as e:
            logger.error(f"Error processing saved places: {e}")
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

    elif command == "extract-saved-places":
        input_file = Path("takeout/maps/your_places/Saved Places.json")
        output_dir = Path("data")

        if not input_file.exists():
            logger.error(f"Input file not found: {input_file}")
            sys.exit(1)

        extractor = SavedPlacesExtractor()
        success = extractor.process_saved_places(input_file, output_dir)
        sys.exit(0 if success else 1)

    else:
        print(__doc__.strip())


if __name__ == "__main__":
    main()
