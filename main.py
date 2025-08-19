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
    extract-photo-metadata: Extract geolocation data from photo metadata
    correlate-photos-to-regions: Match geotagged photos to regions and saved places
    extract-review-visits: Extract review timestamps as visit confirmations
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


class PhotoMetadataExtractor:
    """Extract geolocation data from photo metadata JSON files"""
    
    def __init__(self):
        pass
    
    def validate_coordinates(self, lat: float, lon: float) -> bool:
        """Validate coordinate ranges"""
        return -90 <= lat <= 90 and -180 <= lon <= 180
    
    def parse_timestamp_from_epoch(self, timestamp_str: str) -> str | None:
        """Convert epoch timestamp to ISO format"""
        try:
            # Handle both string and integer timestamps
            timestamp = int(timestamp_str)
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            return dt.isoformat()
        except Exception as e:
            logger.warning(f"Failed to parse epoch timestamp '{timestamp_str}': {e}")
            return None
    
    def process_photo_metadata(self, photos_dir: Path, output_dir: Path) -> bool:
        """Main processing function for photo metadata"""
        try:
            # Find all JSON metadata files
            json_files = list(photos_dir.glob("*.json"))
            
            if not json_files:
                logger.error(f"No JSON metadata files found in {photos_dir}")
                return False
            
            logger.info(f"Found {len(json_files)} metadata files to process")
            
            photos = []
            geotagged_count = 0
            timestamps = []
            
            for i, json_file in enumerate(json_files):
                if i % 10 == 0 and i > 0:
                    logger.info(f"Processing file {i+1}/{len(json_files)} ({(i+1)/len(json_files)*100:.1f}%)")
                
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
                        'image_views': metadata.get('imageViews', '0')
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
                                    'altitude': geo_data.get('altitude', None)
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
                date_range = {
                    'earliest': timestamps[0],
                    'latest': timestamps[-1]
                }
            
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
                    'date_range': date_range
                },
                'photos': photos
            }
            
            with open(output_dir / 'photo_metadata.json', 'w') as f:
                json.dump(photo_metadata_output, f, indent=2)
            
            logger.info(f"Successfully processed {total_photos} photo metadata files")
            logger.info(f"Found {geotagged_count} geotagged photos ({(geotagged_count/total_photos*100):.1f}%)")
            logger.info(f"Date range: {date_range.get('earliest', 'N/A')} to {date_range.get('latest', 'N/A')}")
            logger.info(f"Output written to {output_dir / 'photo_metadata.json'}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing photo metadata: {e}")
            return False


class PhotoLocationCorrelator:
    """Correlate geotagged photos to regions and saved places"""
    
    def __init__(self):
        self.region_distance_threshold_miles = 10.0
        self.place_distance_threshold_miles = 0.1
    
    def load_existing_data(self, data_dir: Path) -> tuple[dict, dict, dict]:
        """Load regional centers, saved places, and photo metadata"""
        regional_centers = {}
        saved_places = {}
        photo_metadata = {}
        
        # Load regional centers
        regional_file = data_dir / 'regional_centers.json'
        if regional_file.exists():
            with open(regional_file) as f:
                regional_centers = json.load(f)
        
        # Load saved places
        saved_file = data_dir / 'saved_places.json'
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
        photo_file = data_dir / 'photo_metadata.json'
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
                nearby_places.append({
                    'name': place.get('name', 'Unknown'),
                    'distance': distance,
                    'id': place.get('id', ''),
                    'type': 'labeled' if place.get('id', '').startswith('place_') else 'saved'
                })
        
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
            
            if not photo_data.get('photos'):
                logger.error("No photo metadata found")
                return False
            
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
                    logger.info(f"Processing photo {i+1}/{len(geotagged_photos)} ({(i+1)/len(geotagged_photos)*100:.1f}%)")
                
                coords = photo.get('coordinates', {})
                if not coords:
                    continue
                
                photo_lat = coords.get('latitude')
                photo_lon = coords.get('longitude')
                
                if photo_lat is None or photo_lon is None:
                    continue
                
                # Find nearest region
                nearest_region, distance_to_region = self.find_nearest_region(
                    photo_lat, photo_lon, regional_data['regions']
                )
                
                # Find nearby places
                nearby_places = self.find_nearest_places(photo_lat, photo_lon, places_list)
                
                photo_location_data = {
                    'filename': photo.get('filename'),
                    'timestamp': photo.get('timestamp'),
                    'coordinates': coords,
                    'distance_to_center': distance_to_region,
                    'nearby_places': nearby_places,
                    'nearest_place': nearby_places[0] if nearby_places else None
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
                    date_range = {
                        'first_photo': timestamps[0],
                        'last_photo': timestamps[-1]
                    }
                
                region_summaries[region_name] = {
                    'photo_count': len(photos),
                    'date_range': date_range,
                    'photos': photos
                }
            
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
                    'place_distance_threshold_miles': self.place_distance_threshold_miles
                },
                'regions': region_summaries,
                'unmatched_photos': unmatched_photos
            }
            
            with open(output_dir / 'photo_locations.json', 'w') as f:
                json.dump(photo_locations_output, f, indent=2)
            
            logger.info(f"Successfully correlated {len(geotagged_photos)} photos")
            logger.info(f"Matched {sum(len(photos) for photos in region_groups.values())} photos to {len(region_groups)} regions")
            logger.info(f"Found {len(unmatched_photos)} unmatched photos")
            logger.info(f"Output written to {output_dir / 'photo_locations.json'}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error correlating photos to locations: {e}")
            return False


class ReviewVisitsExtractor:
    """Extract review timestamps as visit confirmations"""
    
    def __init__(self):
        self.place_matching_tolerance_miles = 0.25  # Quarter mile for fuzzy matching
        self.region_distance_threshold_miles = 10.0
    
    def load_existing_data(self, data_dir: Path) -> tuple[dict, dict]:
        """Load regional centers and saved/labeled places data"""
        regional_centers = {}
        all_places = []
        
        # Load regional centers
        regional_file = data_dir / 'regional_centers.json'
        if regional_file.exists():
            with open(regional_file) as f:
                regional_centers = json.load(f)
        
        # Load saved places
        saved_file = data_dir / 'saved_places.json'
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
                best_match = {
                    'place': place,
                    'distance': distance,
                    'name_score': name_score,
                    'combined_score': combined_score
                }
        
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
                        logger.warning(f"Review {i+1} missing coordinates")
                        continue
                    
                    review_lon, review_lat = coords[0], coords[1]
                    
                    review_record = {
                        'id': f"review_{i+1:03d}",
                        'place_name': location.get('name', 'Unknown Place'),
                        'coordinates': {
                            'latitude': review_lat,
                            'longitude': review_lon
                        },
                        'review_date': props.get('date'),
                        'rating': props.get('five_star_rating_published'),
                        'text_preview': (props.get('review_text_published', '')[:100] + '...') if props.get('review_text_published') else '',
                        'address': location.get('address', ''),
                        'google_maps_url': props.get('google_maps_url', ''),
                        'matched_place': None,
                        'place_match_details': None,
                        'region': None,
                        'distance_to_region': None,
                        'visit_type': 'confirmed'
                    }
                    
                    # Try to match to existing places
                    place_match = self.find_matching_place(
                        review_record['place_name'], 
                        review_lat, 
                        review_lon, 
                        all_places
                    )
                    
                    if place_match:
                        matched_to_places += 1
                        review_record['matched_place'] = place_match['place'].get('id')
                        review_record['place_match_details'] = {
                            'distance': place_match['distance'],
                            'name_score': place_match['name_score'],
                            'combined_score': place_match['combined_score'],
                            'matched_name': place_match['place'].get('name')
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
                    logger.error(f"Error processing review {i+1}: {e}")
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
                    'source_file': str(reviews_file)
                },
                'reviews': processed_reviews
            }
            
            with open(output_dir / 'review_visits.json', 'w') as f:
                json.dump(review_visits_output, f, indent=2)
            
            logger.info(f"Successfully processed {len(processed_reviews)} reviews")
            logger.info(f"Matched {matched_to_places} reviews to existing places ({(matched_to_places/len(processed_reviews)*100):.1f}%)")
            logger.info(f"Matched {matched_to_regions} reviews to regions ({(matched_to_regions/len(processed_reviews)*100):.1f}%)")
            logger.info(f"Output written to {output_dir / 'review_visits.json'}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error extracting review visits: {e}")
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

    elif command == "extract-photo-metadata":
        photos_dir = Path("takeout/maps/saved/Photos and videos")
        output_dir = Path("data")

        if not photos_dir.exists():
            logger.error(f"Photos directory not found: {photos_dir}")
            sys.exit(1)

        extractor = PhotoMetadataExtractor()
        success = extractor.process_photo_metadata(photos_dir, output_dir)
        sys.exit(0 if success else 1)

    elif command == "correlate-photos-to-regions":
        data_dir = Path("data")
        output_dir = Path("data")

        if not data_dir.exists():
            logger.error(f"Data directory not found: {data_dir}")
            sys.exit(1)

        correlator = PhotoLocationCorrelator()
        success = correlator.correlate_photos_to_locations(data_dir, output_dir)
        sys.exit(0 if success else 1)

    elif command == "extract-review-visits":
        reviews_file = Path("takeout/maps/your_places/Reviews.json")
        data_dir = Path("data")
        output_dir = Path("data")

        if not reviews_file.exists():
            logger.error(f"Reviews file not found: {reviews_file}")
            sys.exit(1)

        if not data_dir.exists():
            logger.error(f"Data directory not found: {data_dir}")
            sys.exit(1)

        extractor = ReviewVisitsExtractor()
        success = extractor.extract_review_visits(reviews_file, data_dir, output_dir)
        sys.exit(0 if success else 1)

    else:
        print(__doc__.strip())


if __name__ == "__main__":
    main()
