import json
import pytest
from datetime import UTC, datetime
from main import DataValidator
from pathlib import Path


class TestDataValidator:
    """Test suite for DataValidator class"""

    @pytest.fixture
    def validator(self, tmp_path):
        """Create a validator instance with temporary directories"""
        input_dir = tmp_path / "takeout/maps"
        output_dir = tmp_path / "data"
        input_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        return DataValidator(input_dir=input_dir, output_dir=output_dir)

    @pytest.fixture
    def test_data_dir(self, tmp_path):
        """Create test data directory structure"""
        test_dir = tmp_path / "test_data"
        test_dir.mkdir()
        return test_dir

    def test_is_valid_coordinate(self, validator):
        """Test coordinate validation"""
        # Valid coordinates
        assert validator.is_valid_coordinate(0, 0)
        assert validator.is_valid_coordinate(37.7749, -122.4194)
        assert validator.is_valid_coordinate(-90, 180)
        assert validator.is_valid_coordinate(90, -180)

        # Invalid coordinates
        assert not validator.is_valid_coordinate(91, 0)
        assert not validator.is_valid_coordinate(-91, 0)
        assert not validator.is_valid_coordinate(0, 181)
        assert not validator.is_valid_coordinate(0, -181)
        assert not validator.is_valid_coordinate(100, 200)

    def test_is_valid_timestamp(self, validator):
        """Test timestamp validation"""
        # Valid timestamps
        assert validator.is_valid_timestamp("2024-01-15T10:00:00.000Z")
        assert validator.is_valid_timestamp("2023-12-31T23:59:59Z")
        assert validator.is_valid_timestamp("2020-06-15")

        # Invalid timestamps
        assert not validator.is_valid_timestamp("not-a-date")
        assert not validator.is_valid_timestamp("1989-12-31")  # Before 1990
        assert not validator.is_valid_timestamp("2031-01-01")  # After 2030
        assert not validator.is_valid_timestamp("")

    def test_validate_json_structure(self, validator, tmp_path):
        """Test JSON structure validation"""
        # Create valid JSON file
        valid_file = tmp_path / "valid.json"
        valid_data = {"metadata": {"version": "1.0"}, "places": [{"id": 1, "name": "Test"}]}
        with open(valid_file, 'w') as f:
            json.dump(valid_data, f)

        result = validator.validate_json_structure(valid_file, ['metadata', 'places'])
        assert result['valid']
        assert result['exists']
        assert result['readable']
        assert result['valid_json']
        assert result['has_required_keys']
        assert result['record_count'] == 1

        # Test missing file
        missing_file = tmp_path / "missing.json"
        result = validator.validate_json_structure(missing_file, ['data'])
        assert not result['valid']
        assert not result['exists']

        # Test invalid JSON
        invalid_file = tmp_path / "invalid.json"
        with open(invalid_file, 'w') as f:
            f.write("{invalid json")

        result = validator.validate_json_structure(invalid_file, ['data'])
        assert not result['valid']
        assert result['exists']
        assert result['readable']
        assert not result['valid_json']

        # Test missing required keys
        incomplete_file = tmp_path / "incomplete.json"
        with open(incomplete_file, 'w') as f:
            json.dump({"metadata": {}}, f)

        result = validator.validate_json_structure(incomplete_file, ['metadata', 'data'])
        assert not result['valid']
        assert result['missing_keys'] == ['data']

    def test_test_data_fixtures(self, test_data_dir):
        """Test that test data fixtures work correctly"""
        from tests.fixtures import TestDataFixtures

        # Create test data using fixtures
        success = TestDataFixtures.create_test_data_files(test_data_dir)
        assert success

        # Check generated files
        assert (test_data_dir / 'labeled_places.json').exists()
        assert (test_data_dir / 'saved_places.json').exists()
        assert (test_data_dir / 'reviews.json').exists()

        # Validate generated data structure
        with open(test_data_dir / 'labeled_places.json') as f:
            data = json.load(f)
            assert data['type'] == 'FeatureCollection'
            assert len(data['features']) == 2
            assert all('geometry' in feature for feature in data['features'])
            assert all('properties' in feature for feature in data['features'])

    def test_validate_input_files(self, validator):
        """Test input file validation"""
        # Create valid input files
        input_dir = validator.input_dir

        # Create labeled places file
        labeled_dir = input_dir / 'saved/My labeled places'
        labeled_dir.mkdir(parents=True)
        labeled_file = labeled_dir / 'Labeled places.json'
        with open(labeled_file, 'w') as f:
            json.dump({"features": []}, f)

        # Create saved places file
        your_places_dir = input_dir / 'your_places'
        your_places_dir.mkdir(parents=True)
        saved_file = your_places_dir / 'saved_places.json'
        with open(saved_file, 'w') as f:
            json.dump({"features": []}, f)

        # Create reviews file
        reviews_file = your_places_dir / 'reviews.json'
        with open(reviews_file, 'w') as f:
            json.dump({"features": []}, f)

        # Create photos directory
        photos_dir = input_dir / 'saved/Photos and videos'
        photos_dir.mkdir(parents=True)

        # Test validation
        assert validator.validate_input_files()
        assert len(validator.validation_results['errors']) == 0

        # Test with missing file
        labeled_file.unlink()
        validator.validation_results['errors'] = []
        validator.validation_results['warnings'] = []
        validator.validate_input_files()
        assert len(validator.validation_results['warnings']) > 0

    def test_validate_coordinates_in_data(self, validator):
        """Test coordinate validation in data"""
        # Create test data with valid and invalid coordinates
        output_dir = validator.output_dir

        # Create saved places with mixed coordinates
        saved_places = {
            "places": [
                {"id": 1, "latitude": 37.7749, "longitude": -122.4194},  # Valid
                {"id": 2, "latitude": 200, "longitude": 300},  # Invalid
                {"id": 3, "latitude": 40.7128, "longitude": -74.0060},  # Valid
            ]
        }
        with open(output_dir / 'saved_places.json', 'w') as f:
            json.dump(saved_places, f)

        # Create photo metadata with coordinates
        photo_data = {
            "photos": [
                {
                    "filename": "photo1.jpg",
                    "coordinates": {"latitude": 51.5074, "longitude": -0.1278},  # Valid
                },
                {
                    "filename": "photo2.jpg",
                    "coordinates": {"latitude": -100, "longitude": 200},  # Invalid
                },
            ]
        }
        with open(output_dir / 'photo_metadata.json', 'w') as f:
            json.dump(photo_data, f)

        # Test validation
        assert not validator.validate_coordinates_in_data()

        coord_validation = validator.validation_results['processing_validation']['coordinates']
        assert coord_validation['total_coordinates'] == 5
        assert coord_validation['invalid_coordinates'] == 2
        assert coord_validation['error_rate'] == 40.0

    def test_run_full_validation(self, validator):
        """Test full validation suite"""
        # Create minimal valid structure
        input_dir = validator.input_dir
        output_dir = validator.output_dir

        # Create input files
        labeled_dir = input_dir / 'saved/My labeled places'
        labeled_dir.mkdir(parents=True)
        with open(labeled_dir / 'Labeled places.json', 'w') as f:
            json.dump({"features": []}, f)

        your_places_dir = input_dir / 'your_places'
        your_places_dir.mkdir(parents=True)
        with open(your_places_dir / 'saved_places.json', 'w') as f:
            json.dump({"features": []}, f)
        with open(your_places_dir / 'reviews.json', 'w') as f:
            json.dump({"features": []}, f)

        # Create output files
        output_files = {
            'labeled_places.json': {"metadata": {}, "places": []},
            'regional_centers.json': {"metadata": {}, "regions": {}},
            'saved_places.json': {"metadata": {}, "places": []},
            'photo_metadata.json': {"metadata": {}, "photos": []},
            'photo_locations.json': {"metadata": {}, "regions": {}},
            'review_visits.json': {"metadata": {}, "reviews": []},
            'visit_timeline.json': {"metadata": {}, "regions": {}},
        }

        for filename, content in output_files.items():
            with open(output_dir / filename, 'w') as f:
                json.dump(content, f)

        # Create summary report
        with open(output_dir / 'summary_report.md', 'w') as f:
            f.write("# Google Maps Travel Analysis Report\n\nTest content")

        # Run validation
        result = validator.run_full_validation()
        assert result  # Should be valid with minimal structure

        summary = validator.validation_results['summary']
        assert summary['input_validation']
        assert summary['output_validation']
        assert summary['overall_valid']

    def test_generate_validation_report(self, validator):
        """Test validation report generation"""
        # Set up validation results
        validator.validation_results = {
            'summary': {
                'overall_valid': True,
                'total_errors': 0,
                'total_warnings': 2,
                'input_validation': True,
                'coordinate_validation': True,
                'regional_validation': True,
                'output_validation': True,
                'cache_validation': True,
            },
            'errors': [],
            'warnings': ['Warning 1', 'Warning 2'],
        }

        report = validator.generate_validation_report()

        assert '# Data Validation Report' in report
        assert '✅ **Overall Status:** VALID' in report
        assert '**Errors:** 0' in report
        assert '**Warnings:** 2' in report
        assert 'Warning 1' in report
        assert 'Warning 2' in report
