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
