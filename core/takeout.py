import logging
import shutil
import zipfile
from config import TAKEOUT_FILE_MAPPINGS, TEMP_EXTRACT_DIR
from pathlib import Path

logger = logging.getLogger(__name__)


class TakeoutExtractor:
    """Extract and organize Google Takeout zip files into proper directory structure"""

    def __init__(self, output_dir: Path = Path("takeout")):
        self.output_dir = output_dir

    def find_takeout_zip(self, search_dir: Path = Path(".")) -> Path | None:
        """Find takeout zip file matching the expected pattern"""
        pattern = "takeout-*.zip"
        zip_files = list(search_dir.glob(pattern))

        if not zip_files:
            logger.error(f"No takeout zip files found matching pattern '{pattern}' in {search_dir}")
            return None

        if len(zip_files) > 1:
            logger.warning(f"Multiple takeout zip files found: {[f.name for f in zip_files]}")
            logger.info(f"Using most recent: {max(zip_files, key=lambda f: f.stat().st_mtime).name}")

        return max(zip_files, key=lambda f: f.stat().st_mtime)

    def extract_takeout(self, zip_path: Path | None = None, cleanup: bool = False) -> bool:
        """
        Extract Google Takeout zip file and organize into proper directory structure

        Args:
            zip_path: Path to takeout zip file (auto-detected if None)
            cleanup: Whether to delete the original zip file after extraction

        Returns:
            bool: True if extraction successful, False otherwise
        """
        try:
            if zip_path is None:
                zip_path = self.find_takeout_zip()
                if zip_path is None:
                    return False

            if not zip_path.exists():
                logger.error(f"Zip file not found: {zip_path}")
                return False

            logger.info(f"Extracting takeout from: {zip_path}")

            temp_dir = Path(TEMP_EXTRACT_DIR)
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            temp_dir.mkdir()

            try:
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)

                maps_dir = temp_dir / "Takeout" / "Maps (your places)"
                if not maps_dir.exists():
                    logger.error("Maps (your places) directory not found in extracted files")
                    return False

                output_maps_dir = self.output_dir / "maps" / "your_places"
                output_maps_dir.mkdir(parents=True, exist_ok=True)

                files_moved = 0
                required_files = TAKEOUT_FILE_MAPPINGS

                for source_filename, dest_filename in required_files.items():
                    source_file = maps_dir / source_filename
                    if source_file.exists():
                        dest_file = output_maps_dir / dest_filename
                        shutil.copy2(source_file, dest_file)
                        logger.info(f"Extracted: {source_filename} -> {dest_filename} ({source_file.stat().st_size} bytes)")
                        files_moved += 1
                    else:
                        logger.warning(f"File not found in takeout: {source_filename}")

                if files_moved == 0:
                    logger.error("No required files found in takeout")
                    return False

                logger.info(f"Successfully extracted {files_moved}/{len(required_files)} files to {output_maps_dir}")

                if cleanup:
                    zip_path.unlink()
                    logger.info(f"Deleted original zip file: {zip_path}")

                return True

            finally:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)

        except Exception as e:
            logger.error(f"Error extracting takeout: {e}")
            return False
