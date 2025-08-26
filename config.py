from decouple import config
from pathlib import Path

# Directory paths
INPUT_DIR = Path(config('INPUT_DIR', default='takeout/maps'))
OUTPUT_DIR = Path(config('OUTPUT_DIR', default='results'))
CACHE_DIR = Path(config('CACHE_DIR', default='data'))

# Temporary directories
TEMP_EXTRACT_DIR = 'temp_takeout_extract'

# File names
GEOCODING_CACHE_FILE = 'geocoding_cache.json'
SAVED_PLACES_FILE = 'saved_places.json'
PHOTO_METADATA_FILE = 'photo_metadata.json'
PHOTO_LOCATIONS_FILE = 'photo_locations.json'
REVIEW_VISITS_FILE = 'review_visits.json'
VISIT_TIMELINE_FILE = 'visit_timeline.json'
SUMMARY_REPORT_FILE = 'summary_report.md'
REGIONAL_CENTERS_FILE = 'regional_centers.json'
LABELED_PLACES_FILE = 'labeled_places.json'
VALIDATION_REPORT_FILE = 'validation_report.md'
SERPAPI_CACHE_FILE = 'serpapi_cache.json'
NY_SAVED_PLACES_FILE = 'ny_saved_places.csv'

# Input file mappings
TAKEOUT_FILE_MAPPINGS = {
    "Reviews.json": "reviews.json",
    "Saved Places.json": "saved_places.json"
}

# Geographic constants
GEOCODING_CACHE_EXPIRATION_DAYS = 30
PLACE_MATCHING_TOLERANCE_MILES = 0.25       # Quarter mile for fuzzy matching
REGION_DISTANCE_THRESHOLD_MILES = 10.0      # 10-mile radius for regional clustering
DEDUPLICATION_WINDOW_HOURS = 24             # Consider visits within 24 hours as same visit

# Validation constants
MIN_VALID_LATITUDE = -90.0
MAX_VALID_LATITUDE = 90.0
MIN_VALID_LONGITUDE = -180.0
MAX_VALID_LONGITUDE = 180.0
MIN_VALID_YEAR = 1990
MAX_VALID_YEAR = 2030

# Pipeline step definitions
PIPELINE_STEPS = [
    {
        'name': 'extract-labeled-places',
        'description': 'Extract and group starred/labeled places by region',
        'required_files': ['saved/My labeled places/Labeled places.json'],
        'output_files': [LABELED_PLACES_FILE, REGIONAL_CENTERS_FILE],
    },
    {
        'name': 'extract-saved-places',
        'description': 'Extract saved places with timestamps',
        'required_files': ['your_places/saved_places.json'],
        'output_files': [SAVED_PLACES_FILE],
        'dependencies': ['extract-labeled-places'],
    },
    {
        'name': 'extract-photo-metadata',
        'description': 'Extract geolocation data from photo metadata',
        'required_files': [],
        'output_files': [PHOTO_METADATA_FILE],
    },
    {
        'name': 'correlate-photos-to-regions',
        'description': 'Match geotagged photos to regions',
        'required_files': [],
        'output_files': [PHOTO_LOCATIONS_FILE],
        'dependencies': ['extract-labeled-places', 'extract-photo-metadata'],
    },
    {
        'name': 'extract-review-visits',
        'description': 'Extract review timestamps as visit confirmations',
        'required_files': ['your_places/reviews.json'],
        'output_files': [REVIEW_VISITS_FILE],
        'dependencies': ['extract-labeled-places'],
    },
    {
        'name': 'generate-visit-timeline',
        'description': 'Generate comprehensive visit timeline',
        'required_files': [],
        'output_files': [VISIT_TIMELINE_FILE],
        'dependencies': ['correlate-photos-to-regions', 'extract-review-visits', 'extract-saved-places'],
    },
    {
        'name': 'generate-summary-report',
        'description': 'Generate human-readable markdown summary',
        'required_files': [],
        'output_files': [SUMMARY_REPORT_FILE],
        'dependencies': ['generate-visit-timeline'],
    },
]
