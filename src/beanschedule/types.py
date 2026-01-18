"""Type definitions and enums for beanschedule framework."""

from enum import Enum
from typing import Literal


class FrequencyType(str, Enum):
    """Recurrence frequency types."""

    MONTHLY = "MONTHLY"
    WEEKLY = "WEEKLY"
    YEARLY = "YEARLY"
    INTERVAL = "INTERVAL"
    BIMONTHLY = "BIMONTHLY"


class DayOfWeek(str, Enum):
    """Days of the week for weekly recurrence."""

    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


# Mapping from DayOfWeek enum to dateutil weekday constants
WEEKDAY_MAP = {
    DayOfWeek.MON: 0,  # dateutil.rrule.MO
    DayOfWeek.TUE: 1,  # dateutil.rrule.TU
    DayOfWeek.WED: 2,  # dateutil.rrule.WE
    DayOfWeek.THU: 3,  # dateutil.rrule.TH
    DayOfWeek.FRI: 4,  # dateutil.rrule.FR
    DayOfWeek.SAT: 5,  # dateutil.rrule.SA
    DayOfWeek.SUN: 6,  # dateutil.rrule.SU
}


FlagType = Literal["*", "!", "P", "A", "S", "R", "C", "U", "?"]
