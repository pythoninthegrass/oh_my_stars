import json
import logging
import ssl
import time
from config import (
    CACHE_DIR,
    GEOCODING_CACHE_EXPIRATION_DAYS,
    GEOCODING_CACHE_FILE,
)
from datetime import UTC, datetime
from dateutil.parser import parse as parse_date
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import Nominatim
from pathlib import Path

logger = logging.getLogger(__name__)


class GeocodingCache:
    """Comprehensive file-based cache for geocoding results with rate limiting and expiration"""

    def __init__(
        self, cache_file: Path = CACHE_DIR / GEOCODING_CACHE_FILE, expiration_days: int = GEOCODING_CACHE_EXPIRATION_DAYS
    ):
        self.cache_file = cache_file
        self.expiration_days = expiration_days
        self.last_api_call = 0
        self.min_api_interval = 1.0
        self.cache_data = self._load_cache()
        self.session_hits = 0
        self.session_misses = 0

    def _load_cache(self) -> dict:
        """Load cache from file with proper structure"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    data = json.load(f)
                    if 'metadata' not in data:
                        data = self._migrate_old_cache(data)
                    return data
            except (json.JSONDecodeError, FileNotFoundError):
                logger.warning("Could not load geocoding cache, starting fresh")

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

        for key, city in old_cache.items():
            if isinstance(city, str):
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
            return True

    def get(self, coordinates: tuple[float, float]) -> str | None:
        """Get cached reverse geocoding result"""
        key = self._generate_cache_key('reverse', latitude=coordinates[0], longitude=coordinates[1])
        entry = self.cache_data['entries'].get(key)

        if entry and not self._is_expired(entry):
            self.session_hits += 1
            self.cache_data['metadata']['cache_hits'] += 1
            response = entry.get('response', {})
            return response.get('city')

        self.session_misses += 1
        self.cache_data['metadata']['cache_misses'] += 1

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

        self.session_misses += 1
        self.cache_data['metadata']['cache_misses'] += 1

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
