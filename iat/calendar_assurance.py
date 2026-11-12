"""Explicit assurance holds, separate from structural v1 calendar validity.

These markers are deny-only review state, not a broker authentication system.
Removing a marker is not independent verification and is never automated here.
"""
UNVERIFIED_PREFIX = 'IAT_UNVERIFIED:'
EXNESS_SOURCE = UNVERIFIED_PREFIX + 'EXNESS_XAUUSD_SCREENSHOT_WINTER_2026_11'
EXNESS_HOLDS = (
    'CALENDAR_SCHEDULE_CONFLICT',
    'CALENDAR_PHASES_UNREPRESENTABLE',
    'HOLIDAY_COVERAGE_UNKNOWN',
    'MAINTENANCE_COVERAGE_UNKNOWN',
)
ASSURANCE_MESSAGES = {
    'CALENDAR_ASSURANCE_UNKNOWN': 'Calendar assurance has not been established.',
    'CALENDAR_SCHEDULE_CONFLICT': 'Observed weekly boundaries conflict with the published session phases.',
    'CALENDAR_PHASES_UNREPRESENTABLE': 'The minute-only calendar cannot represent the published second-level close-only phases.',
    'HOLIDAY_COVERAGE_UNKNOWN': 'Instrument-specific dated holiday and exceptional-closure coverage is unknown.',
    'MAINTENANCE_COVERAGE_UNKNOWN': 'Applicable maintenance intervals have not been established.',
}


def source_holds(source):
    if source == EXNESS_SOURCE:
        return EXNESS_HOLDS
    if source.startswith(UNVERIFIED_PREFIX):
        return ('CALENDAR_ASSURANCE_UNKNOWN',)
    return ()
