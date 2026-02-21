"""YAML schedule file loader and validator."""

import logging
import os
from pathlib import Path

import yaml

from . import constants
from .schema import GlobalConfig, Schedule, ScheduleFile

logger = logging.getLogger(__name__)


def find_schedules_location() -> Path | None:
    """
    Locate schedules directory.

    Search order (highest to lowest priority):
    1. BEANSCHEDULE_DIR environment variable → directory mode
    2. schedules/ directory in current directory → directory mode
    3. schedules/ in parent of importers/config.py → directory mode

    Returns:
        Path to schedules directory, or None if not found
    """
    # Check BEANSCHEDULE_DIR env var
    if env_dir := os.getenv(constants.ENV_SCHEDULES_DIR):
        path = Path(env_dir)
        if path.is_dir():
            return path
        logger.warning("BEANSCHEDULE_DIR points to non-existent directory: %s", env_dir)

    # Check current directory for schedules/
    cwd_dir = Path.cwd() / constants.DEFAULT_SCHEDULES_DIR
    if cwd_dir.is_dir():
        return cwd_dir

    # Check config.py parent directory (typical location)
    try:
        config_dir = Path(__file__).parent.parent.parent

        config_schedules_dir = config_dir / constants.DEFAULT_SCHEDULES_DIR
        if config_schedules_dir.is_dir():
            return config_schedules_dir
    except (OSError, ValueError) as e:
        logger.debug("Error checking config parent directory: %s", e)

    return None


def load_schedules_from_path(path: Path) -> ScheduleFile | None:
    """Load schedules from a directory path.

    Args:
        path: Path to a schedules/ directory

    Returns:
        ScheduleFile if path is a valid directory, None if path does not exist

    Raises:
        ValueError: If path is a file (only directories are supported)
    """
    if path.is_file():
        raise ValueError(f"Path must be a schedules/ directory, not a file: {path}")
    if path.is_dir():
        return load_schedules_from_directory(path)
    return None


def load_schedule_from_file(filepath: Path) -> Schedule | None:
    """
    Load a single schedule from an individual YAML file.

    Args:
        filepath: Path to individual schedule YAML file

    Returns:
        Schedule object or None if file is invalid

    Note:
        Errors are logged but not raised - allows directory loading to continue
    """
    try:
        with filepath.open() as f:
            data = yaml.safe_load(f)

        if data is None:
            logger.warning("Empty schedule file: %s", filepath)
            return None

        # Validate and parse with Pydantic
        schedule = Schedule(**data)

        # Store source file path
        schedule.source_file = filepath

        # Validate filename matches schedule ID
        expected_filename = f"{schedule.id}.yaml"
        if filepath.name != expected_filename:
            logger.error(
                "Failed to load schedule from '%s':\n"
                "  Schedule ID '%s' does not match filename.\n"
                "  Expected: '%s'\n"
                "  Found: '%s'\n"
                "  Fix: Rename file to '%s' or change 'id' field to '%s'",
                filepath,
                schedule.id,
                expected_filename,
                filepath.name,
                expected_filename,
                filepath.stem,
            )
            return None

        return schedule

    except yaml.YAMLError as e:
        logger.error("YAML parsing error in '%s': %s", filepath, e)
        return None
    except (ValueError, TypeError) as e:
        logger.error("Invalid schedule data in '%s': %s", filepath, e)
        return None
    except Exception as e:
        logger.error("Unexpected error loading '%s': %s", filepath, e)
        raise


def load_schedules_from_directory(dirpath: Path) -> ScheduleFile | None:
    """
    Load all schedules from a directory structure.

    Directory structure:
        schedules/
        ├── _config.yaml           # Global config (optional)
        ├── schedule-id-1.yaml     # Individual schedule files
        ├── schedule-id-2.yaml
        └── ...

    Args:
        dirpath: Path to schedules directory

    Returns:
        ScheduleFile object with all loaded schedules
    """
    logger.info("Loading schedules from directory: %s", dirpath)

    # Load global config
    config_path = dirpath / constants.CONFIG_FILENAME
    config = GlobalConfig()  # Default config

    if config_path.is_file():
        try:
            with config_path.open() as f:
                config_data = yaml.safe_load(f)

            if config_data is not None:
                config = GlobalConfig(**config_data)
                logger.debug("Loaded global config from: %s", config_path)
        except (yaml.YAMLError, ValueError, TypeError, KeyError) as e:
            logger.warning(
                "Failed to load config from '%s', using defaults: %s", config_path, e
            )

    # Load all schedule files
    schedules = []
    schedule_files = sorted(dirpath.glob(constants.SCHEDULE_FILE_PATTERN))

    for schedule_path in schedule_files:
        # Skip config file
        if schedule_path.name == constants.CONFIG_FILENAME:
            continue

        # Skip hidden files
        if schedule_path.name.startswith("."):
            continue

        schedule = load_schedule_from_file(schedule_path)
        if schedule is not None:
            schedules.append(schedule)

    # Check for duplicate IDs
    seen_ids = {}
    for schedule in schedules:
        if schedule.id in seen_ids:
            logger.error(
                "Duplicate schedule ID '%s' found in multiple files:\n"
                "  First: %s\n"
                "  Duplicate: %s\n"
                "  The duplicate will be ignored.",
                schedule.id,
                seen_ids[schedule.id],
                dirpath / f"{schedule.id}.yaml",
            )
        else:
            seen_ids[schedule.id] = dirpath / f"{schedule.id}.yaml"

    # Remove duplicates (keep first occurrence)
    unique_schedules = []
    seen_ids_set = set()
    for schedule in schedules:
        if schedule.id not in seen_ids_set:
            unique_schedules.append(schedule)
            seen_ids_set.add(schedule.id)

    schedule_file = ScheduleFile(schedules=unique_schedules, config=config)

    logger.info(
        "Loaded %d schedules (%d enabled) from directory: %s",
        len(schedule_file.schedules),
        sum(1 for s in schedule_file.schedules if s.enabled),
        dirpath,
    )

    return schedule_file


def load_schedules() -> ScheduleFile | None:
    """
    Load and validate schedules from the auto-discovered schedules/ directory.

    Uses find_schedules_location() to locate the schedules/ directory,
    then loads all YAML files from it.

    Returns:
        ScheduleFile object or None if no schedules directory found
    """
    path = find_schedules_location()

    if path is None:
        logger.info("No schedules directory found, schedule matching disabled")
        return None

    return load_schedules_from_directory(path)


def get_enabled_schedules(schedule_file: ScheduleFile | None) -> list[Schedule]:
    """
    Get list of enabled schedules.

    Args:
        schedule_file: ScheduleFile object or None

    Returns:
        List of enabled Schedule objects
    """
    if schedule_file is None:
        return []

    return [s for s in schedule_file.schedules if s.enabled]
