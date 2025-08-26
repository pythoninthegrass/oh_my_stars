"""Test data fixtures for oh_my_stars tests"""

import json
from pathlib import Path


class TestDataFixtures:
    """Centralized test data fixtures"""

    @staticmethod
    def get_test_labeled_places():
        """Generate test labeled places data"""
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "Title": "Test Location 1",
                        "Published": "2024-01-15T10:00:00.000Z",
                        "Updated": "2024-01-15T10:00:00.000Z",
                        "Google Maps URL": "https://maps.google.com/?cid=123456789",
                    },
                    "geometry": {"type": "Point", "coordinates": [-122.4194, 37.7749]},
                },
                {
                    "type": "Feature",
                    "properties": {
                        "Title": "Test Location 2",
                        "Published": "2024-01-16T14:30:00.000Z",
                        "Updated": "2024-01-16T14:30:00.000Z",
                        "Google Maps URL": "https://maps.google.com/?cid=987654321",
                    },
                    "geometry": {"type": "Point", "coordinates": [-74.0060, 40.7128]},
                },
            ],
        }

    @staticmethod
    def get_test_saved_places():
        """Generate test saved places data"""
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "Title": "Test Restaurant",
                        "Date": "2024-01-15T12:00:00.000Z",
                        "Google Maps URL": "https://maps.google.com/?cid=111222333",
                    },
                    "geometry": {"type": "Point", "coordinates": [-122.4194, 37.7749]},
                }
            ],
        }

    @staticmethod
    def get_test_reviews():
        """Generate test reviews data"""
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "Google Maps URL": "https://maps.google.com/?cid=111222333",
                        "Location": {
                            "Business Name": "Test Business",
                            "Address": "123 Test St, San Francisco, CA",
                            "Country Code": "US",
                        },
                        "Published": "2024-01-15T15:00:00.000Z",
                    },
                    "geometry": {"type": "Point", "coordinates": [-122.4194, 37.7749]},
                }
            ],
        }

    @classmethod
    def create_test_data_files(cls, test_dir: Path):
        """Create all test data files in the given directory"""
        test_dir.mkdir(exist_ok=True)

        # Create test files
        with open(test_dir / 'labeled_places.json', 'w') as f:
            json.dump(cls.get_test_labeled_places(), f, indent=2)

        with open(test_dir / 'saved_places.json', 'w') as f:
            json.dump(cls.get_test_saved_places(), f, indent=2)

        with open(test_dir / 'reviews.json', 'w') as f:
            json.dump(cls.get_test_reviews(), f, indent=2)

        return True
