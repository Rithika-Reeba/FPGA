"""
One active dashboard tab at a time, newest first.

Every browser tab (or window) that opens the dashboard is a separate session, and sessions share one serial port,
one baseline and one active board. Several live tabs used to fight over them (switching the board back and forth,
holding the port, re-reading baselines). The rule now:

  * a tab that OPENS (a new session) becomes the active one at once: the newest has priority;
  * an older tab notices on its next refresh that it was superseded, pauses and shows a notice;
  * a paused tab can take priority back on purpose ("Use this tab"), which pauses the other one.

The registry lives on `sys`, so it survives the module reloads the dashboard does when a baseline changes.
"""

import sys
from typing import Optional

_ATTR = "_fpga_active_session"


def active_session() -> Optional[str]:
    return getattr(sys, _ATTR, None)


def claim(session_id: str) -> None:
    """Make this session the active one (a new tab opening, or an explicit take-over)."""
    setattr(sys, _ATTR, session_id)


def is_active(session_id: str) -> bool:
    """True while this session is the active one. With no active session recorded yet, nobody is superseded."""
    current = active_session()
    return current is None or current == session_id


def release(session_id: str) -> None:
    """Forget the active session if it is this one (used by tests and when a tab is known to be gone)."""
    if active_session() == session_id:
        setattr(sys, _ATTR, None)
