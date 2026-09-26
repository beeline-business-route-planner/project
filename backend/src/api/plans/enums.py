from enum import StrEnum


class RequestGroupKey(StrEnum):
    EMERGENCY = "emergency"
    TEN_TO_TWELVE = "10-12"
    TWELVE_TO_FOURTEEN = "12-14"
    FOURTEEN_TO_SIXTEEN = "14-16"
    SIXTEEN_TO_EIGHTEEN = "16-18"
    EIGHTEEN_TO_TWENTY = "18-20"
    TWENTY_TO_TWENTY_TWO = "20-22"
    UNASSIGNED = "unassigned"


class EngineerChange(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


class RequestChange(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    REASSIGNED = "reassigned"
    REORDERED = "reordered"
    RESCHEDULED = "rescheduled"
    TRAVEL_CHANGED = "travel_changed"
    ASSIGNMENT_CHANGED = "assignment_changed"
    UNASSIGNED_REASON_CHANGED = "unassigned_reason_changed"
    UNCHANGED = "unchanged"
