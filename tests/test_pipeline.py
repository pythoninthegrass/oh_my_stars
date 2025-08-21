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
        # Initial status
        status = pipeline._get_pipeline_status()
        assert status == {}

        # Create status file
        status_data = {"extract-labeled-places": {"completed": True, "timestamp": datetime.now(UTC).isoformat()}}
        status_file = pipeline.output_dir / "pipeline_status.json"
        with open(status_file, 'w') as f:
            json.dump(status_data, f)

        # Check loaded status
        status = pipeline._get_pipeline_status()
        assert "extract-labeled-places" in status
        assert status["extract-labeled-places"]["completed"]

    def test_update_pipeline_status(self, pipeline):
        """Test pipeline status updates"""
        # Update status
        pipeline._update_pipeline_status("test-step", True)

        # Verify file created
        status_file = pipeline.output_dir / "pipeline_status.json"
        assert status_file.exists()

        # Check content
        with open(status_file) as f:
            status = json.load(f)

        assert "test-step" in status
        assert status["test-step"]["completed"]
        assert "timestamp" in status["test-step"]

    def test_find_resume_point(self, pipeline):
        """Test finding resume point in pipeline"""
        # No completed steps
        assert pipeline._find_resume_point() == 0

        # Some completed steps
        pipeline._update_pipeline_status("extract-labeled-places", True)
        pipeline._update_pipeline_status("extract-saved-places", True)

        resume_point = pipeline._find_resume_point()
        assert resume_point == 2  # Should resume from step 3

    @patch('main.LabeledPlacesExtractor')
    def test_run_extract_labeled_places(self, mock_extractor_class, pipeline):
        """Test labeled places extraction step"""
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

        # Run step
        success = pipeline._run_extract_labeled_places()
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

        # Check that first step was marked complete
        status = pipeline._get_pipeline_status()
        assert status["extract-labeled-places"]["completed"]
        assert "extract-saved-places" not in status


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

    def test_load_timeline_data(self, generator, sample_data):
        """Test loading timeline data"""
        data = generator.load_timeline_data(sample_data)

        assert "regional_centers" in data
        assert "saved_places" in data
        assert "photo_locations" in data
        assert "review_visits" in data

        assert len(data["regional_centers"]["regions"]) == 2
        assert len(data["saved_places"]["places"]) == 2

    def test_aggregate_visits(self, generator, sample_data):
        """Test visit aggregation"""
        data = generator.load_timeline_data(sample_data)
        aggregated = generator.aggregate_visits(data)

        assert "San Francisco, CA, US" in aggregated
        assert "New York, NY, US" in aggregated

        sf_visits = aggregated["San Francisco, CA, US"]["visits"]
        assert len(sf_visits) == 2  # saved place + photo

        ny_visits = aggregated["New York, NY, US"]["visits"]
        assert len(ny_visits) == 2  # saved place + review

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
        assert timeline["metadata"]["total_regions"] == 2
        assert timeline["metadata"]["total_visits"] == 4


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

    def test_format_date(self, generator):
        """Test date formatting"""
        # ISO string
        assert generator.format_date("2024-01-15T10:30:00Z") == "Jan 15, 2024"

        # Already a date string
        assert generator.format_date("January 15, 2024") == "January 15, 2024"

        # Invalid date
        assert generator.format_date("invalid-date") == "invalid-date"

    def test_generate_region_summary(self, generator, sample_timeline):
        """Test region summary generation"""
        region_data = sample_timeline["regions"]["San Francisco, CA, US"]
        summary = generator.generate_region_summary("San Francisco, CA, US", region_data)

        assert "## San Francisco, CA, US" in summary
        assert "Total Visits:** 6" in summary
        assert "Starred Places:** 2" in summary
        assert "First Visit:** Jan 15, 2023" in summary
        assert "### 2023" in summary
        assert "January (2 visits)" in summary
        assert "- Place A" in summary

    def test_generate_executive_summary(self, generator, sample_timeline):
        """Test executive summary generation"""
        summary = generator.generate_executive_summary(sample_timeline)

        assert "Total Regions Visited:** 2" in summary
        assert "Total Recorded Visits:** 10" in summary
        assert "Date Range:** Jan 1, 2023 - Jan 31, 2024" in summary
        assert "Top 5 Most Visited Regions" in summary
        assert "1. **San Francisco, CA, US** - 6 visits" in summary
        assert "2. **New York, NY, US** - 4 visits" in summary

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
