#!/usr/bin/env python

"""
Oh My Stars - Google Takeout Maps Data Processor

Analyzes starred locations, saved places, and photo geolocations from Google Takeout
to generate regional visit summaries and comprehensive travel timelines.

Usage:
    main.py [command] [options]

    Default command is 'run-pipeline' if none specified.

Commands:
    extract-takeout: Extract and organize Google Takeout zip file into proper directory structure
    run-pipeline: Execute complete data analysis pipeline from start to finish (default)
    validate-data: Run comprehensive data validation suite
    extract-labeled-places: Extract and group starred/labeled places by region
    extract-saved-places: Extract saved places with timestamps and integrate with regions
    extract-photo-metadata: Extract geolocation data from photo metadata
    correlate-photos-to-regions: Match geotagged photos to regions and saved places
    extract-review-visits: Extract review timestamps as visit confirmations
    generate-visit-timeline: Generate comprehensive visit timeline from all data sources
    generate-summary-report: Generate human-readable markdown summary report
    cache-stats: Display geocoding cache statistics and clean expired entries
    cache-clear: Clear all geocoding cache entries

Options:
    --dry-run: Show what would be done without making changes
    --verbose: Enable verbose logging output
    --input-dir: Path to Google Takeout data directory (default: takeout/maps)
    --output-dir: Path to output directory (default: results)
"""

import argparse
import json
import logging
import shutil
import ssl
import sys
import time
import zipfile
from config import (
    CACHE_DIR,
    DEDUPLICATION_WINDOW_HOURS,
    GEOCODING_CACHE_EXPIRATION_DAYS,
    GEOCODING_CACHE_FILE,
    INPUT_DIR,
    LABELED_PLACES_FILE,
    MAX_VALID_LATITUDE,
    MAX_VALID_LONGITUDE,
    MAX_VALID_YEAR,
    MIN_VALID_LATITUDE,
    MIN_VALID_LONGITUDE,
    MIN_VALID_YEAR,
    NY_SAVED_PLACES_FILE,
    OUTPUT_DIR,
    PHOTO_LOCATIONS_FILE,
    PHOTO_METADATA_FILE,
    PIPELINE_STEPS,
    PLACE_MATCHING_TOLERANCE_MILES,
    REGION_DISTANCE_THRESHOLD_MILES,
    REGIONAL_CENTERS_FILE,
    REVIEW_VISITS_FILE,
    SAVED_PLACES_FILE,
    SERPAPI_CACHE_FILE,
    SUMMARY_REPORT_FILE,
    TAKEOUT_FILE_MAPPINGS,
    TEMP_EXTRACT_DIR,
    VALIDATION_REPORT_FILE,
    VISIT_TIMELINE_FILE,
)
from core.takeout import TakeoutExtractor
from datetime import UTC, datetime, timezone
from dateutil.parser import parse as parse_date
from decouple import config
from geopy.distance import geodesic
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import Nominatim
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class GeocodingCache:
    """Comprehensive file-based cache for geocoding results with rate limiting and expiration"""

    def __init__(
        self, cache_file: Path = CACHE_DIR / GEOCODING_CACHE_FILE, expiration_days: int = GEOCODING_CACHE_EXPIRATION_DAYS
    ):
        self.cache_file = cache_file
        self.expiration_days = expiration_days
        self.last_api_call = 0  # Timestamp of last API call for rate limiting
        self.min_api_interval = 1.0  # Minimum seconds between API calls
        self.cache_data = self._load_cache()
        self.session_hits = 0
        self.session_misses = 0

    def _load_cache(self) -> dict:
        """Load cache from file with proper structure"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    data = json.load(f)
                    # Ensure proper structure
                    if 'metadata' not in data:
                        data = self._migrate_old_cache(data)
                    return data
            except (json.JSONDecodeError, FileNotFoundError):
                logger.warning("Could not load geocoding cache, starting fresh")

        # Return empty cache with proper structure
        return {
            'metadata': {
                'version': '1.0',
                'created': datetime.now(UTC).isoformat(),
                'last_updated': datetime.now(UTC).isoformat(),
                'total_entries': 0,
                'cache_hits': 0,
                'cache_misses': 0,
                'expiration_days': self.expiration_days,
            },
            'entries': {},
        }

    def _migrate_old_cache(self, old_cache: dict) -> dict:
        """Migrate old simple cache format to new structure"""
        logger.info("Migrating old cache format to new structure")
        new_cache = {
            'metadata': {
                'version': '1.0',
                'created': datetime.now(UTC).isoformat(),
                'last_updated': datetime.now(UTC).isoformat(),
                'total_entries': len(old_cache),
                'cache_hits': 0,
                'cache_misses': 0,
                'expiration_days': self.expiration_days,
            },
            'entries': {},
        }

        # Convert old entries to new format
        for key, city in old_cache.items():
            if isinstance(city, str):  # Skip metadata entries
                new_cache['entries'][f"reverse_{key}"] = {
                    'timestamp': datetime.now(UTC).isoformat(),
                    'query_type': 'reverse',
                    'query': self._parse_coordinates_from_key(key),
                    'response': {'city': city},
                }

        return new_cache

    def _parse_coordinates_from_key(self, key: str) -> dict:
        """Parse coordinates from old cache key format"""
        try:
            lat_str, lon_str = key.split(',')
            return {'latitude': float(lat_str), 'longitude': float(lon_str)}
        except (ValueError, IndexError):
            return {'latitude': 0.0, 'longitude': 0.0}

    def _generate_cache_key(self, query_type: str, **kwargs) -> str:
        """Generate cache key for different query types"""
        if query_type == 'reverse':
            lat = kwargs.get('latitude', 0)
            lon = kwargs.get('longitude', 0)
            return f"reverse_{lat:.6f}_{lon:.6f}"
        elif query_type == 'forward':
            address = kwargs.get('address', '')
            # Normalize address for consistent keys
            normalized = address.lower().strip().replace(' ', '_')
            return f"forward_{normalized}"
        else:
            raise ValueError(f"Unknown query type: {query_type}")

    def _is_expired(self, entry: dict) -> bool:
        """Check if cache entry has expired"""
        try:
            entry_time = parse_date(entry['timestamp'])
            now = datetime.now(UTC)
            age_days = (now - entry_time).days
            return age_days > self.expiration_days
        except Exception:
            return True  # Consider invalid timestamps as expired

    def get(self, coordinates: tuple[float, float]) -> str | None:
        """Get cached reverse geocoding result"""
        key = self._generate_cache_key('reverse', latitude=coordinates[0], longitude=coordinates[1])
        entry = self.cache_data['entries'].get(key)

        if entry and not self._is_expired(entry):
            self.session_hits += 1
            self.cache_data['metadata']['cache_hits'] += 1
            response = entry.get('response', {})
            return response.get('city')

        # Cache miss or expired
        self.session_misses += 1
        self.cache_data['metadata']['cache_misses'] += 1

        # Clean up expired entry
        if entry and self._is_expired(entry):
            del self.cache_data['entries'][key]
            self.cache_data['metadata']['total_entries'] -= 1

        return None

    def set(self, coordinates: tuple[float, float], city: str, full_response: dict = None):
        """Set cached reverse geocoding result"""
        key = self._generate_cache_key('reverse', latitude=coordinates[0], longitude=coordinates[1])

        entry = {
            'timestamp': datetime.now(UTC).isoformat(),
            'query_type': 'reverse',
            'query': {'latitude': coordinates[0], 'longitude': coordinates[1]},
            'response': full_response or {'city': city},
        }

        # Add new entry
        if key not in self.cache_data['entries']:
            self.cache_data['metadata']['total_entries'] += 1

        self.cache_data['entries'][key] = entry
        self.cache_data['metadata']['last_updated'] = datetime.now(UTC).isoformat()
        self._save_cache()

    def get_forward(self, address: str) -> dict | None:
        """Get cached forward geocoding result"""
        key = self._generate_cache_key('forward', address=address)
        entry = self.cache_data['entries'].get(key)

        if entry and not self._is_expired(entry):
            self.session_hits += 1
            self.cache_data['metadata']['cache_hits'] += 1
            return entry.get('response')

        # Cache miss or expired
        self.session_misses += 1
        self.cache_data['metadata']['cache_misses'] += 1

        # Clean up expired entry
        if entry and self._is_expired(entry):
            del self.cache_data['entries'][key]
            self.cache_data['metadata']['total_entries'] -= 1

        return None

    def set_forward(self, address: str, response: dict):
        """Set cached forward geocoding result"""
        key = self._generate_cache_key('forward', address=address)

        entry = {
            'timestamp': datetime.now(UTC).isoformat(),
            'query_type': 'forward',
            'query': {'address': address},
            'response': response,
        }

        # Add new entry
        if key not in self.cache_data['entries']:
            self.cache_data['metadata']['total_entries'] += 1

        self.cache_data['entries'][key] = entry
        self.cache_data['metadata']['last_updated'] = datetime.now(UTC).isoformat()
        self._save_cache()

    def enforce_rate_limit(self):
        """Enforce rate limiting for API calls (1 request per second)"""
        current_time = time.time()
        time_since_last = current_time - self.last_api_call

        if time_since_last < self.min_api_interval:
            sleep_time = self.min_api_interval - time_since_last
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f} seconds")
            time.sleep(sleep_time)

        self.last_api_call = time.time()

    def clean_expired(self) -> int:
        """Remove expired entries from cache"""
        expired_keys = []

        for key, entry in self.cache_data['entries'].items():
            if self._is_expired(entry):
                expired_keys.append(key)

        for key in expired_keys:
            del self.cache_data['entries'][key]

        if expired_keys:
            self.cache_data['metadata']['total_entries'] -= len(expired_keys)
            self.cache_data['metadata']['last_updated'] = datetime.now(UTC).isoformat()
            self._save_cache()
            logger.info(f"Cleaned {len(expired_keys)} expired cache entries")

        return len(expired_keys)

    def clear(self):
        """Clear all cache entries"""
        entry_count = len(self.cache_data['entries'])
        self.cache_data['entries'] = {}
        self.cache_data['metadata']['total_entries'] = 0
        self.cache_data['metadata']['last_updated'] = datetime.now(UTC).isoformat()
        self._save_cache()
        logger.info(f"Cleared {entry_count} cache entries")

    def get_stats(self) -> dict:
        """Get cache statistics"""
        total_hits = self.cache_data['metadata']['cache_hits'] + self.session_hits
        total_misses = self.cache_data['metadata']['cache_misses'] + self.session_misses
        total_requests = total_hits + total_misses

        hit_ratio = (total_hits / total_requests * 100) if total_requests > 0 else 0

        return {
            'total_entries': self.cache_data['metadata']['total_entries'],
            'cache_hits': total_hits,
            'cache_misses': total_misses,
            'hit_ratio_percent': round(hit_ratio, 1),
            'session_hits': self.session_hits,
            'session_misses': self.session_misses,
            'expiration_days': self.expiration_days,
            'created': self.cache_data['metadata']['created'],
            'last_updated': self.cache_data['metadata']['last_updated'],
        }

    def _save_cache(self):
        """Save cache to file"""
        self.cache_file.parent.mkdir(exist_ok=True)
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache_data, f, indent=2)


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
        """Get city name from coordinates using Nominatim with enhanced caching"""
        coordinates = (lat, lon)

        # Check cache first
        cached_city = self.cache.get(coordinates)
        if cached_city:
            return cached_city

        try:
            # Enforce rate limiting
            self.cache.enforce_rate_limit()

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

                    # Store full response in cache
                    self.cache.set(coordinates, city_key, address)
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

            with open(output_dir / LABELED_PLACES_FILE, 'w') as f:
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

            with open(output_dir / REGIONAL_CENTERS_FILE, 'w') as f:
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
        """Get city name from coordinates using Nominatim with enhanced caching"""
        coordinates = (lat, lon)

        # Check cache first
        cached_city = self.cache.get(coordinates)
        if cached_city:
            return cached_city

        try:
            # Enforce rate limiting
            self.cache.enforce_rate_limit()

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

                    # Store full response in cache
                    self.cache.set(coordinates, city_key, address)
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
                    'all_coordinates': [],
                }

            for i, feature in enumerate(data['features']):
                if i % 100 == 0 and i > 0:
                    logger.info(
                        f"Processing place {i + 1}/{len(data['features'])} ({(i + 1) / len(data['features']) * 100:.1f}%)"
                    )

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
                        'id': f"saved_{i + 1:03d}",
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
                            logger.info(f"Reverse geocoding for {place['name']} ({i + 1}/{len(data['features'])})")
                            city = self.reverse_geocode_city(place['latitude'], place['longitude'])

                    if not city:
                        # Use country code as fallback for grouping
                        city = f"Unknown Location ({place['country_code']})" if place['country_code'] else "Unknown Location"

                    place['region'] = city
                    saved_places.append(place)

                    # Group by region
                    if city not in regional_groups:
                        regional_groups[city] = {'labeled_places': [], 'saved_places': [], 'all_coordinates': []}

                    regional_groups[city]['saved_places'].append(place['id'])
                    regional_groups[city]['all_coordinates'].append(
                        {'latitude': place['latitude'], 'longitude': place['longitude']}
                    )

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
                        all_coords.append({'latitude': existing_center['latitude'], 'longitude': existing_center['longitude']})

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
                date_range = {'earliest': timestamps[0], 'latest': timestamps[-1]}

            # Write saved places
            saved_places_output = {
                'metadata': {
                    'extraction_date': datetime.now(UTC).isoformat(),
                    'total_saved_places': len(saved_places),
                    'source_file': str(input_file),
                    'date_range': date_range,
                },
                'places': saved_places,
            }

            with open(output_dir / SAVED_PLACES_FILE, 'w') as f:
                json.dump(saved_places_output, f, indent=2)

            # Write updated regional centers
            updated_regional_output = {
                'metadata': {
                    'extraction_date': datetime.now(UTC).isoformat(),
                    'total_labeled_places': sum(r['labeled_place_count'] for r in updated_regions.values()),
                    'total_saved_places': len(saved_places),
                    'total_regions': len(updated_regions),
                    'integrated_data': True,
                },
                'regions': updated_regions,
            }

            with open(output_dir / REGIONAL_CENTERS_FILE, 'w') as f:
                json.dump(updated_regional_output, f, indent=2)

            logger.info(f"Successfully processed {len(saved_places)} saved places")
            logger.info(f"Updated {len(updated_regions)} regions with integrated data")
            logger.info(f"Date range: {date_range.get('earliest', 'N/A')} to {date_range.get('latest', 'N/A')}")
            logger.info(f"Output written to {output_dir}")

            return True

        except Exception as e:
            logger.error(f"Error processing saved places: {e}")
            return False


class PhotoMetadataExtractor:
    """Extract geolocation data from photo metadata JSON files"""

    def __init__(self):
        pass

    def validate_coordinates(self, lat: float, lon: float) -> bool:
        """Validate coordinate ranges"""
        return MIN_VALID_LATITUDE <= lat <= MAX_VALID_LATITUDE and MIN_VALID_LONGITUDE <= lon <= MAX_VALID_LONGITUDE

    def parse_timestamp_from_epoch(self, timestamp_str: str) -> str | None:
        """Convert epoch timestamp to ISO format"""
        try:
            # Handle both string and integer timestamps
            timestamp = int(timestamp_str)
            dt = datetime.fromtimestamp(timestamp, tz=UTC)
            return dt.isoformat()
        except Exception as e:
            logger.warning(f"Failed to parse epoch timestamp '{timestamp_str}': {e}")
            return None

    def process_photo_metadata(self, photos_dir: Path, output_dir: Path) -> bool:
        """Main processing function for photo metadata"""
        try:
            # Check if photos directory exists
            if not photos_dir.exists():
                logger.info(f"Photos directory not found: {photos_dir} - creating empty metadata")
                # Create empty metadata file
                empty_metadata = {
                    'metadata': {
                        'extraction_date': datetime.now(UTC).isoformat(),
                        'source': str(photos_dir),
                        'total_files_processed': 0,
                        'geotagged_photos': 0,
                        'date_range': None,
                    },
                    'photos': [],
                }

                output_dir.mkdir(exist_ok=True)
                with open(output_dir / PHOTO_METADATA_FILE, 'w') as f:
                    json.dump(empty_metadata, f, indent=2)

                logger.info("Created empty photo metadata file")
                return True

            # Find all JSON metadata files
            json_files = list(photos_dir.glob("*.json"))

            if not json_files:
                logger.info(f"No JSON metadata files found in {photos_dir} - creating empty metadata")
                # Create empty metadata file
                empty_metadata = {
                    'metadata': {
                        'extraction_date': datetime.now(UTC).isoformat(),
                        'source': str(photos_dir),
                        'total_files_processed': 0,
                        'geotagged_photos': 0,
                        'date_range': None,
                    },
                    'photos': [],
                }

                output_dir.mkdir(exist_ok=True)
                with open(output_dir / PHOTO_METADATA_FILE, 'w') as f:
                    json.dump(empty_metadata, f, indent=2)

                return True

            logger.info(f"Found {len(json_files)} metadata files to process")

            photos = []
            geotagged_count = 0
            timestamps = []

            for i, json_file in enumerate(json_files):
                if i % 10 == 0 and i > 0:
                    logger.info(f"Processing file {i + 1}/{len(json_files)} ({(i + 1) / len(json_files) * 100:.1f}%)")

                try:
                    with open(json_file) as f:
                        metadata = json.load(f)

                    # Extract filename (remove .json extension)
                    filename = json_file.name[:-5]  # Remove .json

                    photo_data = {
                        'filename': filename,
                        'has_geolocation': False,
                        'coordinates': None,
                        'timestamp': None,
                        'photo_taken_time': None,
                        'creation_time': None,
                        'description': metadata.get('description', ''),
                        'image_views': metadata.get('imageViews', '0'),
                    }

                    # Extract timestamps
                    if 'photoTakenTime' in metadata:
                        photo_taken_timestamp = metadata['photoTakenTime'].get('timestamp')
                        if photo_taken_timestamp:
                            photo_data['photo_taken_time'] = self.parse_timestamp_from_epoch(photo_taken_timestamp)
                            photo_data['timestamp'] = photo_data['photo_taken_time']  # Use photo taken time as primary
                            if photo_data['timestamp']:
                                timestamps.append(photo_data['timestamp'])

                    if 'creationTime' in metadata:
                        creation_timestamp = metadata['creationTime'].get('timestamp')
                        if creation_timestamp:
                            photo_data['creation_time'] = self.parse_timestamp_from_epoch(creation_timestamp)
                            # If no photo taken time, use creation time
                            if not photo_data['timestamp']:
                                photo_data['timestamp'] = photo_data['creation_time']
                                if photo_data['timestamp']:
                                    timestamps.append(photo_data['timestamp'])

                    # Extract geolocation if available
                    if 'geoDataExif' in metadata:
                        geo_data = metadata['geoDataExif']

                        lat = geo_data.get('latitude')
                        lon = geo_data.get('longitude')

                        if lat is not None and lon is not None:
                            if self.validate_coordinates(lat, lon):
                                photo_data['has_geolocation'] = True
                                photo_data['coordinates'] = {
                                    'latitude': lat,
                                    'longitude': lon,
                                    'altitude': geo_data.get('altitude', None),
                                }
                                geotagged_count += 1
                            else:
                                logger.warning(f"Invalid coordinates in {filename}: lat={lat}, lon={lon}")

                    photos.append(photo_data)

                except Exception as e:
                    logger.error(f"Error processing {json_file}: {e}")
                    continue

            # Calculate statistics
            total_photos = len(photos)
            date_range = {}
            if timestamps:
                timestamps.sort()
                date_range = {'earliest': timestamps[0], 'latest': timestamps[-1]}

            # Prepare output
            output_dir.mkdir(exist_ok=True)

            photo_metadata_output = {
                'metadata': {
                    'extraction_date': datetime.now(UTC).isoformat(),
                    'total_photos': total_photos,
                    'geotagged_photos': geotagged_count,
                    'non_geotagged_photos': total_photos - geotagged_count,
                    'geolocation_percentage': round((geotagged_count / total_photos * 100), 2) if total_photos > 0 else 0,
                    'source_directory': str(photos_dir),
                    'date_range': date_range,
                },
                'photos': photos,
            }

            with open(output_dir / 'photo_metadata.json', 'w') as f:
                json.dump(photo_metadata_output, f, indent=2)

            logger.info(f"Successfully processed {total_photos} photo metadata files")
            logger.info(f"Found {geotagged_count} geotagged photos ({(geotagged_count / total_photos * 100):.1f}%)")
            logger.info(f"Date range: {date_range.get('earliest', 'N/A')} to {date_range.get('latest', 'N/A')}")
            logger.info(f"Output written to {output_dir / PHOTO_METADATA_FILE}")

            return True

        except Exception as e:
            logger.error(f"Error processing photo metadata: {e}")
            return False


class PhotoLocationCorrelator:
    """Correlate geotagged photos to regions and saved places"""

    def __init__(self):
        self.region_distance_threshold_miles = REGION_DISTANCE_THRESHOLD_MILES
        self.place_distance_threshold_miles = 0.1

    def load_existing_data(self, data_dir: Path) -> tuple[dict, dict, dict]:
        """Load regional centers, saved places, and photo metadata"""
        regional_centers = {}
        saved_places = {}
        photo_metadata = {}

        # Load regional centers
        regional_file = data_dir / REGIONAL_CENTERS_FILE
        if regional_file.exists():
            with open(regional_file) as f:
                regional_centers = json.load(f)

        # Load saved places
        saved_file = data_dir / SAVED_PLACES_FILE
        if saved_file.exists():
            with open(saved_file) as f:
                saved_places = json.load(f)

        # Load labeled places
        labeled_file = data_dir / 'labeled_places.json'
        if labeled_file.exists():
            with open(labeled_file) as f:
                labeled_places = json.load(f)
                # Merge labeled places into saved places format for unified processing
                if 'places' not in saved_places:
                    saved_places['places'] = []
                saved_places['places'].extend(labeled_places.get('places', []))

        # Load photo metadata
        photo_file = data_dir / PHOTO_METADATA_FILE
        if photo_file.exists():
            with open(photo_file) as f:
                photo_metadata = json.load(f)

        return regional_centers, saved_places, photo_metadata

    def calculate_distance_miles(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance in miles between two coordinates"""
        try:
            point1 = (lat1, lon1)
            point2 = (lat2, lon2)
            distance = geodesic(point1, point2).miles
            return distance
        except Exception as e:
            logger.warning(f"Error calculating distance: {e}")
            return float('inf')

    def find_nearest_region(self, photo_lat: float, photo_lon: float, regions: dict) -> tuple[str | None, float]:
        """Find the nearest region within threshold distance"""
        nearest_region = None
        min_distance = float('inf')

        for region_name, region_data in regions.items():
            center = region_data.get('center', {})
            if not center:
                continue

            region_lat = center.get('latitude')
            region_lon = center.get('longitude')

            if region_lat is None or region_lon is None:
                continue

            distance = self.calculate_distance_miles(photo_lat, photo_lon, region_lat, region_lon)

            if distance < min_distance and distance <= self.region_distance_threshold_miles:
                min_distance = distance
                nearest_region = region_name

        return nearest_region, min_distance if nearest_region else float('inf')

    def find_nearest_places(self, photo_lat: float, photo_lon: float, places: list) -> list:
        """Find saved/labeled places within threshold distance"""
        nearby_places = []

        for place in places:
            place_lat = place.get('latitude')
            place_lon = place.get('longitude')

            if place_lat is None or place_lon is None:
                continue

            distance = self.calculate_distance_miles(photo_lat, photo_lon, place_lat, place_lon)

            if distance <= self.place_distance_threshold_miles:
                nearby_places.append(
                    {
                        'name': place.get('name', 'Unknown'),
                        'distance': distance,
                        'id': place.get('id', ''),
                        'type': 'labeled' if place.get('id', '').startswith('place_') else 'saved',
                    }
                )

        # Sort by distance
        nearby_places.sort(key=lambda x: x['distance'])
        return nearby_places

    def correlate_photos_to_locations(self, data_dir: Path, output_dir: Path) -> bool:
        """Main processing function to correlate photos with regions and places"""
        try:
            # Load all required data
            regional_data, saved_data, photo_data = self.load_existing_data(data_dir)

            if not regional_data.get('regions'):
                logger.error("No regional centers data found")
                return False

            if photo_data.get('photos') is None:
                logger.error("No photo metadata found")
                return False

            if len(photo_data.get('photos', [])) == 0:
                logger.info("No photos to process - creating empty photo locations file")
                # Create empty photo locations file
                empty_locations = {
                    'metadata': {
                        'extraction_date': datetime.now(UTC).isoformat(),
                        'total_photos': 0,
                        'matched_photos': 0,
                        'unmatched_photos': 0,
                        'unique_regions': 0,
                    },
                    'photo_locations': [],
                    'unmatched_photos': [],
                }

                output_dir.mkdir(exist_ok=True)
                with open(output_dir / PHOTO_LOCATIONS_FILE, 'w') as f:
                    json.dump(empty_locations, f, indent=2)

                return True

            logger.info(f"Processing {len(photo_data['photos'])} photos against {len(regional_data['regions'])} regions")

            # Get geotagged photos only
            geotagged_photos = [p for p in photo_data['photos'] if p.get('has_geolocation')]
            places_list = saved_data.get('places', [])

            logger.info(f"Found {len(geotagged_photos)} geotagged photos and {len(places_list)} saved/labeled places")

            # Process photos
            region_groups = {}
            unmatched_photos = []

            for i, photo in enumerate(geotagged_photos):
                if i % 5 == 0 and i > 0:
                    logger.info(
                        f"Processing photo {i + 1}/{len(geotagged_photos)} ({(i + 1) / len(geotagged_photos) * 100:.1f}%)"
                    )

                coords = photo.get('coordinates', {})
                if not coords:
                    continue

                photo_lat = coords.get('latitude')
                photo_lon = coords.get('longitude')

                if photo_lat is None or photo_lon is None:
                    continue

                # Find nearest region
                nearest_region, distance_to_region = self.find_nearest_region(photo_lat, photo_lon, regional_data['regions'])

                # Find nearby places
                nearby_places = self.find_nearest_places(photo_lat, photo_lon, places_list)

                photo_location_data = {
                    'filename': photo.get('filename'),
                    'timestamp': photo.get('timestamp'),
                    'coordinates': coords,
                    'distance_to_center': distance_to_region,
                    'nearby_places': nearby_places,
                    'nearest_place': nearby_places[0] if nearby_places else None,
                }

                if nearest_region:
                    if nearest_region not in region_groups:
                        region_groups[nearest_region] = []
                    region_groups[nearest_region].append(photo_location_data)
                else:
                    unmatched_photos.append(photo_location_data)

            # Sort photos within each region by timestamp
            for region_photos in region_groups.values():
                region_photos.sort(key=lambda x: x.get('timestamp', ''))

            # Calculate statistics per region
            region_summaries = {}
            for region_name, photos in region_groups.items():
                timestamps = [p.get('timestamp') for p in photos if p.get('timestamp')]
                date_range = {}
                if timestamps:
                    timestamps.sort()
                    date_range = {'first_photo': timestamps[0], 'last_photo': timestamps[-1]}

                region_summaries[region_name] = {'photo_count': len(photos), 'date_range': date_range, 'photos': photos}

            # Prepare output
            output_dir.mkdir(exist_ok=True)

            photo_locations_output = {
                'metadata': {
                    'processing_date': datetime.now(UTC).isoformat(),
                    'total_photos_processed': len(geotagged_photos),
                    'photos_matched_to_regions': sum(len(photos) for photos in region_groups.values()),
                    'unmatched_photos': len(unmatched_photos),
                    'total_regions_with_photos': len(region_groups),
                    'region_distance_threshold_miles': self.region_distance_threshold_miles,
                    'place_distance_threshold_miles': self.place_distance_threshold_miles,
                },
                'regions': region_summaries,
                'unmatched_photos': unmatched_photos,
            }

            with open(output_dir / 'photo_locations.json', 'w') as f:
                json.dump(photo_locations_output, f, indent=2)

            logger.info(f"Successfully correlated {len(geotagged_photos)} photos")
            logger.info(f"Matched {sum(len(photos) for photos in region_groups.values())} photos to {len(region_groups)} regions")
            logger.info(f"Found {len(unmatched_photos)} unmatched photos")
            logger.info(f"Output written to {output_dir / PHOTO_LOCATIONS_FILE}")

            return True

        except Exception as e:
            logger.error(f"Error correlating photos to locations: {e}")
            return False


class ReviewVisitsExtractor:
    """Extract review timestamps as visit confirmations"""

    def __init__(self):
        self.place_matching_tolerance_miles = PLACE_MATCHING_TOLERANCE_MILES  # Quarter mile for fuzzy matching
        self.region_distance_threshold_miles = REGION_DISTANCE_THRESHOLD_MILES

    def load_existing_data(self, data_dir: Path) -> tuple[dict, dict]:
        """Load regional centers and saved/labeled places data"""
        regional_centers = {}
        all_places = []

        # Load regional centers
        regional_file = data_dir / REGIONAL_CENTERS_FILE
        if regional_file.exists():
            with open(regional_file) as f:
                regional_centers = json.load(f)

        # Load saved places
        saved_file = data_dir / SAVED_PLACES_FILE
        if saved_file.exists():
            with open(saved_file) as f:
                saved_data = json.load(f)
                all_places.extend(saved_data.get('places', []))

        # Load labeled places
        labeled_file = data_dir / 'labeled_places.json'
        if labeled_file.exists():
            with open(labeled_file) as f:
                labeled_data = json.load(f)
                all_places.extend(labeled_data.get('places', []))

        return regional_centers, all_places

    def calculate_distance_miles(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance in miles between two coordinates"""
        try:
            point1 = (lat1, lon1)
            point2 = (lat2, lon2)
            distance = geodesic(point1, point2).miles
            return distance
        except Exception as e:
            logger.warning(f"Error calculating distance: {e}")
            return float('inf')

    def fuzzy_match_place_name(self, review_name: str, place_name: str) -> float:
        """Simple fuzzy matching score for place names (0-1, higher is better)"""
        review_name_lower = review_name.lower().strip()
        place_name_lower = place_name.lower().strip()

        # Exact match
        if review_name_lower == place_name_lower:
            return 1.0

        # Substring match
        if review_name_lower in place_name_lower or place_name_lower in review_name_lower:
            return 0.8

        # Word overlap - simple approach
        review_words = set(review_name_lower.split())
        place_words = set(place_name_lower.split())

        if review_words and place_words:
            overlap = len(review_words.intersection(place_words))
            total = len(review_words.union(place_words))
            return overlap / total if total > 0 else 0.0

        return 0.0

    def find_matching_place(self, review_name: str, review_lat: float, review_lon: float, places: list) -> dict | None:
        """Find the best matching place for a review"""
        best_match = None
        best_score = 0.0

        for place in places:
            place_lat = place.get('latitude')
            place_lon = place.get('longitude')
            place_name = place.get('name', '')

            if place_lat is None or place_lon is None:
                continue

            # Calculate distance
            distance = self.calculate_distance_miles(review_lat, review_lon, place_lat, place_lon)

            # Only consider places within tolerance
            if distance > self.place_matching_tolerance_miles:
                continue

            # Calculate name similarity
            name_score = self.fuzzy_match_place_name(review_name, place_name)

            # Combined score: name similarity weighted more than distance
            # Closer places get bonus, perfect name match is weighted heavily
            distance_score = max(0, 1 - (distance / self.place_matching_tolerance_miles))
            combined_score = (name_score * 0.7) + (distance_score * 0.3)

            if combined_score > best_score and combined_score > 0.3:  # Minimum threshold
                best_score = combined_score
                best_match = {'place': place, 'distance': distance, 'name_score': name_score, 'combined_score': combined_score}

        return best_match

    def find_nearest_region(self, review_lat: float, review_lon: float, regions: dict) -> tuple[str | None, float]:
        """Find the nearest region for a review location"""
        nearest_region = None
        min_distance = float('inf')

        for region_name, region_data in regions.items():
            center = region_data.get('center', {})
            if not center:
                continue

            region_lat = center.get('latitude')
            region_lon = center.get('longitude')

            if region_lat is None or region_lon is None:
                continue

            distance = self.calculate_distance_miles(review_lat, review_lon, region_lat, region_lon)

            if distance < min_distance and distance <= self.region_distance_threshold_miles:
                min_distance = distance
                nearest_region = region_name

        return nearest_region, min_distance if nearest_region else float('inf')

    def extract_review_visits(self, reviews_file: Path, data_dir: Path, output_dir: Path) -> bool:
        """Main processing function for review visits"""
        try:
            # Load review data
            with open(reviews_file) as f:
                review_data = json.load(f)

            reviews = review_data.get('features', [])
            logger.info(f"Loaded {len(reviews)} reviews")

            if not reviews:
                logger.warning("No reviews found")
                return False

            # Load existing data
            regional_data, all_places = self.load_existing_data(data_dir)

            logger.info(f"Loaded {len(regional_data.get('regions', {}))} regions and {len(all_places)} places")

            # Process reviews
            processed_reviews = []
            matched_to_places = 0
            matched_to_regions = 0

            for i, review_feature in enumerate(reviews):
                try:
                    coords = review_feature.get('geometry', {}).get('coordinates', [])
                    props = review_feature.get('properties', {})
                    location = props.get('location', {})

                    if len(coords) < 2:
                        logger.warning(f"Review {i + 1} missing coordinates")
                        continue

                    review_lon, review_lat = coords[0], coords[1]

                    review_record = {
                        'id': f"review_{i + 1:03d}",
                        'place_name': location.get('name', 'Unknown Place'),
                        'coordinates': {'latitude': review_lat, 'longitude': review_lon},
                        'review_date': props.get('date'),
                        'rating': props.get('five_star_rating_published'),
                        'text_preview': (props.get('review_text_published', '')[:100] + '...')
                        if props.get('review_text_published')
                        else '',
                        'address': location.get('address', ''),
                        'google_maps_url': props.get('google_maps_url', ''),
                        'matched_place': None,
                        'place_match_details': None,
                        'region': None,
                        'distance_to_region': None,
                        'visit_type': 'confirmed',
                    }

                    # Try to match to existing places
                    place_match = self.find_matching_place(review_record['place_name'], review_lat, review_lon, all_places)

                    if place_match:
                        matched_to_places += 1
                        review_record['matched_place'] = place_match['place'].get('id')
                        review_record['place_match_details'] = {
                            'distance': place_match['distance'],
                            'name_score': place_match['name_score'],
                            'combined_score': place_match['combined_score'],
                            'matched_name': place_match['place'].get('name'),
                        }

                    # Find nearest region
                    nearest_region, distance_to_region = self.find_nearest_region(
                        review_lat, review_lon, regional_data.get('regions', {})
                    )

                    if nearest_region:
                        matched_to_regions += 1
                        review_record['region'] = nearest_region
                        review_record['distance_to_region'] = distance_to_region

                    processed_reviews.append(review_record)

                except Exception as e:
                    logger.error(f"Error processing review {i + 1}: {e}")
                    continue

            # Prepare output
            output_dir.mkdir(exist_ok=True)

            review_visits_output = {
                'metadata': {
                    'extraction_date': datetime.now(UTC).isoformat(),
                    'total_reviews': len(processed_reviews),
                    'matched_to_places': matched_to_places,
                    'matched_to_regions': matched_to_regions,
                    'place_matching_tolerance_miles': self.place_matching_tolerance_miles,
                    'region_distance_threshold_miles': self.region_distance_threshold_miles,
                    'source_file': str(reviews_file),
                },
                'reviews': processed_reviews,
            }

            with open(output_dir / REVIEW_VISITS_FILE, 'w') as f:
                json.dump(review_visits_output, f, indent=2)

            logger.info(f"Successfully processed {len(processed_reviews)} reviews")
            logger.info(
                f"Matched {matched_to_places} reviews to existing places ({(matched_to_places / len(processed_reviews) * 100):.1f}%)"
            )
            logger.info(
                f"Matched {matched_to_regions} reviews to regions ({(matched_to_regions / len(processed_reviews) * 100):.1f}%)"
            )
            logger.info(f"Output written to {output_dir / REVIEW_VISITS_FILE}")

            return True

        except Exception as e:
            logger.error(f"Error extracting review visits: {e}")
            return False


class VisitTimelineGenerator:
    """Generate comprehensive visit timeline from all data sources"""

    def __init__(self):
        self.deduplication_window_hours = DEDUPLICATION_WINDOW_HOURS  # Consider visits within 24 hours as same visit

    def load_all_data(self, data_dir: Path) -> tuple[dict, dict, dict, dict]:
        """Load all required data sources"""
        photo_locations = {}
        review_visits = {}
        saved_places = {}
        regional_centers = {}

        # Load photo locations
        photo_file = data_dir / PHOTO_LOCATIONS_FILE
        if photo_file.exists():
            with open(photo_file) as f:
                photo_locations = json.load(f)

        # Load review visits
        review_file = data_dir / REVIEW_VISITS_FILE
        if review_file.exists():
            with open(review_file) as f:
                review_visits = json.load(f)

        # Load saved places
        saved_file = data_dir / SAVED_PLACES_FILE
        if saved_file.exists():
            with open(saved_file) as f:
                saved_places = json.load(f)

        # Load regional centers
        regional_file = data_dir / REGIONAL_CENTERS_FILE
        if regional_file.exists():
            with open(regional_file) as f:
                regional_centers = json.load(f)

        return photo_locations, review_visits, saved_places, regional_centers

    def parse_timestamp(self, timestamp_str: str) -> datetime | None:
        """Parse timestamp string to datetime object, filtering out epoch time"""
        if not timestamp_str:
            return None
        try:
            dt = parse_date(timestamp_str)
            # Filter out epoch time (1970-01-01) as it's not real visit data
            if dt.year == 1970:
                return None
            return dt
        except Exception as e:
            logger.warning(f"Failed to parse timestamp '{timestamp_str}': {e}")
            return None

    def extract_visits_from_photos(self, photo_data: dict) -> list:
        """Extract visit data from photo locations"""
        visits = []

        for region_name, region_info in photo_data.get('regions', {}).items():
            for photo in region_info.get('photos', []):
                timestamp = photo.get('timestamp')
                if not timestamp:
                    continue

                dt = self.parse_timestamp(timestamp)
                if not dt:
                    continue

                places_visited = []
                nearest_place = photo.get('nearest_place')
                if nearest_place:
                    places_visited.append(nearest_place.get('name', 'Unknown'))

                visit = {
                    'region': region_name,
                    'datetime': dt,
                    'date': dt.date(),
                    'source': 'photo',
                    'source_id': photo.get('filename'),
                    'places_visited': places_visited,
                    'coordinates': photo.get('coordinates', {}),
                    'timestamp_str': timestamp,
                }
                visits.append(visit)

        return visits

    def extract_visits_from_reviews(self, review_data: dict) -> list:
        """Extract visit data from review visits"""
        visits = []

        for review in review_data.get('reviews', []):
            timestamp = review.get('review_date')
            region = review.get('region')

            if not timestamp or not region:
                continue

            dt = self.parse_timestamp(timestamp)
            if not dt:
                continue

            visit = {
                'region': region,
                'datetime': dt,
                'date': dt.date(),
                'source': 'review',
                'source_id': review.get('id'),
                'places_visited': [review.get('place_name', 'Unknown')],
                'coordinates': review.get('coordinates', {}),
                'timestamp_str': timestamp,
                'rating': review.get('rating'),
                'review_text_preview': review.get('text_preview', ''),
            }
            visits.append(visit)

        return visits

    def extract_visits_from_saved_places(self, saved_data: dict) -> list:
        """Extract visit data from saved places"""
        visits = []

        for place in saved_data.get('places', []):
            timestamp = place.get('saved_date')
            region = place.get('region')

            if not timestamp or not region:
                continue

            dt = self.parse_timestamp(timestamp)
            if not dt:
                continue

            visit = {
                'region': region,
                'datetime': dt,
                'date': dt.date(),
                'source': 'saved_place',
                'source_id': place.get('id'),
                'places_visited': [place.get('name', 'Unknown')],
                'coordinates': {'latitude': place.get('latitude'), 'longitude': place.get('longitude')},
                'timestamp_str': timestamp,
            }
            visits.append(visit)

        return visits

    def deduplicate_visits(self, visits: list) -> list:
        """Remove duplicate visits within the deduplication window"""
        if not visits:
            return []

        # Sort visits by datetime
        visits.sort(key=lambda v: v['datetime'])

        deduplicated = []

        for visit in visits:
            # Check if this visit is a duplicate of any recent visit to the same region
            is_duplicate = False

            for existing in reversed(deduplicated):
                if existing['region'] != visit['region']:
                    continue

                time_diff = abs((visit['datetime'] - existing['datetime']).total_seconds() / 3600)
                if time_diff <= self.deduplication_window_hours:
                    # This is a duplicate - merge places_visited if different
                    new_places = set(visit['places_visited']) - set(existing['places_visited'])
                    existing['places_visited'].extend(list(new_places))

                    # Keep the source with most information (reviews > photos > saved places)
                    source_priority = {'review': 3, 'photo': 2, 'saved_place': 1}
                    if source_priority.get(visit['source'], 0) > source_priority.get(existing['source'], 0):
                        existing['source'] = visit['source']
                        existing['source_id'] = visit['source_id']
                        if 'rating' in visit:
                            existing['rating'] = visit['rating']
                        if 'review_text_preview' in visit:
                            existing['review_text_preview'] = visit['review_text_preview']

                    is_duplicate = True
                    break

            if not is_duplicate:
                deduplicated.append(visit)

        return deduplicated

    def calculate_visit_stats(self, visits: list) -> dict:
        """Calculate visit statistics for a region"""
        if not visits:
            return {}

        # Sort by datetime
        visits.sort(key=lambda v: v['datetime'])

        first_visit = visits[0]['datetime']
        last_visit = visits[-1]['datetime']

        # Calculate average days between visits
        avg_days_between = 0
        if len(visits) > 1:
            total_days = (last_visit - first_visit).days
            avg_days_between = round(total_days / (len(visits) - 1), 1)

        # Group by year
        visits_by_year = {}
        visits_by_month = {}

        for visit in visits:
            year = str(visit['datetime'].year)
            month = visit['datetime'].strftime('%Y-%m')

            visits_by_year[year] = visits_by_year.get(year, 0) + 1
            visits_by_month[month] = visits_by_month.get(month, 0) + 1

        return {
            'visit_count': len(visits),
            'first_visit': first_visit.isoformat(),
            'last_visit': last_visit.isoformat(),
            'avg_days_between_visits': avg_days_between,
            'visits_by_year': dict(sorted(visits_by_year.items())),
            'visits_by_month': dict(sorted(visits_by_month.items())),
        }

    def generate_timeline(self, data_dir: Path, output_dir: Path) -> bool:
        """Main processing function to generate visit timeline"""
        try:
            # Load all data sources
            photo_data, review_data, saved_data, regional_data = self.load_all_data(data_dir)

            logger.info("Extracting visits from all data sources...")

            # Extract visits from each source
            photo_visits = self.extract_visits_from_photos(photo_data)
            review_visits = self.extract_visits_from_reviews(review_data)
            saved_visits = self.extract_visits_from_saved_places(saved_data)

            logger.info(
                f"Extracted {len(photo_visits)} photo visits, {len(review_visits)} review visits, {len(saved_visits)} saved place visits"
            )

            # Combine all visits
            all_visits = photo_visits + review_visits + saved_visits

            if not all_visits:
                logger.warning("No visits found from any data source")
                return False

            # Group by region and deduplicate
            visits_by_region = {}
            for visit in all_visits:
                region = visit['region']
                if region not in visits_by_region:
                    visits_by_region[region] = []
                visits_by_region[region].append(visit)

            # Deduplicate within each region
            for region in visits_by_region:
                visits_by_region[region] = self.deduplicate_visits(visits_by_region[region])

            # Calculate statistics for each region
            region_timelines = {}
            total_visits = 0
            all_timestamps = []

            for region, visits in visits_by_region.items():
                if not visits:
                    continue

                stats = self.calculate_visit_stats(visits)
                total_visits += len(visits)

                # Prepare visit records for output
                visit_records = []
                for visit in visits:
                    record = {
                        'date': visit['timestamp_str'],
                        'source': visit['source'],
                        'source_id': visit['source_id'],
                        'places_visited': visit['places_visited'],
                    }

                    # Add optional fields if present
                    if 'rating' in visit:
                        record['rating'] = visit['rating']
                    if 'review_text_preview' in visit:
                        record['review_text_preview'] = visit['review_text_preview']

                    visit_records.append(record)
                    all_timestamps.append(visit['datetime'])

                region_timelines[region] = {**stats, 'visits': visit_records}

            # Calculate overall metadata
            all_timestamps.sort()
            date_range = {}
            if all_timestamps:
                date_range = {'first_visit': all_timestamps[0].isoformat(), 'last_visit': all_timestamps[-1].isoformat()}

            # Sort regions by visit count
            region_rankings = sorted(
                [(region, info['visit_count']) for region, info in region_timelines.items()], key=lambda x: x[1], reverse=True
            )

            # Prepare output
            output_dir.mkdir(exist_ok=True)

            timeline_output = {
                'metadata': {
                    'generation_date': datetime.now(UTC).isoformat(),
                    'total_regions': len(region_timelines),
                    'total_visits': total_visits,
                    'date_range': date_range,
                    'deduplication_window_hours': self.deduplication_window_hours,
                    'data_sources': {
                        'photo_visits': len(photo_visits),
                        'review_visits': len(review_visits),
                        'saved_place_visits': len(saved_visits),
                        'total_before_deduplication': len(all_visits),
                    },
                },
                'regions': region_timelines,
                'rankings': {'most_visited_regions': region_rankings[:10]},
            }

            with open(output_dir / VISIT_TIMELINE_FILE, 'w') as f:
                json.dump(timeline_output, f, indent=2)

            logger.info(f"Successfully generated visit timeline for {len(region_timelines)} regions")
            logger.info(f"Total visits after deduplication: {total_visits}")
            logger.info(f"Date range: {date_range.get('first_visit', 'N/A')} to {date_range.get('last_visit', 'N/A')}")
            logger.info(
                f"Top region: {region_rankings[0][0]} ({region_rankings[0][1]} visits)" if region_rankings else "No visits found"
            )
            logger.info(f"Output written to {output_dir / VISIT_TIMELINE_FILE}")

            return True

        except Exception as e:
            logger.error(f"Error generating visit timeline: {e}")
            return False


class SummaryReportGenerator:
    """Generate human-readable markdown summary report from all analyzed data"""

    def __init__(self):
        self.report_lines = []

    def load_all_data(self, data_dir: Path) -> tuple[dict, dict, dict, dict, dict]:
        """Load all processed data sources"""
        visit_timeline = {}
        regional_centers = {}
        saved_places = {}
        photo_locations = {}
        review_visits = {}

        # Load visit timeline (main source)
        timeline_file = data_dir / VISIT_TIMELINE_FILE
        if timeline_file.exists():
            with open(timeline_file) as f:
                visit_timeline = json.load(f)

        # Load regional centers
        regional_file = data_dir / REGIONAL_CENTERS_FILE
        if regional_file.exists():
            with open(regional_file) as f:
                regional_centers = json.load(f)

        # Load saved places
        saved_file = data_dir / SAVED_PLACES_FILE
        if saved_file.exists():
            with open(saved_file) as f:
                saved_places = json.load(f)

        # Load photo locations
        photo_file = data_dir / PHOTO_LOCATIONS_FILE
        if photo_file.exists():
            with open(photo_file) as f:
                photo_locations = json.load(f)

        # Load review visits
        review_file = data_dir / REVIEW_VISITS_FILE
        if review_file.exists():
            with open(review_file) as f:
                review_visits = json.load(f)

        return visit_timeline, regional_centers, saved_places, photo_locations, review_visits

    def generate_header_section(self, timeline_data: dict) -> None:
        """Generate report header with metadata and overview"""
        metadata = timeline_data.get('metadata', {})
        date_range = metadata.get('date_range', {})
        rankings = timeline_data.get('rankings', {})

        generation_date = datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')

        self.report_lines.extend(
            [
                "# Google Maps Travel Analysis Report",
                "",
                f"**Generated:** {generation_date}",
                "**Data Source:** Google Takeout Maps Export",
                f"**Analysis Period:** {date_range.get('first_visit', 'N/A')[:10]} to {date_range.get('last_visit', 'N/A')[:10]}",
                "",
                "## Table of Contents",
                "",
                "- [Overview](#overview)",
                "- [Regional Visit Summary](#regional-visit-summary)",
                "- [Travel Timeline](#travel-timeline)",
                "- [Travel Insights](#travel-insights)",
                "- [Data Sources](#data-sources)",
                "",
                "## Overview",
                "",
                f"- **Total Regions Visited:** {metadata.get('total_regions', 0)}",
                f"- **Total Recorded Visits:** {metadata.get('total_visits', 0)}",
                f"- **Photo Visits:** {metadata.get('data_sources', {}).get('photo_visits', 0)}",
                f"- **Review Visits:** {metadata.get('data_sources', {}).get('review_visits', 0)}",
                f"- **Saved Place Visits:** {metadata.get('data_sources', {}).get('saved_place_visits', 0)}",
            ]
        )

        # Add top region if available
        top_regions = rankings.get('most_visited_regions', [])
        if top_regions:
            top_region, top_visits = top_regions[0]
            self.report_lines.append(f"- **Most Visited Region:** {top_region} ({top_visits} visits)")

        self.report_lines.append("")

    def calculate_days_since_last_visit(self, last_visit_str: str) -> int:
        """Calculate days since last visit"""
        try:
            last_visit = parse_date(last_visit_str)
            now = datetime.now(UTC)
            return (now - last_visit).days
        except Exception:
            return -1

    def count_photos_and_places_for_region(self, region_name: str, photo_data: dict, saved_data: dict) -> tuple[int, int]:
        """Count photos and saved places for a region"""
        photo_count = 0
        place_count = 0

        # Count photos from photo locations data
        region_photos = photo_data.get('regions', {}).get(region_name, {}).get('photos', [])
        photo_count = len(region_photos)

        # Count saved places for this region
        saved_places = saved_data.get('places', [])
        place_count = sum(1 for place in saved_places if place.get('region') == region_name)

        return photo_count, place_count

    def generate_regional_summary_section(self, timeline_data: dict, photo_data: dict, saved_data: dict) -> None:
        """Generate regional visit summary table"""
        regions = timeline_data.get('regions', {})

        self.report_lines.extend(
            [
                "## Regional Visit Summary",
                "",
                "| Region | Visits | First Visit | Last Visit | Days Since | Photos | Places |",
                "|--------|--------|-------------|------------|------------|--------|--------|",
            ]
        )

        # Sort regions by visit count (descending)
        sorted_regions = sorted(regions.items(), key=lambda x: x[1].get('visit_count', 0), reverse=True)

        for region_name, region_info in sorted_regions[:25]:  # Top 25 regions
            visits = region_info.get('visit_count', 0)
            first_visit = region_info.get('first_visit', 'N/A')[:10] if region_info.get('first_visit') else 'N/A'
            last_visit = region_info.get('last_visit', 'N/A')[:10] if region_info.get('last_visit') else 'N/A'

            days_since = self.calculate_days_since_last_visit(region_info.get('last_visit', ''))
            days_since_str = str(days_since) if days_since >= 0 else 'N/A'

            photo_count, place_count = self.count_photos_and_places_for_region(region_name, photo_data, saved_data)

            self.report_lines.append(
                f"| {region_name} | {visits} | {first_visit} | {last_visit} | {days_since_str} | {photo_count} | {place_count} |"
            )

        self.report_lines.append("")

    def generate_timeline_section(self, timeline_data: dict) -> None:
        """Generate visual timeline representations"""
        regions = timeline_data.get('regions', {})

        self.report_lines.extend(["## Travel Timeline", "", "### Visit Activity by Year", ""])

        # Aggregate visits by year across all regions
        year_totals = {}
        for region_info in regions.values():
            visits_by_year = region_info.get('visits_by_year', {})
            for year, count in visits_by_year.items():
                year_totals[year] = year_totals.get(year, 0) + count

        # Create ASCII chart for yearly visits
        if year_totals:
            max_visits = max(year_totals.values())
            scale_factor = 50 / max_visits if max_visits > 0 else 1

            self.report_lines.append("```")
            for year in sorted(year_totals.keys()):
                visits = year_totals[year]
                bar_length = max(1, int(visits * scale_factor))
                bar = "█" * bar_length
                self.report_lines.append(f"{year}: {bar} ({visits} visits)")
            self.report_lines.extend(["```", ""])

        # Top 10 most visited regions timeline
        sorted_regions = sorted(regions.items(), key=lambda x: x[1].get('visit_count', 0), reverse=True)

        self.report_lines.extend(["### Top 10 Most Visited Regions", ""])

        for i, (region_name, region_info) in enumerate(sorted_regions[:10]):
            visits = region_info.get('visit_count', 0)
            first_visit = region_info.get('first_visit', 'N/A')[:10] if region_info.get('first_visit') else 'N/A'
            last_visit = region_info.get('last_visit', 'N/A')[:10] if region_info.get('last_visit') else 'N/A'
            avg_days = region_info.get('avg_days_between_visits', 0)

            intensity_emoji = "🔥" if visits > 50 else "⭐" if visits > 20 else "📍"

            self.report_lines.extend(
                [
                    f"**{i + 1}. {region_name}** {intensity_emoji}",
                    f"- **{visits} visits** | First: {first_visit} | Last: {last_visit}",
                    f"- Average {avg_days} days between visits",
                    "",
                ]
            )

    def generate_insights_section(self, timeline_data: dict) -> None:
        """Generate travel insights and patterns"""
        regions = timeline_data.get('regions', {})
        metadata = timeline_data.get('metadata', {})

        self.report_lines.extend(["## Travel Insights", ""])

        # Recent vs old regions
        recent_regions = []
        old_regions = []
        now = datetime.now(UTC)

        for region_name, region_info in regions.items():
            last_visit_str = region_info.get('last_visit')
            if last_visit_str:
                try:
                    last_visit = parse_date(last_visit_str)
                    days_since = (now - last_visit).days
                    if days_since > 365:
                        old_regions.append((region_name, days_since))
                    elif days_since <= 90:
                        recent_regions.append((region_name, days_since))
                except Exception:
                    continue

        # Sort by recency
        recent_regions.sort(key=lambda x: x[1])
        old_regions.sort(key=lambda x: x[1], reverse=True)

        self.report_lines.extend(["### Recent Travel Activity (Last 90 Days)", ""])

        if recent_regions:
            for region, days_ago in recent_regions[:10]:
                self.report_lines.append(f"- **{region}** - {days_ago} days ago")
        else:
            self.report_lines.append("- No recent travel activity recorded")

        self.report_lines.extend(["", "### Regions Not Visited in Over 1 Year", ""])

        if old_regions:
            for region, days_ago in old_regions[:15]:
                years_ago = round(days_ago / 365.25, 1)
                self.report_lines.append(f"- **{region}** - {years_ago} years ago")
        else:
            self.report_lines.append("- All regions visited within the last year")

        # Travel frequency patterns
        total_visits = metadata.get('total_visits', 0)
        total_regions = metadata.get('total_regions', 0)

        if total_regions > 0:
            avg_visits_per_region = round(total_visits / total_regions, 1)

            self.report_lines.extend(
                [
                    "",
                    "### Travel Patterns",
                    "",
                    f"- **Average visits per region:** {avg_visits_per_region}",
                    f"- **Total unique destinations:** {total_regions}",
                    f"- **Total recorded visits:** {total_visits}",
                ]
            )

    def generate_data_sources_section(self, metadata: dict) -> None:
        """Generate data sources and methodology section"""
        data_sources = metadata.get('data_sources', {})

        self.report_lines.extend(
            [
                "",
                "## Data Sources",
                "",
                "This report was generated from Google Takeout Maps data including:",
                "",
                f"- **{data_sources.get('photo_visits', 0)} photo visits** - Extracted from geotagged photo metadata",
                f"- **{data_sources.get('review_visits', 0)} review visits** - Based on Google Maps review timestamps",
                f"- **{data_sources.get('saved_place_visits', 0)} saved place visits** - From bookmarked locations with save dates",
                "",
                "### Processing Notes",
                "",
                "- Visits within 24 hours to the same region are deduplicated",
                "- Epoch time timestamps (1970-01-01) are filtered out as system artifacts",
                "- Geographic clustering groups nearby locations into regions",
                "- Distance calculations use geodesic (great circle) measurements",
                "",
                "### Data Files",
                "",
                f"- [`{VISIT_TIMELINE_FILE}`]({VISIT_TIMELINE_FILE}) - Complete visit timeline data",
                f"- [`{REGIONAL_CENTERS_FILE}`]({REGIONAL_CENTERS_FILE}) - Regional clustering results",
                f"- [`{SAVED_PLACES_FILE}`]({SAVED_PLACES_FILE}) - Processed saved places",
                f"- [`{PHOTO_LOCATIONS_FILE}`]({PHOTO_LOCATIONS_FILE}) - Photo geolocation correlations",
                f"- [`{REVIEW_VISITS_FILE}`]({REVIEW_VISITS_FILE}) - Review visit confirmations",
                "",
                f"**Report Generated:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
                "",
            ]
        )

    def generate_report(self, data_dir: Path, output_dir: Path) -> bool:
        """Main processing function to generate summary report"""
        try:
            # Load all data
            timeline_data, regional_data, saved_data, photo_data, review_data = self.load_all_data(data_dir)

            if not timeline_data.get('regions'):
                logger.error("No timeline data found")
                return False

            logger.info("Generating summary report sections...")

            # Generate each section
            self.generate_header_section(timeline_data)
            self.generate_regional_summary_section(timeline_data, photo_data, saved_data)
            self.generate_timeline_section(timeline_data)
            self.generate_insights_section(timeline_data)
            self.generate_data_sources_section(timeline_data.get('metadata', {}))

            # Write output
            output_dir.mkdir(exist_ok=True)

            with open(output_dir / SUMMARY_REPORT_FILE, 'w') as f:
                f.write('\n'.join(self.report_lines))

            logger.info(f"Successfully generated summary report with {len(self.report_lines)} lines")
            logger.info(f"Report covers {len(timeline_data.get('regions', {}))} regions")
            logger.info(f"Output written to {output_dir / SUMMARY_REPORT_FILE}")

            return True

        except Exception as e:
            logger.error(f"Error generating summary report: {e}")
            return False


class DataAnalysisPipeline:
    """Orchestrates the complete data analysis pipeline"""

    def __init__(self, input_dir: Path = INPUT_DIR, output_dir: Path = OUTPUT_DIR, dry_run: bool = False):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.dry_run = dry_run
        # Create pipeline steps by adding function references to the imported steps
        self.pipeline_steps = []
        function_map = {
            'extract-labeled-places': self._run_labeled_places,
            'extract-saved-places': self._run_saved_places,
            'extract-photo-metadata': self._run_photo_metadata,
            'correlate-photos-to-regions': self._run_photo_correlation,
            'extract-review-visits': self._run_review_visits,
            'generate-visit-timeline': self._run_visit_timeline,
            'generate-summary-report': self._run_summary_report,
        }

        for step in PIPELINE_STEPS:
            step_with_function = step.copy()
            step_with_function['function'] = function_map[step['name']]
            self.pipeline_steps.append(step_with_function)

    def check_prerequisites(self) -> tuple[bool, list[str]]:
        """Check if all required input files exist"""
        missing_files = []

        for step in self.pipeline_steps:
            for required_file in step['required_files']:
                file_path = self.input_dir / required_file
                if not file_path.exists():
                    missing_files.append(str(file_path))

        return len(missing_files) == 0, missing_files

    def check_step_dependencies(self, step_name: str) -> bool:
        """Check if a step's dependencies are satisfied"""
        step = next((s for s in self.pipeline_steps if s['name'] == step_name), None)
        if not step:
            return False

        dependencies = step.get('dependencies', [])
        for dep in dependencies:
            dep_step = next((s for s in self.pipeline_steps if s['name'] == dep), None)
            if not dep_step:
                continue

            # Check if dependency outputs exist
            for output_file in dep_step['output_files']:
                if not (self.output_dir / output_file).exists():
                    return False

        return True

    def get_next_runnable_steps(self, completed_steps: set[str]) -> list[dict]:
        """Get list of steps that can be run next"""
        runnable = []

        for step in self.pipeline_steps:
            if step['name'] in completed_steps:
                continue

            dependencies = step.get('dependencies', [])
            if all(dep in completed_steps for dep in dependencies):
                runnable.append(step)

        return runnable

    def run_pipeline(self, resume: bool = False) -> bool:
        """Execute the complete data analysis pipeline"""
        logger.info("Starting Oh My Stars data analysis pipeline")

        if self.dry_run:
            logger.info("DRY RUN MODE - No files will be modified")

        # Check prerequisites
        prerequisites_ok, missing_files = self.check_prerequisites()
        if not prerequisites_ok:
            logger.error("Missing required input files:")
            for file_path in missing_files:
                logger.error(f"  - {file_path}")
            return False

        # Determine completed steps if resuming
        completed_steps = set()
        if resume:
            for step in self.pipeline_steps:
                output_exists = all((self.output_dir / output_file).exists() for output_file in step['output_files'])
                if output_exists:
                    completed_steps.add(step['name'])
                    logger.info(f"Step '{step['name']}' already completed - skipping")

        # Execute pipeline steps
        total_steps = len(self.pipeline_steps)

        while len(completed_steps) < total_steps:
            runnable_steps = self.get_next_runnable_steps(completed_steps)

            if not runnable_steps:
                logger.error("No runnable steps found - pipeline may have circular dependencies")
                return False

            # Execute next step
            step = runnable_steps[0]  # Execute steps one at a time for now
            step_num = len(completed_steps) + 1

            logger.info(f"[{step_num}/{total_steps}] Executing: {step['description']}")

            if self.dry_run:
                logger.info(f"DRY RUN: Would execute {step['name']}")
                completed_steps.add(step['name'])
                continue

            try:
                success = step['function']()
                if success:
                    completed_steps.add(step['name'])
                    logger.info(f"✓ Completed: {step['name']}")
                else:
                    logger.error(f"✗ Failed: {step['name']}")
                    return False
            except Exception as e:
                logger.error(f"✗ Error in {step['name']}: {e}")
                return False

        logger.info("🎉 Pipeline completed successfully!")
        logger.info(f"📊 Generated analysis report: {self.output_dir / SUMMARY_REPORT_FILE}")

        return True

    def _run_labeled_places(self) -> bool:
        """Execute labeled places extraction"""
        input_file = self.input_dir / "saved/My labeled places/Labeled places.json"
        extractor = LabeledPlacesExtractor()
        return extractor.process_labeled_places(input_file, self.output_dir)

    def _run_saved_places(self) -> bool:
        """Execute saved places extraction"""
        input_file = self.input_dir / "your_places/saved_places.json"
        extractor = SavedPlacesExtractor()
        return extractor.process_saved_places(input_file, self.output_dir)

    def _run_photo_metadata(self) -> bool:
        """Execute photo metadata extraction"""
        photos_dir = self.input_dir / "saved/Photos and videos"
        extractor = PhotoMetadataExtractor()
        return extractor.process_photo_metadata(photos_dir, self.output_dir)

    def _run_photo_correlation(self) -> bool:
        """Execute photo to region correlation"""
        correlator = PhotoLocationCorrelator()
        return correlator.correlate_photos_to_locations(self.output_dir, self.output_dir)

    def _run_review_visits(self) -> bool:
        """Execute review visits extraction"""
        reviews_file = self.input_dir / "your_places/reviews.json"
        extractor = ReviewVisitsExtractor()
        return extractor.extract_review_visits(reviews_file, self.output_dir, self.output_dir)

    def _run_visit_timeline(self) -> bool:
        """Execute visit timeline generation"""
        generator = VisitTimelineGenerator()
        return generator.generate_timeline(self.output_dir, self.output_dir)

    def _run_summary_report(self) -> bool:
        """Execute summary report generation"""
        generator = SummaryReportGenerator()
        return generator.generate_report(self.output_dir, self.output_dir)


class DataValidator:
    """Comprehensive data validation and testing utilities"""

    def __init__(self, input_dir: Path = INPUT_DIR, output_dir: Path = OUTPUT_DIR):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.validation_results = {
            'input_validation': {},
            'processing_validation': {},
            'output_validation': {},
            'errors': [],
            'warnings': [],
            'summary': {},
        }

    def is_valid_coordinate(self, lat: float, lon: float) -> bool:
        """Validate coordinate ranges"""
        return MIN_VALID_LATITUDE <= lat <= MAX_VALID_LATITUDE and MIN_VALID_LONGITUDE <= lon <= MAX_VALID_LONGITUDE

    def is_valid_timestamp(self, timestamp_str: str) -> bool:
        """Validate timestamp format and range"""
        try:
            dt = parse_date(timestamp_str)
            # Reasonable date range: 1990 to 2030
            return MIN_VALID_YEAR <= dt.year <= MAX_VALID_YEAR
        except Exception:
            return False

    def validate_json_structure(self, file_path: Path, required_keys: list[str]) -> dict:
        """Validate JSON file structure"""
        result = {
            'valid': True,
            'exists': file_path.exists(),
            'readable': False,
            'valid_json': False,
            'has_required_keys': False,
            'missing_keys': [],
            'file_size': 0,
            'record_count': 0,
        }

        if not result['exists']:
            result['valid'] = False
            return result

        try:
            result['file_size'] = file_path.stat().st_size

            with open(file_path) as f:
                data = json.load(f)

            result['readable'] = True
            result['valid_json'] = True

            # Check required keys
            if isinstance(data, dict):
                missing_keys = [key for key in required_keys if key not in data]
                result['missing_keys'] = missing_keys
                result['has_required_keys'] = len(missing_keys) == 0

                # Count records
                if 'features' in data:
                    result['record_count'] = len(data['features'])
                elif 'places' in data:
                    result['record_count'] = len(data['places'])
                elif 'regions' in data:
                    result['record_count'] = len(data['regions'])
                else:
                    result['record_count'] = len(data) if isinstance(data, list) else 1

            result['valid'] = result['has_required_keys']

        except json.JSONDecodeError:
            result['valid'] = False
            result['readable'] = True
            result['valid_json'] = False
        except Exception:
            result['valid'] = False
            result['readable'] = False

        return result

    def validate_input_files(self) -> bool:
        """Validate all input files"""
        logger.info("Validating input files...")

        input_files = {
            'labeled_places': {
                'path': self.input_dir / 'saved/My labeled places/Labeled places.json',
                'required_keys': ['features'],
            },
            'saved_places': {'path': self.input_dir / 'your_places/saved_places.json', 'required_keys': ['features']},
            'reviews': {'path': self.input_dir / 'your_places/reviews.json', 'required_keys': ['features']},
        }

        all_valid = True

        for file_type, file_config in input_files.items():
            result = self.validate_json_structure(file_config['path'], file_config['required_keys'])
            self.validation_results['input_validation'][file_type] = result

            if not result['valid']:
                all_valid = False
                if not result['exists']:
                    self.validation_results['warnings'].append(f"Optional file missing: {file_config['path']}")
                else:
                    self.validation_results['errors'].append(f"Invalid {file_type}: {result['missing_keys']}")

        # Validate photo directory
        photos_dir = self.input_dir / 'saved/Photos and videos'
        photos_result = {
            'exists': photos_dir.exists(),
            'is_directory': photos_dir.is_dir() if photos_dir.exists() else False,
            'file_count': 0,
            'json_files': 0,
        }

        if photos_result['exists'] and photos_result['is_directory']:
            json_files = list(photos_dir.glob('*.json'))
            photos_result['file_count'] = len(list(photos_dir.iterdir()))
            photos_result['json_files'] = len(json_files)

        self.validation_results['input_validation']['photos_directory'] = photos_result

        return all_valid

    def validate_coordinates_in_data(self) -> bool:
        """Validate coordinates in all data sources"""
        logger.info("Validating coordinates...")

        coordinate_errors = []
        total_coordinates = 0
        invalid_coordinates = 0

        # Check saved places
        saved_places_file = self.output_dir / SAVED_PLACES_FILE
        if saved_places_file.exists():
            with open(saved_places_file) as f:
                data = json.load(f)

            for place in data.get('places', []):
                lat = place.get('latitude')
                lon = place.get('longitude')

                if lat is not None and lon is not None:
                    total_coordinates += 1
                    if not self.is_valid_coordinate(lat, lon):
                        invalid_coordinates += 1
                        coordinate_errors.append(
                            f"Invalid coordinates in saved place {place.get('id', 'unknown')}: ({lat}, {lon})"
                        )

        # Check photo metadata
        photo_file = self.output_dir / 'photo_metadata.json'
        if photo_file.exists():
            with open(photo_file) as f:
                data = json.load(f)

            for photo in data.get('photos', []):
                coords = photo.get('coordinates') or {}
                lat = coords.get('latitude')
                lon = coords.get('longitude')

                if lat is not None and lon is not None:
                    total_coordinates += 1
                    if not self.is_valid_coordinate(lat, lon):
                        invalid_coordinates += 1
                        coordinate_errors.append(
                            f"Invalid coordinates in photo {photo.get('filename', 'unknown')}: ({lat}, {lon})"
                        )

        self.validation_results['processing_validation']['coordinates'] = {
            'total_coordinates': total_coordinates,
            'invalid_coordinates': invalid_coordinates,
            'error_rate': (invalid_coordinates / total_coordinates * 100) if total_coordinates > 0 else 0,
            'errors': coordinate_errors[:10],  # Limit to first 10 errors
        }

        self.validation_results['errors'].extend(coordinate_errors)

        return invalid_coordinates == 0

    def validate_regional_assignments(self) -> bool:
        """Validate regional assignments and distance calculations"""
        logger.info("Validating regional assignments...")

        regional_file = self.output_dir / 'regional_centers.json'
        photo_locations_file = self.output_dir / PHOTO_LOCATIONS_FILE

        if not regional_file.exists() or not photo_locations_file.exists():
            self.validation_results['warnings'].append("Regional assignment files not found for validation")
            return True

        with open(regional_file) as f:
            regional_data = json.load(f)

        with open(photo_locations_file) as f:
            photo_data = json.load(f)

        assignment_errors = []
        total_assignments = 0
        invalid_assignments = 0

        for region_name, region_info in photo_data.get('regions', {}).items():
            region_center = regional_data.get('regions', {}).get(region_name, {}).get('center', {})

            if not region_center:
                continue

            center_lat = region_center.get('latitude')
            center_lon = region_center.get('longitude')

            for photo in region_info.get('photos', []):
                photo_coords = photo.get('coordinates', {})
                photo_lat = photo_coords.get('latitude')
                photo_lon = photo_coords.get('longitude')

                if all(coord is not None for coord in [center_lat, center_lon, photo_lat, photo_lon]):
                    total_assignments += 1

                    # Calculate distance
                    distance = geodesic((photo_lat, photo_lon), (center_lat, center_lon)).miles

                    # Check if assignment is reasonable (within 50 miles as a liberal threshold)
                    if distance > 50:
                        invalid_assignments += 1
                        assignment_errors.append(
                            f"Photo {photo.get('filename', 'unknown')} assigned to distant region {region_name}: {distance:.1f} miles"
                        )

        self.validation_results['processing_validation']['regional_assignments'] = {
            'total_assignments': total_assignments,
            'invalid_assignments': invalid_assignments,
            'error_rate': (invalid_assignments / total_assignments * 100) if total_assignments > 0 else 0,
            'errors': assignment_errors[:10],
        }

        self.validation_results['errors'].extend(assignment_errors)

        return invalid_assignments == 0

    def validate_output_files(self) -> bool:
        """Validate all output files"""
        logger.info("Validating output files...")

        output_files = {
            'labeled_places': {'path': self.output_dir / LABELED_PLACES_FILE, 'required_keys': ['metadata', 'places']},
            'regional_centers': {'path': self.output_dir / REGIONAL_CENTERS_FILE, 'required_keys': ['metadata', 'regions']},
            'saved_places': {'path': self.output_dir / SAVED_PLACES_FILE, 'required_keys': ['metadata', 'places']},
            'photo_metadata': {'path': self.output_dir / PHOTO_METADATA_FILE, 'required_keys': ['metadata', 'photos']},
            'photo_locations': {'path': self.output_dir / PHOTO_LOCATIONS_FILE, 'required_keys': ['metadata', 'regions']},
            'review_visits': {'path': self.output_dir / REVIEW_VISITS_FILE, 'required_keys': ['metadata', 'reviews']},
            'visit_timeline': {'path': self.output_dir / VISIT_TIMELINE_FILE, 'required_keys': ['metadata', 'regions']},
        }

        all_valid = True

        for file_type, file_config in output_files.items():
            result = self.validate_json_structure(file_config['path'], file_config['required_keys'])
            self.validation_results['output_validation'][file_type] = result

            if not result['valid']:
                all_valid = False
                if not result['exists']:
                    self.validation_results['errors'].append(f"Missing output file: {file_config['path']}")
                else:
                    self.validation_results['errors'].append(f"Invalid output {file_type}: {result['missing_keys']}")

        # Validate summary report
        summary_report = self.output_dir / SUMMARY_REPORT_FILE
        report_result = {
            'exists': summary_report.exists(),
            'size': summary_report.stat().st_size if summary_report.exists() else 0,
            'valid': False,
        }

        if report_result['exists'] and report_result['size'] > 0:
            # Basic markdown validation
            try:
                with open(summary_report) as f:
                    content = f.read()
                    report_result['valid'] = '# Google Maps Travel Analysis Report' in content
            except Exception:
                report_result['valid'] = False

        self.validation_results['output_validation']['summary_report'] = report_result

        return all_valid

    def validate_cache_integrity(self) -> bool:
        """Validate geocoding cache integrity"""
        logger.info("Validating cache integrity...")

        cache_file = self.output_dir / 'geocoding_cache.json'

        if not cache_file.exists():
            self.validation_results['warnings'].append("Geocoding cache not found")
            return True

        cache_result = self.validate_json_structure(cache_file, ['metadata', 'entries'])
        self.validation_results['processing_validation']['cache'] = cache_result

        if not cache_result['valid']:
            self.validation_results['errors'].append("Invalid geocoding cache structure")
            return False

        # Validate cache entries
        try:
            with open(cache_file) as f:
                cache_data = json.load(f)

            invalid_entries = 0
            total_entries = len(cache_data.get('entries', {}))

            for entry in cache_data.get('entries', {}).values():
                if not isinstance(entry, dict) or 'timestamp' not in entry or not self.is_valid_timestamp(entry['timestamp']):
                    invalid_entries += 1

            cache_result['invalid_entries'] = invalid_entries
            cache_result['valid_entries'] = total_entries - invalid_entries

            if invalid_entries > 0:
                self.validation_results['warnings'].append(f"Found {invalid_entries} invalid cache entries")

        except Exception as e:
            self.validation_results['errors'].append(f"Error validating cache entries: {e}")
            return False

        return True

    def run_full_validation(self) -> bool:
        """Run complete validation suite"""
        logger.info("Running full data validation suite...")

        # Run all validation checks
        input_valid = self.validate_input_files()
        coord_valid = self.validate_coordinates_in_data()
        regional_valid = self.validate_regional_assignments()
        output_valid = self.validate_output_files()
        cache_valid = self.validate_cache_integrity()

        # Generate summary
        self.validation_results['summary'] = {
            'input_validation': input_valid,
            'coordinate_validation': coord_valid,
            'regional_validation': regional_valid,
            'output_validation': output_valid,
            'cache_validation': cache_valid,
            'overall_valid': all([input_valid, coord_valid, regional_valid, output_valid, cache_valid]),
            'total_errors': len(self.validation_results['errors']),
            'total_warnings': len(self.validation_results['warnings']),
        }

        return self.validation_results['summary']['overall_valid']

    def generate_validation_report(self) -> str:
        """Generate detailed validation report"""
        lines = [
            "# Data Validation Report",
            "",
            f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "## Summary",
            "",
        ]

        summary = self.validation_results['summary']
        status_emoji = "✅" if summary.get('overall_valid', False) else "❌"

        lines.extend(
            [
                f"{status_emoji} **Overall Status:** {'VALID' if summary.get('overall_valid', False) else 'INVALID'}",
                f"- **Errors:** {summary.get('total_errors', 0)}",
                f"- **Warnings:** {summary.get('total_warnings', 0)}",
                "",
            ]
        )

        # Validation sections
        sections = [
            ('Input Validation', 'input_validation'),
            ('Coordinate Validation', 'coordinate_validation'),
            ('Regional Assignment Validation', 'regional_validation'),
            ('Output Validation', 'output_validation'),
            ('Cache Validation', 'cache_validation'),
        ]

        for section_name, section_key in sections:
            status = "✅ PASS" if summary.get(section_key, False) else "❌ FAIL"
            lines.extend([f"### {section_name}", f"**Status:** {status}", ""])

        # Error details
        if self.validation_results['errors']:
            lines.extend(["## Errors", ""])
            for error in self.validation_results['errors'][:20]:  # Limit to first 20
                lines.append(f"- {error}")
            lines.append("")

        # Warning details
        if self.validation_results['warnings']:
            lines.extend(["## Warnings", ""])
            for warning in self.validation_results['warnings'][:20]:  # Limit to first 20
                lines.append(f"- {warning}")
            lines.append("")

        return '\n'.join(lines)


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Oh My Stars - Google Takeout Maps Data Processor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument('command', nargs='?', default='run-pipeline', help='Command to execute (default: run-pipeline)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging output')
    parser.add_argument('--input-dir', type=Path, default=INPUT_DIR, help='Path to Google Takeout data directory')
    parser.add_argument('--output-dir', type=Path, default=OUTPUT_DIR, help='Path to output directory')
    parser.add_argument('--resume', action='store_true', help='Resume pipeline from last completed step')

    # Extract takeout specific options
    parser.add_argument('--zip-file', type=str, help='Path to takeout zip file (auto-detected if not provided)')
    parser.add_argument('--cleanup', action='store_true', help='Delete original zip file after successful extraction')

    return parser.parse_args()


def setup_logging(verbose: bool = False):
    """Configure logging based on verbosity level"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format='%(asctime)s - %(levelname)s - %(message)s', force=True)


def main():
    args = parse_arguments()

    # Setup logging
    setup_logging(args.verbose)

    command = args.command

    # Handle extract takeout command
    if command == "extract-takeout":
        extractor = TakeoutExtractor()
        zip_path = Path(args.zip_file) if hasattr(args, 'zip_file') and args.zip_file else None
        cleanup = getattr(args, 'cleanup', False)
        success = extractor.extract_takeout(zip_path=zip_path, cleanup=cleanup)
        sys.exit(0 if success else 1)

    # Handle pipeline command
    elif command == "run-pipeline":
        pipeline = DataAnalysisPipeline(input_dir=args.input_dir, output_dir=args.output_dir, dry_run=args.dry_run)
        success = pipeline.run_pipeline(resume=args.resume)
        sys.exit(0 if success else 1)

    # Handle validation commands
    elif command == "validate-data":
        validator = DataValidator(input_dir=args.input_dir, output_dir=args.output_dir)

        if args.dry_run:
            logger.info("DRY RUN: Would run full data validation suite")
            sys.exit(0)

        success = validator.run_full_validation()

        # Generate and save validation report
        report = validator.generate_validation_report()
        report_file = args.output_dir / VALIDATION_REPORT_FILE

        try:
            args.output_dir.mkdir(exist_ok=True)
            with open(report_file, 'w') as f:
                f.write(report)
            logger.info(f"Validation report written to {report_file}")
        except Exception as e:
            logger.error(f"Failed to write validation report: {e}")

        # Print summary
        summary = validator.validation_results['summary']
        status = "✅ VALID" if success else "❌ INVALID"
        print("\n=== Data Validation Results ===")
        print(f"Overall Status: {status}")
        print(f"Errors: {summary.get('total_errors', 0)}")
        print(f"Warnings: {summary.get('total_warnings', 0)}")
        print(f"Report: {report_file}")

        sys.exit(0 if success else 1)

    # Legacy command handling for backwards compatibility
    # TODO: glob for default filename
    if command == "extract-labeled-places":
        input_file = args.input_dir / "saved/My labeled places/Labeled places.json"
        output_dir = args.output_dir

        if not input_file.exists():
            logger.error(f"Input file not found: {input_file}")
            sys.exit(1)

        extractor = LabeledPlacesExtractor()
        success = extractor.process_labeled_places(input_file, output_dir)
        sys.exit(0 if success else 1)

    elif command == "extract-saved-places":
        input_file = args.input_dir / "your_places/saved_places.json"
        output_dir = args.output_dir

        if not input_file.exists():
            logger.error(f"Input file not found: {input_file}")
            sys.exit(1)

        extractor = SavedPlacesExtractor()
        success = extractor.process_saved_places(input_file, output_dir)
        sys.exit(0 if success else 1)

    elif command == "extract-photo-metadata":
        photos_dir = args.input_dir / "saved/Photos and videos"
        output_dir = args.output_dir

        if not photos_dir.exists():
            logger.error(f"Photos directory not found: {photos_dir}")
            sys.exit(1)

        extractor = PhotoMetadataExtractor()
        success = extractor.process_photo_metadata(photos_dir, output_dir)
        sys.exit(0 if success else 1)

    elif command == "correlate-photos-to-regions":
        data_dir = args.output_dir
        output_dir = args.output_dir

        if not data_dir.exists():
            logger.error(f"Data directory not found: {data_dir}")
            sys.exit(1)

        correlator = PhotoLocationCorrelator()
        success = correlator.correlate_photos_to_locations(data_dir, output_dir)
        sys.exit(0 if success else 1)

    elif command == "extract-review-visits":
        reviews_file = args.input_dir / "your_places/reviews.json"
        data_dir = args.output_dir
        output_dir = args.output_dir

        if not reviews_file.exists():
            logger.error(f"Reviews file not found: {reviews_file}")
            sys.exit(1)

        if not data_dir.exists():
            logger.error(f"Data directory not found: {data_dir}")
            sys.exit(1)

        extractor = ReviewVisitsExtractor()
        success = extractor.extract_review_visits(reviews_file, data_dir, output_dir)
        sys.exit(0 if success else 1)

    elif command == "generate-visit-timeline":
        data_dir = args.output_dir
        output_dir = args.output_dir

        if not data_dir.exists():
            logger.error(f"Data directory not found: {data_dir}")
            sys.exit(1)

        generator = VisitTimelineGenerator()
        success = generator.generate_timeline(data_dir, output_dir)
        sys.exit(0 if success else 1)

    elif command == "generate-summary-report":
        data_dir = args.output_dir
        output_dir = args.output_dir

        if not data_dir.exists():
            logger.error(f"Data directory not found: {data_dir}")
            sys.exit(1)

        generator = SummaryReportGenerator()
        success = generator.generate_report(data_dir, output_dir)
        sys.exit(0 if success else 1)

    elif command == "cache-stats":
        cache = GeocodingCache()
        stats = cache.get_stats()

        print("\n=== Geocoding Cache Statistics ===")
        print(f"Total entries: {stats['total_entries']}")
        print(f"Cache hits: {stats['cache_hits']}")
        print(f"Cache misses: {stats['cache_misses']}")
        print(f"Hit ratio: {stats['hit_ratio_percent']}%")
        print(f"Session hits: {stats['session_hits']}")
        print(f"Session misses: {stats['session_misses']}")
        print(f"Expiration: {stats['expiration_days']} days")
        print(f"Created: {stats['created']}")
        print(f"Last updated: {stats['last_updated']}")

        # Clean expired entries
        expired_count = cache.clean_expired()
        if expired_count > 0:
            print(f"Cleaned {expired_count} expired entries")

        sys.exit(0)

    elif command == "cache-clear":
        cache = GeocodingCache()
        cache.clear()
        print("Cache cleared successfully")
        sys.exit(0)

    else:
        print(__doc__.strip())


if __name__ == "__main__":
    main()
