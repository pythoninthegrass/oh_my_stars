import json
import pytest
from datetime import UTC, datetime
from main import (
    LabeledPlacesExtractor,
    PhotoLocationCorrelator,
    PhotoMetadataExtractor,
    ReviewVisitsExtractor,
    SavedPlacesExtractor,
    SummaryReportGenerator,
    VisitTimelineGenerator,
)
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch


class TestLabeledPlacesExtractor:
    """Test suite for LabeledPlacesExtractor"""

    @pytest.fixture
    def extractor(self):
        """Create extractor instance"""
        return LabeledPlacesExtractor()

    @pytest.fixture
    def sample_labeled_places(self):
        """Create sample labeled places data"""
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "Title": "Golden Gate Bridge",
                        "Address": "Golden Gate Bridge, San Francisco, CA 94129, USA",
                        "Published": "2024-01-15T10:00:00Z",
                        "Updated": "2024-01-15T10:00:00Z",
                        "Google Maps URL": "https://maps.google.com/?cid=123456",
                    },
                    "geometry": {"type": "Point", "coordinates": [-122.4783, 37.8199]},
                },
                {
                    "type": "Feature",
                    "properties": {
                        "Title": "Statue of Liberty",
                        "Address": "New York, NY 10004, USA",
                        "Published": "2024-01-16T14:30:00Z",
                        "Updated": "2024-01-16T14:30:00Z",
                        "Google Maps URL": "https://maps.google.com/?cid=789012",
                    },
                    "geometry": {"type": "Point", "coordinates": [-74.0445, 40.6892]},
                },
            ],
        }

    def test_extract_city_from_address(self, extractor):
        """Test city extraction from addresses"""
        # Standard address formats
        assert extractor.extract_city_from_address("123 Main St, San Francisco, CA 94105") == "San Francisco"
        assert extractor.extract_city_from_address("New York, NY 10001") == "New York"
        assert extractor.extract_city_from_address("Paris, France") == "Paris"

        # Edge cases
        assert extractor.extract_city_from_address("") is None
        assert extractor.extract_city_from_address("123 Main St") is None
        assert extractor.extract_city_from_address("94105") is None

    def test_calculate_center_point(self, extractor):
        """Test center point calculation"""
        places = [{"latitude": 37.7749, "longitude": -122.4194}, {"latitude": 37.8044, "longitude": -122.2712}]

        center_lat, center_lon = extractor.calculate_center_point(places)
        assert abs(center_lat - 37.7896) < 0.01
        assert abs(center_lon - (-122.3453)) < 0.01

        # Empty list
        lat, lon = extractor.calculate_center_point([])
        assert lat == 0.0
        assert lon == 0.0

    @patch('main.Nominatim')
    def test_reverse_geocode_city(self, mock_nominatim, extractor):
        """Test reverse geocoding with mocked API"""
        # Mock geocoder response
        mock_location = Mock()
        mock_location.raw = {'address': {'city': 'San Francisco', 'state': 'California', 'country_code': 'us'}}
        mock_geocoder = Mock()
        mock_geocoder.reverse.return_value = mock_location
        mock_nominatim.return_value = mock_geocoder

        # Re-initialize with mocked geocoder
        extractor.geocoder = mock_geocoder

        result = extractor.reverse_geocode_city(37.7749, -122.4194)
        assert result == "San Francisco, California, US"

        # Test cache hit (cache returns the exact same value)
        result2 = extractor.reverse_geocode_city(37.7749, -122.4194)
        assert result2 == result  # Should return same value from cache
        assert mock_geocoder.reverse.call_count == 1  # Should use cache

    def test_process_labeled_places(self, extractor, sample_labeled_places, tmp_path):
        """Test processing labeled places"""
        input_file = tmp_path / "labeled_places.json"
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with open(input_file, 'w') as f:
            json.dump(sample_labeled_places, f)

        # Mock reverse geocoding
        extractor.reverse_geocode_city = Mock(side_effect=["San Francisco, CA, US", "New York, NY, US"])

        success = extractor.process_labeled_places(input_file, output_dir)
        assert success

        # Check output files
        labeled_file = output_dir / "labeled_places.json"
        regional_file = output_dir / "regional_centers.json"

        assert labeled_file.exists()
        assert regional_file.exists()

        # Verify labeled places output
        with open(labeled_file) as f:
            labeled_data = json.load(f)

        assert labeled_data['metadata']['total_places'] == 2
        assert len(labeled_data['places']) == 2

        # Verify regional centers output
        with open(regional_file) as f:
            regional_data = json.load(f)

        assert len(regional_data['regions']) == 2
        assert "San Francisco, CA, US" in regional_data['regions']
        assert "New York, NY, US" in regional_data['regions']


class TestSavedPlacesExtractor:
    """Test suite for SavedPlacesExtractor"""

    @pytest.fixture
    def extractor(self):
        """Create extractor instance"""
        return SavedPlacesExtractor()

    @pytest.fixture
    def sample_saved_places(self):
        """Create sample saved places data"""
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "Title": "Best Coffee Shop",
                        "Date": "2024-01-15T08:30:00Z",
                        "Google Maps URL": "https://maps.google.com/?cid=111222",
                    },
                    "geometry": {"type": "Point", "coordinates": [-122.4194, 37.7749]},
                }
            ],
        }

    def test_parse_timestamp(self, extractor):
        """Test timestamp parsing"""
        # Valid formats
        dt = extractor.parse_timestamp("2024-01-15T10:00:00Z")
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15

        dt = extractor.parse_timestamp("2024-01-15")
        assert dt.year == 2024

        # Invalid format
        assert extractor.parse_timestamp("invalid-date") is None

    def test_process_saved_places(self, extractor, sample_saved_places, tmp_path):
        """Test processing saved places"""
        input_file = tmp_path / "saved_places.json"
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create regional centers file
        regional_centers = {
            "regions": {"San Francisco, CA, US": {"center": {"latitude": 37.7749, "longitude": -122.4194}, "places": []}}
        }
        with open(output_dir / "regional_centers.json", 'w') as f:
            json.dump(regional_centers, f)

        with open(input_file, 'w') as f:
            json.dump(sample_saved_places, f)

        success = extractor.process_saved_places(input_file, output_dir)
        assert success

        # Check output
        output_file = output_dir / "saved_places.json"
        assert output_file.exists()

        with open(output_file) as f:
            data = json.load(f)

        assert data['metadata']['total_places'] == 1
        assert len(data['places']) == 1
        assert data['places'][0]['title'] == "Best Coffee Shop"


class TestPhotoMetadataExtractor:
    """Test suite for PhotoMetadataExtractor"""

    @pytest.fixture
    def extractor(self):
        """Create extractor instance"""
        return PhotoMetadataExtractor()

    @pytest.fixture
    def sample_photo_metadata(self):
        """Create sample photo metadata"""
        return {
            "title": "IMG_1234.jpg",
            "photoTakenTime": {
                "timestamp": "1610553600"  # 2021-01-13 16:00:00 UTC
            },
            "geoData": {"latitude": 37.7749, "longitude": -122.4194, "altitude": 50.0, "latitudeSpan": 0.0, "longitudeSpan": 0.0},
        }

    def test_parse_photo_timestamp(self, extractor):
        """Test photo timestamp parsing"""
        # Unix timestamp
        metadata = {"photoTakenTime": {"timestamp": "1610553600"}}
        dt = extractor.parse_photo_timestamp(metadata)
        assert dt.year == 2021
        assert dt.month == 1
        assert dt.day == 13

        # Formatted timestamp
        metadata = {"photoTakenTime": {"formatted": "Jan 13, 2021, 4:00:00 PM UTC"}}
        dt = extractor.parse_photo_timestamp(metadata)
        assert dt is not None

        # Missing timestamp
        assert extractor.parse_photo_timestamp({}) is None

    def test_extract_coordinates(self, extractor):
        """Test coordinate extraction"""
        # Valid coordinates
        metadata = {"geoData": {"latitude": 37.7749, "longitude": -122.4194}}
        coords = extractor.extract_coordinates(metadata)
        assert coords == {"latitude": 37.7749, "longitude": -122.4194}

        # Zero coordinates (invalid)
        metadata = {"geoData": {"latitude": 0.0, "longitude": 0.0}}
        assert extractor.extract_coordinates(metadata) is None

        # Missing geoData
        assert extractor.extract_coordinates({}) is None

    def test_process_photo_metadata(self, extractor, sample_photo_metadata, tmp_path):
        """Test processing photo metadata"""
        photos_dir = tmp_path / "photos"
        photos_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create photo metadata file
        metadata_file = photos_dir / "IMG_1234.jpg.json"
        with open(metadata_file, 'w') as f:
            json.dump(sample_photo_metadata, f)

        success = extractor.process_photo_metadata(photos_dir, output_dir)
        assert success

        # Check output
        output_file = output_dir / "photo_metadata.json"
        assert output_file.exists()

        with open(output_file) as f:
            data = json.load(f)

        assert data['metadata']['total_photos'] == 1
        assert data['metadata']['geotagged_photos'] == 1
        assert len(data['photos']) == 1
        assert data['photos'][0]['filename'] == "IMG_1234.jpg"


class TestPhotoLocationCorrelator:
    """Test suite for PhotoLocationCorrelator"""

    @pytest.fixture
    def correlator(self):
        """Create correlator instance"""
        return PhotoLocationCorrelator()

    def test_find_closest_saved_place(self, correlator):
        """Test finding closest saved place"""
        photo_coords = (37.7749, -122.4194)
        saved_places = [
            {"id": "place1", "title": "Close Place", "latitude": 37.7750, "longitude": -122.4190},
            {"id": "place2", "title": "Far Place", "latitude": 40.7128, "longitude": -74.0060},
        ]

        place, distance = correlator.find_closest_saved_place(photo_coords, saved_places)
        assert place['title'] == "Close Place"
        assert distance < 0.3  # Less than 0.3 miles

    def test_correlate_photos_to_locations(self, correlator, tmp_path):
        """Test photo correlation"""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Create test data files
        regional_centers = {
            "regions": {"San Francisco, CA, US": {"center": {"latitude": 37.7749, "longitude": -122.4194}, "places": []}}
        }

        photo_metadata = {
            "photos": [
                {
                    "filename": "photo1.jpg",
                    "coordinates": {"latitude": 37.7749, "longitude": -122.4194},
                    "timestamp": "2024-01-15T10:00:00Z",
                }
            ]
        }

        saved_places = {
            "places": [
                {
                    "id": "place1",
                    "title": "Test Place",
                    "latitude": 37.7750,
                    "longitude": -122.4190,
                    "timestamp": "2024-01-15T09:00:00Z",
                }
            ]
        }

        with open(data_dir / "regional_centers.json", 'w') as f:
            json.dump(regional_centers, f)
        with open(data_dir / "photo_metadata.json", 'w') as f:
            json.dump(photo_metadata, f)
        with open(data_dir / "saved_places.json", 'w') as f:
            json.dump(saved_places, f)

        success = correlator.correlate_photos_to_locations(data_dir, data_dir)
        assert success

        # Check output
        output_file = data_dir / "photo_locations.json"
        assert output_file.exists()


class TestReviewVisitsExtractor:
    """Test suite for ReviewVisitsExtractor"""

    @pytest.fixture
    def extractor(self):
        """Create extractor instance"""
        return ReviewVisitsExtractor()

    @pytest.fixture
    def sample_reviews(self):
        """Create sample reviews data"""
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "Google Maps URL": "https://maps.google.com/?cid=123456",
                        "Published": "2024-01-15T15:00:00Z",
                        "Location": {"Business Name": "Test Restaurant", "Address": "123 Main St, San Francisco, CA"},
                    },
                    "geometry": {"type": "Point", "coordinates": [-122.4194, 37.7749]},
                }
            ],
        }

    def test_extract_review_visits(self, extractor, sample_reviews, tmp_path):
        """Test review visit extraction"""
        reviews_file = tmp_path / "reviews.json"
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Create regional centers
        regional_centers = {"regions": {"San Francisco, CA, US": {"center": {"latitude": 37.7749, "longitude": -122.4194}}}}

        with open(reviews_file, 'w') as f:
            json.dump(sample_reviews, f)
        with open(data_dir / "regional_centers.json", 'w') as f:
            json.dump(regional_centers, f)

        success = extractor.extract_review_visits(reviews_file, data_dir, data_dir)
        assert success

        # Check output
        output_file = data_dir / "review_visits.json"
        assert output_file.exists()

        with open(output_file) as f:
            data = json.load(f)

        assert data['metadata']['total_reviews'] == 1
        assert len(data['reviews']) == 1
