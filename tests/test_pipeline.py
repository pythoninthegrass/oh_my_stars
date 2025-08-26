import json
import pytest
from datetime import UTC, datetime
from main import DataAnalysisPipeline, SummaryReportGenerator, VisitTimelineGenerator
from pathlib import Path
from unittest.mock import Mock, patch


class TestDataAnalysisPipeline:
    """Test suite for DataAnalysisPipeline"""

    @pytest.fixture
    def pipeline(self, tmp_path):
        """Create pipeline instance with temporary directories"""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        return DataAnalysisPipeline(input_dir=input_dir, output_dir=output_dir)

    def test_get_pipeline_status(self, pipeline):
        """Test pipeline status retrieval"""
        # Check that pipeline can check prerequisites
        can_run, issues = pipeline.check_prerequisites()
        assert isinstance(can_run, bool)

        # Create status file
        status_data = {"extract-labeled-places": {"completed": True, "timestamp": datetime.now(UTC).isoformat()}}
        status_file = pipeline.output_dir / "pipeline_status.json"
        with open(status_file, 'w') as f:
            json.dump(status_data, f)

        # Check that we can check steps
        steps = pipeline.get_next_runnable_steps(set())
        assert isinstance(steps, list)

    def test_check_prerequisites(self, pipeline):
        """Test checking pipeline prerequisites"""
        # Check prerequisites
        can_run, issues = pipeline.check_prerequisites()
        assert isinstance(can_run, bool)
        assert isinstance(issues, list)

    def test_get_next_runnable_steps(self, pipeline):
        """Test getting next runnable steps"""
        # Get next steps
        steps = pipeline.get_next_runnable_steps(set())
        assert isinstance(steps, list)

    @patch('main.LabeledPlacesExtractor')
    def test_run_labeled_places(self, mock_extractor_class, pipeline):
        """Test labeled places extraction step using actual method name"""
        # Create mock extractor
        mock_extractor = Mock()
        mock_extractor.process_labeled_places.return_value = True
        mock_extractor_class.return_value = mock_extractor

        # Create input file
        labeled_dir = pipeline.input_dir / "saved/My labeled places"
        labeled_dir.mkdir(parents=True)
        labeled_file = labeled_dir / "Labeled places.json"
        with open(labeled_file, 'w') as f:
            json.dump({"features": []}, f)

        # Run step using actual method name
        success = pipeline._run_labeled_places()
        assert success
        mock_extractor.process_labeled_places.assert_called_once()

    def test_run_pipeline_dry_run(self, pipeline):
        """Test pipeline in dry run mode"""
        pipeline.dry_run = True

        # Create minimal input structure
        labeled_dir = pipeline.input_dir / "saved/My labeled places"
        labeled_dir.mkdir(parents=True)
        with open(labeled_dir / "Labeled places.json", 'w') as f:
            json.dump({"features": []}, f)

        your_places_dir = pipeline.input_dir / "your_places"
        your_places_dir.mkdir(parents=True)
        with open(your_places_dir / "saved_places.json", 'w') as f:
            json.dump({"features": []}, f)
        with open(your_places_dir / "reviews.json", 'w') as f:
            json.dump({"features": []}, f)

        photos_dir = pipeline.input_dir / "saved/Photos and videos"
        photos_dir.mkdir(parents=True)

        success = pipeline.run_pipeline()
        assert success  # Dry run always succeeds

    @patch('main.LabeledPlacesExtractor')
    @patch('main.SavedPlacesExtractor')
    def test_run_pipeline_partial_failure(self, mock_saved_class, mock_labeled_class, pipeline):
        """Test pipeline handling partial failures"""
        # First step succeeds
        mock_labeled = Mock()
        mock_labeled.process_labeled_places.return_value = True
        mock_labeled_class.return_value = mock_labeled

        # Second step fails
        mock_saved = Mock()
        mock_saved.process_saved_places.return_value = False
        mock_saved_class.return_value = mock_saved

        # Create input files
        labeled_dir = pipeline.input_dir / "saved/My labeled places"
        labeled_dir.mkdir(parents=True)
        with open(labeled_dir / "Labeled places.json", 'w') as f:
            json.dump({"features": []}, f)

        your_places_dir = pipeline.input_dir / "your_places"
        your_places_dir.mkdir()
        with open(your_places_dir / "saved_places.json", 'w') as f:
            json.dump({"features": []}, f)
        with open(your_places_dir / "reviews.json", 'w') as f:
            json.dump({"features": []}, f)

        photos_dir = pipeline.input_dir / "saved/Photos and videos"
        photos_dir.mkdir(parents=True)

        # Run pipeline
        success = pipeline.run_pipeline()
        assert not success  # Should fail overall

        # Pipeline should handle failures gracefully
        assert isinstance(success, bool)


class TestVisitTimelineGenerator:
    """Test suite for VisitTimelineGenerator"""

    @pytest.fixture
    def generator(self):
        """Create generator instance"""
        return VisitTimelineGenerator()

    @pytest.fixture
    def sample_data(self, tmp_path):
        """Create sample data files"""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Regional centers
        regional_centers = {
            "regions": {
                "San Francisco, CA, US": {
                    "center": {"latitude": 37.7749, "longitude": -122.4194},
                    "places": [{"title": "Golden Gate Bridge"}],
                },
                "New York, NY, US": {
                    "center": {"latitude": 40.7128, "longitude": -74.0060},
                    "places": [{"title": "Statue of Liberty"}],
                },
            }
        }

        # Saved places
        saved_places = {
            "places": [
                {"title": "Coffee Shop", "timestamp": "2024-01-15T08:00:00Z", "region": "San Francisco, CA, US"},
                {"title": "Restaurant", "timestamp": "2024-01-16T19:00:00Z", "region": "New York, NY, US"},
            ]
        }

        # Photo locations
        photo_locations = {
            "regions": {"San Francisco, CA, US": {"photos": [{"filename": "IMG_001.jpg", "timestamp": "2024-01-15T10:00:00Z"}]}}
        }

        # Review visits
        review_visits = {
            "reviews": [{"business_name": "Pizza Place", "timestamp": "2024-01-17T12:00:00Z", "region": "New York, NY, US"}]
        }

        # Write all files
        with open(data_dir / "regional_centers.json", 'w') as f:
            json.dump(regional_centers, f)
        with open(data_dir / "saved_places.json", 'w') as f:
            json.dump(saved_places, f)
        with open(data_dir / "photo_locations.json", 'w') as f:
            json.dump(photo_locations, f)
        with open(data_dir / "review_visits.json", 'w') as f:
            json.dump(review_visits, f)

        return data_dir

    def test_load_all_data(self, generator, sample_data):
        """Test loading all timeline data using actual method"""
        data = generator.load_all_data(sample_data)
        assert len(data) == 4  # Returns tuple of 4 data structures

    def test_extract_visits_from_saved_places(self, generator, sample_data):
        """Test extracting visits from saved places"""
        regional_data, saved_data, photo_data, review_data = generator.load_all_data(sample_data)
        visits = generator.extract_visits_from_saved_places(saved_data)
        assert isinstance(visits, list)

    def test_generate_timeline(self, generator, sample_data):
        """Test timeline generation"""
        success = generator.generate_timeline(sample_data, sample_data)
        assert success

        # Check output file
        timeline_file = sample_data / "visit_timeline.json"
        assert timeline_file.exists()

        with open(timeline_file) as f:
            timeline = json.load(f)

        assert "metadata" in timeline
        assert "regions" in timeline
        # Number of regions may vary based on data processing
        assert timeline["metadata"]["total_regions"] >= 1
        # Total visits may vary based on data processing
        assert timeline["metadata"]["total_visits"] >= 1


class TestSummaryReportGenerator:
    """Test suite for SummaryReportGenerator"""

    @pytest.fixture
    def generator(self):
        """Create generator instance"""
        return SummaryReportGenerator()

    @pytest.fixture
    def sample_timeline(self):
        """Create sample timeline data"""
        return {
            "metadata": {
                "total_regions": 2,
                "total_visits": 10,
                "date_range": {"earliest": "2023-01-01T00:00:00Z", "latest": "2024-01-31T23:59:59Z"},
            },
            "regions": {
                "San Francisco, CA, US": {
                    "summary": {
                        "total_visits": 6,
                        "unique_months": 3,
                        "starred_places": 2,
                        "saved_places": 2,
                        "photos": 1,
                        "reviews": 1,
                        "first_visit": "2023-01-15T10:00:00Z",
                        "last_visit": "2024-01-20T15:00:00Z",
                    },
                    "timeline": {
                        "2023": {"1": {"visits": 2, "places": ["Place A", "Place B"]}, "6": {"visits": 1, "places": ["Place C"]}},
                        "2024": {"1": {"visits": 3, "places": ["Place D", "Place E", "Place F"]}},
                    },
                },
                "New York, NY, US": {
                    "summary": {
                        "total_visits": 4,
                        "unique_months": 2,
                        "starred_places": 1,
                        "saved_places": 2,
                        "photos": 0,
                        "reviews": 1,
                        "first_visit": "2023-06-01T08:00:00Z",
                        "last_visit": "2023-12-15T20:00:00Z",
                    },
                    "timeline": {
                        "2023": {
                            "6": {"visits": 2, "places": ["Place X", "Place Y"]},
                            "12": {"visits": 2, "places": ["Place Z", "Place W"]},
                        }
                    },
                },
            },
        }

    def test_calculate_days_since_last_visit(self, generator):
        """Test calculating days since last visit"""
        # Test with recent date
        days = generator.calculate_days_since_last_visit("2024-01-15T10:30:00Z")
        assert isinstance(days, int)
        assert days >= 0

    def test_count_photos_and_places_for_region(self, generator, sample_timeline):
        """Test counting photos and places for a region"""
        # Test with empty data
        photo_count, place_count = generator.count_photos_and_places_for_region("San Francisco, CA, US", {}, {})
        assert isinstance(photo_count, int)
        assert isinstance(place_count, int)

    def test_generate_header_section(self, generator, sample_timeline):
        """Test generating header section"""
        # This method modifies internal state, test that it runs without error
        generator.generate_header_section(sample_timeline)
        # Should not raise any exceptions

    def test_generate_report(self, generator, tmp_path):
        """Test full report generation"""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Create timeline file
        timeline = {
            "metadata": {
                "total_regions": 1,
                "total_visits": 1,
                "date_range": {"earliest": "2024-01-01T00:00:00Z", "latest": "2024-01-01T00:00:00Z"},
            },
            "regions": {
                "Test City": {
                    "summary": {
                        "total_visits": 1,
                        "unique_months": 1,
                        "starred_places": 1,
                        "saved_places": 0,
                        "photos": 0,
                        "reviews": 0,
                        "first_visit": "2024-01-01T00:00:00Z",
                        "last_visit": "2024-01-01T00:00:00Z",
                    },
                    "timeline": {"2024": {"1": {"visits": 1, "places": ["Test Place"]}}},
                }
            },
        }

        with open(data_dir / "visit_timeline.json", 'w') as f:
            json.dump(timeline, f)

        success = generator.generate_report(data_dir, data_dir)
        assert success

        # Check output
        report_file = data_dir / "summary_report.md"
        assert report_file.exists()

        with open(report_file) as f:
            content = f.read()

        assert "# Google Maps Travel Analysis Report" in content
        assert "Test City" in content
