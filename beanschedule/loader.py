"""YAML schedule file loader and validator."""

import logging
import os
from pathlib import Path
from typing import Optional

import yaml

from . import constants
from .schema import GlobalConfig, Schedule, ScheduleFile

logger = logging.getLogger(__name__)


def find_schedules_location() -> Optional[tuple[str, Path]]:
    """
    Locate schedules configuration (directory or file).

    Search order (highest to lowest priority):
    1. BEANSCHEDULE_DIR environment variable → directory mode
    2. BEANSCHEDULE_FILE environment variable → file mode
    3. schedules/ directory in current directory → directory mode
    4. schedules.yaml in current directory → file mode (backward compat)
    5. schedules/ in parent of importers/config.py → directory mode
    6. schedules.yaml in parent of importers/config.py → file mode (backward compat)

    Returns:
        Tuple of ("dir", Path) or ("file", Path), or None if not found
    """
    # Check BEANSCHEDULE_DIR env var (new directory mode)
    if env_dir := os.getenv(constants.ENV_SCHEDULES_DIR):
        path = Path(env_dir)
        if path.is_dir():
            return ("dir", path)
        logger.warning("BEANSCHEDULE_DIR points to non-existent directory: %s", env_dir)

    # Check BEANSCHEDULE_FILE env var (existing file mode)
    if env_file := os.getenv(constants.ENV_SCHEDULES_FILE):
        path = Path(env_file)
        if path.is_file():
            return ("file", path)
        logger.warning("BEANSCHEDULE_FILE points to non-existent file: %s", env_file)

    # Check current directory for schedules/ (directory mode)
    cwd_dir = Path.cwd() / constants.DEFAULT_SCHEDULES_DIR
    if cwd_dir.is_dir():
        return ("dir", cwd_dir)

    # Check current directory for schedules.yaml (file mode, backward compat)
    cwd_file = Path.cwd() / constants.DEFAULT_SCHEDULES_FILE
    if cwd_file.is_file():
        return ("file", cwd_file)

    # Check config.py parent directory (typical location)
    try:
        config_dir = Path(__file__).parent.parent.parent

        # Check for schedules/ directory
        config_schedules_dir = config_dir / constants.DEFAULT_SCHEDULES_DIR
        if config_schedules_dir.is_dir():
            return ("dir", config_schedules_dir)

        # Check for schedules.yaml file (backward compat)
        config_schedules_file = config_dir / constants.DEFAULT_SCHEDULES_FILE
        if config_schedules_file.is_file():
            return ("file", config_schedules_file)
    except (OSError, ValueError) as e:
        logger.debug("Error checking config parent directory: %s", e)

    return None


def find_schedules_file() -> Optional[Path]:
    """
    Locate schedules.yaml file.

    DEPRECATED: Use find_schedules_location() instead for directory support.
    Maintained for backward compatibility.

    Search order:
    1. BEANSCHEDULE_FILE environment variable
    2. schedules.yaml in current directory
    3. schedules.yaml in parent of importers/config.py

    Returns:
        Path to schedules.yaml or None if not found
    """
    location = find_schedules_location()
    if location is None:
        return None

    mode, path = location
    if mode == "file":
        return path
    # Directory mode found, but caller expects file
    # Return None to indicate file not found
    return None


def load_schedule_from_file(filepath: Path) -> Optional[Schedule]:
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


def load_schedules_from_directory(dirpath: Path) -> Optional[ScheduleFile]:
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
            logger.warning("Failed to load config from '%s', using defaults: %s", config_path, e)

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


def load_schedules_file(filepath: Optional[Path] = None) -> Optional[ScheduleFile]:
    """
    Load and validate schedules (supports both directory and file formats).

    Supports two formats:
    1. Directory mode: schedules/ directory with individual YAML files
    2. File mode: single schedules.yaml file (legacy/backward compat)

    Args:
        filepath: Optional explicit path to schedules file.
                  If provided, loads as single file (legacy mode).
                  If None, uses find_schedules_location() to auto-discover.

    Returns:
        ScheduleFile object or None if not found or invalid

    Raises:
        yaml.YAMLError: If YAML parsing fails (file mode only)
        pydantic.ValidationError: If schema validation fails (file mode only)
    """
    # If explicit filepath provided, use legacy single-file loading
    if filepath is not None:
        logger.info("Loading schedules from: %s", filepath)

        try:
            with filepath.open() as f:
                data = yaml.safe_load(f)

            if data is None:
                logger.warning("Empty schedules file: %s", filepath)
                return ScheduleFile(schedules=[], config=GlobalConfig())

            # Handle case where schedules key is None (all commented out)
            if data.get("schedules") is None:
                data["schedules"] = []

            # Validate and parse with Pydantic
            schedule_file = ScheduleFile(**data)

            # Set source file for all schedules
            for schedule in schedule_file.schedules:
                schedule.source_file = filepath

            logger.info(
                "Loaded %d schedules (%d enabled)",
                len(schedule_file.schedules),
                sum(1 for s in schedule_file.schedules if s.enabled),
            )

            return schedule_file

        except yaml.YAMLError as e:
            logger.error("YAML parsing error in %s: %s", filepath, e)
            raise
        except Exception as e:
            logger.error("Error loading schedules from %s: %s", filepath, e)
            raise

    # Auto-discover using new location finder
    location = find_schedules_location()

    if location is None:
        logger.info("No schedules file or directory found, schedule matching disabled")
        return None

    mode, path = location

    if mode == "dir":
        return load_schedules_from_directory(path)

    logger.info("Loading schedules from: %s", path)

    try:
        with path.open() as f:
            data = yaml.safe_load(f)

        if data is None:
            logger.warning("Empty schedules file: %s", path)
            return ScheduleFile(schedules=[], config=GlobalConfig())

        # Handle case where schedules key is None (all commented out)
        if data.get("schedules") is None:
            data["schedules"] = []

        # Validate and parse with Pydantic
        schedule_file = ScheduleFile(**data)

        # Set source file for all schedules
        for schedule in schedule_file.schedules:
            schedule.source_file = path

        logger.info(
            "Loaded %d schedules (%d enabled)",
            len(schedule_file.schedules),
            sum(1 for s in schedule_file.schedules if s.enabled),
        )

        return schedule_file

    except yaml.YAMLError as e:
        logger.error("YAML parsing error in %s: %s", path, e)
        raise
    except Exception as e:
        logger.error("Error loading schedules from %s: %s", path, e)
        raise


def get_enabled_schedules(schedule_file: Optional[ScheduleFile]) -> list[Schedule]:
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
