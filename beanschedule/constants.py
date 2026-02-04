"""
Global constants for beanschedule.

This module centralizes all magic strings, thresholds, and default values
to improve maintainability and make configuration easier.
"""

from decimal import Decimal

# ============================================================================
# File Paths and Directories
# ============================================================================

CONFIG_FILENAME = "_config.yaml"
SCHEDULE_FILE_PATTERN = "*.yaml"
DEFAULT_SCHEDULES_DIR = "schedules"
DEFAULT_SCHEDULES_FILE = "schedules.yaml"
SYNTHETIC_SCHEDULES_SOURCE = "<schedules>"

# Environment variables for schedule location discovery
ENV_SCHEDULES_DIR = "BEANSCHEDULE_DIR"
ENV_SCHEDULES_FILE = "BEANSCHEDULE_FILE"

# ============================================================================
# Metadata Keys (added to enriched transactions)
# ============================================================================

META_SCHEDULE_ID = "schedule_id"
META_SCHEDULE_MATCHED_DATE = "schedule_matched_date"
META_SCHEDULE_CONFIDENCE = "schedule_confidence"
META_SCHEDULE_PLACEHOLDER = "schedule_placeholder"
META_SCHEDULE_EXPECTED_DATE = "schedule_expected_date"

# Amortization-specific metadata
META_AMORTIZATION_PRINCIPAL = "amortization_principal"
META_AMORTIZATION_INTEREST = "amortization_interest"
META_AMORTIZATION_BALANCE_AFTER = "amortization_balance_after"
META_AMORTIZATION_LINKED_DATE = "amortization_linked_date"
META_AMORTIZATION_PAYMENT_NUMBER = "amortization_payment_number"

# ============================================================================
# Default Configuration Values
# ============================================================================

DEFAULT_DATE_WINDOW_DAYS = 3
DEFAULT_MISSING_PREFIX = "[MISSING]"
DEFAULT_PLACEHOLDER_FLAG = "!"
DEFAULT_CURRENCY = "USD"
DEFAULT_FUZZY_MATCH_THRESHOLD = 0.80
DEFAULT_AMOUNT_TOLERANCE_PERCENT = 0.02  # 2%
SCHEDULE_FILE_VERSION = "1.0"

# ============================================================================
# Matching Algorithm Scoring Weights
# ============================================================================

PAYEE_SCORE_WEIGHT = 0.4  # 40%
AMOUNT_SCORE_WEIGHT = 0.4  # 40%
DATE_SCORE_WEIGHT = 0.2  # 20%

# ============================================================================
# Validation Constraints
# ============================================================================

MIN_DAY_OF_MONTH = 1
MAX_DAY_OF_MONTH = 31
MIN_MONTH = 1
MAX_MONTH = 12
NTH_OCCURRENCE_MIN = -1  # Last occurrence
NTH_OCCURRENCE_MAX = 5  # 5th occurrence
NTH_OCCURRENCE_LAST = -1

# Validation for amortization payment day
PAYMENT_DAY_MIN = 1
PAYMENT_DAY_MAX = 31

# Regex pattern indicators (for detecting if payee_pattern is regex)
REGEX_INDICATORS = ["|", ".*", ".+", "\\", "[", "]", "(", ")", "^", "$"]

# ============================================================================
# Date/Time Constants
# ============================================================================

DATE_RANGE_BUFFER_DAYS = 7  # Buffer for extracting date range from transactions
DEFAULT_MISSING_PLACEHOLDER_WINDOW_DAYS = 3
LAST_DAY_OF_MONTH_INDICATOR = -1

# ============================================================================
# Pattern Detection Configuration
# ============================================================================

# Detector fuzzy matching thresholds
DETECTOR_FUZZY_THRESHOLD = 0.85
DETECTOR_AMOUNT_TOLERANCE_PCT = 0.05  # 5%
DETECTOR_MIN_OCCURRENCES = 3
DETECTOR_MIN_CONFIDENCE = 0.60

# Frequency detection gap ranges (in days)
WEEKLY_GAP_RANGE = (6, 8)  # 7±1 days
BIWEEKLY_GAP_RANGE = (12, 16)  # 14±2 days
MONTHLY_GAP_RANGE = (25, 35)  # 28-32 days
QUARTERLY_GAP_RANGE = (85, 95)  # 88-92 days
YEARLY_GAP_RANGE = (355, 375)  # 360-370 days

# Month-end detection
MONTH_END_DAYS = (28, 29, 30, 31)

# ============================================================================
# Confidence Calculation Weights (for pattern detection)
# ============================================================================

COVERAGE_WEIGHT = 0.5  # Ratio of actual to expected occurrences
REGULARITY_WEIGHT = 0.3  # Consistency of gaps (inverse of variance)
SAMPLE_SIZE_WEIGHT = 0.2  # More transactions = higher confidence

# Sample size scoring parameters
SAMPLE_SIZE_INTERCEPT = 0.7
SAMPLE_SIZE_DENOMINATOR = 15.0

# ============================================================================
# Financial/Decimal Constants
# ============================================================================

CENTS_PRECISION = Decimal("0.01")  # Currency rounding precision
MONTHS_PER_YEAR = 12  # Months in a year
ZERO_BALANCE = Decimal("0")  # Zero balance constant

# ============================================================================
# Display/Formatting Constants
# ============================================================================

LOG_DIVIDER_WIDTH = 70  # Width of log separator lines
MAX_TABLE_COLUMN_WIDTH = 30  # Max width for table columns in CLI

# ============================================================================
# Frequency Interval Constants
# ============================================================================

BIWEEKLY_INTERVAL = 2  # Bi-weekly interval (2 weeks)
MONTHLY_WEEKLY_INTERVAL = 4  # Monthly frequency expressed as weekly intervals
QUARTERLY_MONTHS = 3  # Quarterly = 3 months
SEMIANNUAL_MONTHS = 6  # Semi-annual = 6 months

# ============================================================================
# Pattern Detection Thresholds
# ============================================================================

MIN_GAPS_FOR_STDEV = 2  # Minimum gaps needed for standard deviation
MONTH_END_THRESHOLD = 0.5  # Threshold for month-end detection (50% of dates)

# ============================================================================
# Miscellaneous Constants
# ============================================================================

MIN_BEANGULP_TUPLE_SIZE = 2
PLACEHOLDER_FLAG_TRUE = "true"
MAX_SCHEDULE_ID_LENGTH = 50
DAYS_PER_OCCURRENCE_ESTIMATE = 45  # Days to estimate for single occurrence
