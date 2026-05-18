"""
Event detection is currently disabled.

This module used to detect market-moving events and deliver them through Kakao.
Kakao delivery is no longer part of the operating flow, so the scheduled hook
is intentionally kept as a no-op to avoid repeated token refresh/send failures.
"""


def run_event_detection():
    print("Event detection skipped: Kakao delivery is disabled.")
    return None


if __name__ == "__main__":
    run_event_detection()
