import json
import pytest
import time
from datetime import UTC, datetime, timedelta
from main import GeocodingCache
from pathlib import Path


class TestGeocodingCache:
    """Test suite for GeocodingCache class"""

    @pytest.fixture
    def cache_file(self, tmp_path):
        """Create temporary cache file path"""
        return tmp_path / "test_cache.json"

    @pytest.fixture
    def cache(self, cache_file):
        """Create cache instance with temporary file"""
        return GeocodingCache(cache_file=cache_file, expiration_days=30)

    def test_init_empty_cache(self, cache, cache_file):
        """Test initialization with empty cache"""
        assert cache.cache_file == cache_file
        assert cache.expiration_days == 30
        assert cache.session_hits == 0
        assert cache.session_misses == 0
        assert 'metadata' in cache.cache_data
        assert 'entries' in cache.cache_data
        assert cache.cache_data['metadata']['version'] == '1.0'
        assert cache.cache_data['metadata']['total_entries'] == 0

    def test_load_existing_cache(self, cache_file):
        """Test loading existing cache file"""
        # Create existing cache
        existing_data = {
            'metadata': {'version': '1.0', 'total_entries': 1, 'cache_hits': 10, 'cache_misses': 5},
            'entries': {
                'reverse_37.774900_-122.419400': {
                    'timestamp': datetime.now(UTC).isoformat(),
                    'query_type': 'reverse',
                    'response': {'city': 'San Francisco'},
                }
            },
        }

        with open(cache_file, 'w') as f:
            json.dump(existing_data, f)

        # Load cache
        cache = GeocodingCache(cache_file=cache_file)
        assert cache.cache_data['metadata']['total_entries'] == 1
        assert cache.cache_data['metadata']['cache_hits'] == 10
        assert len(cache.cache_data['entries']) == 1

    def test_migrate_old_cache(self, cache_file):
        """Test migration from old cache format"""
        # Create old format cache
        old_data = {'37.7749,-122.4194': 'San Francisco', '40.7128,-74.0060': 'New York'}

        with open(cache_file, 'w') as f:
            json.dump(old_data, f)

        # Load and migrate
        cache = GeocodingCache(cache_file=cache_file)
        assert 'metadata' in cache.cache_data
        assert cache.cache_data['metadata']['total_entries'] == 2
        assert len(cache.cache_data['entries']) == 2

        # Check migrated entries
        sf_key = 'reverse_37.7749,-122.4194'
        assert sf_key in cache.cache_data['entries']
        assert cache.cache_data['entries'][sf_key]['response']['city'] == 'San Francisco'

    def test_generate_cache_key(self, cache):
        """Test cache key generation"""
        # Reverse geocoding key
        key = cache._generate_cache_key('reverse', latitude=37.7749, longitude=-122.4194)
        assert key == 'reverse_37.774900_-122.419400'

        # Forward geocoding key
        key = cache._generate_cache_key('forward', address='123 Main St, San Francisco')
        assert key == 'forward_123_main_st,_san_francisco'

        # Invalid query type
        with pytest.raises(ValueError):
            cache._generate_cache_key('invalid')

    def test_is_expired(self, cache):
        """Test expiration checking"""
        # Fresh entry
        fresh_entry = {'timestamp': datetime.now(UTC).isoformat()}
        assert not cache._is_expired(fresh_entry)

        # Old entry
        old_time = datetime.now(UTC) - timedelta(days=31)
        old_entry = {'timestamp': old_time.isoformat()}
        assert cache._is_expired(old_entry)

        # Invalid timestamp
        invalid_entry = {'timestamp': 'invalid-date'}
        assert cache._is_expired(invalid_entry)

    def test_get_set_reverse(self, cache):
        """Test reverse geocoding cache get/set"""
        coords = (37.7749, -122.4194)

        # Initial miss
        result = cache.get(coords)
        assert result is None
        assert cache.session_misses == 1
        assert cache.session_hits == 0

        # Set value
        cache.set(coords, 'San Francisco', {'city': 'San Francisco', 'country': 'USA'})

        # Cache hit
        result = cache.get(coords)
        assert result == 'San Francisco'
        assert cache.session_hits == 1
        assert cache.session_misses == 1

        # Verify cache was saved
        assert cache.cache_file.exists()

    def test_get_set_forward(self, cache):
        """Test forward geocoding cache get/set"""
        address = '123 Main St, San Francisco'
        response = {'latitude': 37.7749, 'longitude': -122.4194, 'display_name': '123 Main Street, San Francisco, CA, USA'}

        # Initial miss
        result = cache.get_forward(address)
        assert result is None
        assert cache.session_misses == 1

        # Set value
        cache.set_forward(address, response)

        # Cache hit
        result = cache.get_forward(address)
        assert result == response
        assert cache.session_hits == 1

    def test_clean_expired(self, cache):
        """Test cleaning expired entries"""
        # Add fresh entry
        fresh_coords = (37.7749, -122.4194)
        cache.set(fresh_coords, 'San Francisco')

        # Add expired entry manually
        old_time = datetime.now(UTC) - timedelta(days=31)
        expired_key = 'reverse_40.712800_-74.006000'
        cache.cache_data['entries'][expired_key] = {
            'timestamp': old_time.isoformat(),
            'query_type': 'reverse',
            'response': {'city': 'New York'},
        }
        cache.cache_data['metadata']['total_entries'] += 1

        # Clean expired
        removed = cache.clean_expired()
        assert removed == 1
        assert expired_key not in cache.cache_data['entries']
        assert cache.cache_data['metadata']['total_entries'] == 1

        # Fresh entry should remain
        assert cache.get(fresh_coords) == 'San Francisco'

    def test_rate_limiting(self, cache):
        """Test rate limiting enforcement"""
        # First call sets baseline
        cache.enforce_rate_limit()
        first_time = cache.last_api_call

        # Quick second call should be delayed
        start = time.time()
        cache.enforce_rate_limit()
        elapsed = time.time() - start

        # Should have waited approximately 1 second
        assert elapsed >= 0.9  # Allow small tolerance
        assert cache.last_api_call > first_time

    def test_get_stats(self, cache):
        """Test cache statistics"""
        # Add some entries and simulate usage
        cache.set((37.7749, -122.4194), 'San Francisco')
        cache.get((37.7749, -122.4194))  # Hit
        cache.get((40.7128, -74.0060))  # Miss

        stats = cache.get_stats()
        assert stats['total_entries'] == 1
        assert stats['cache_hits'] == 1
        assert stats['cache_misses'] == 1
        assert stats['hit_ratio_percent'] == 50.0
        assert stats['session_hits'] == 1
        assert stats['session_misses'] == 1
        assert stats['expiration_days'] == 30

    def test_clear_cache(self, cache):
        """Test cache clearing"""
        # Add entries
        cache.set((37.7749, -122.4194), 'San Francisco')
        cache.set((40.7128, -74.0060), 'New York')

        assert cache.cache_data['metadata']['total_entries'] == 2

        # Clear cache
        cache.clear()

        # Verify cleared
        assert cache.cache_data['metadata']['total_entries'] == 0
        assert len(cache.cache_data['entries']) == 0
        assert cache.session_hits == 0
        assert cache.session_misses == 0

    def test_concurrent_save(self, cache):
        """Test that cache saves properly"""
        coords1 = (37.7749, -122.4194)
        coords2 = (40.7128, -74.0060)

        # Set multiple values
        cache.set(coords1, 'San Francisco')
        cache.set(coords2, 'New York')

        # Load fresh cache instance to verify persistence
        new_cache = GeocodingCache(cache_file=cache.cache_file)

        assert new_cache.get(coords1) == 'San Francisco'
        assert new_cache.get(coords2) == 'New York'
        assert new_cache.cache_data['metadata']['total_entries'] == 2
