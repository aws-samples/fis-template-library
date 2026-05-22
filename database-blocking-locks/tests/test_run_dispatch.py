# Feature: database-blocking-locks-real-table-targeting, Property 1: Mode dispatch is exact
"""Unit tests verifying ``BlockingLocksHarness.run()`` dispatch.

These tests verify the *dispatch clause* of Property 1 (Mode dispatch is exact):
``run()`` must invoke ``_run_synthetic_mode`` exactly once when
``target_table_name`` is the default synthetic table name, and must invoke
``_run_real_mode`` exactly once when it is anything else. The two methods are
mutually exclusive — the other branch must never be called.

The pure-helper clause of Property 1 (``is_real_mode`` itself) is covered by
the property test in ``test_property_1_mode_dispatch.py``.

Validates: Requirements 1.2, 1.3, 8.1
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


# Constructor parameters that are valid Python values but never actually used
# by ``run()`` once both mode branches are mocked. The harness reads them on
# the constructor only to populate instance attributes.
_HARNESS_KWARGS = dict(
    engine="postgres",
    endpoint="db.example.invalid",
    port=5432,
    dbname="appdb",
    user="appuser",
    password="not-a-real-password",
    waiter_count=1,
    experiment_duration_s=1,
    ramp_time_s=1,
    ramp_steps=1,
)


def _make_harness(harness_module, *, target_table_name: str):
    """Instantiate the harness with the given target table name."""
    return harness_module.BlockingLocksHarness(
        target_table_name=target_table_name,
        **_HARNESS_KWARGS,
    )


def test_default_target_table_name_dispatches_to_synthetic_mode(harness_module):
    """Default ``TargetTableName`` → ``_run_synthetic_mode`` is called exactly once."""
    harness_cls = harness_module.BlockingLocksHarness
    harness = _make_harness(
        harness_module,
        target_table_name=harness_module.DEFAULT_SYNTHETIC_TABLE,
    )

    with patch.object(harness_cls, "_run_synthetic_mode", autospec=True) as synth, \
         patch.object(harness_cls, "_run_real_mode", autospec=True) as real:
        harness.run()

    assert synth.call_count == 1, (
        "Default TargetTableName must dispatch to _run_synthetic_mode exactly once; "
        "got %d calls" % synth.call_count
    )
    assert real.call_count == 0, (
        "Default TargetTableName must NOT dispatch to _run_real_mode; "
        "got %d calls" % real.call_count
    )


def test_non_default_target_table_name_dispatches_to_real_mode(harness_module):
    """Non-default ``TargetTableName`` → ``_run_real_mode`` is called exactly once."""
    harness_cls = harness_module.BlockingLocksHarness
    harness = _make_harness(
        harness_module,
        target_table_name="application_orders",
    )

    with patch.object(harness_cls, "_run_synthetic_mode", autospec=True) as synth, \
         patch.object(harness_cls, "_run_real_mode", autospec=True) as real:
        harness.run()

    assert real.call_count == 1, (
        "Non-default TargetTableName must dispatch to _run_real_mode exactly once; "
        "got %d calls" % real.call_count
    )
    assert synth.call_count == 0, (
        "Non-default TargetTableName must NOT dispatch to _run_synthetic_mode; "
        "got %d calls" % synth.call_count
    )


@pytest.mark.parametrize(
    "target_table_name",
    [
        "application_orders",
        "public.orders",
        "dbo.orders",
        "Orders",  # case-sensitive: differs from default by case alone
        "fis_blocking_locks_target_v2",  # superset of default name
        " fis_blocking_locks_target",  # leading whitespace differs from default
        "",  # empty string is non-default
    ],
)
def test_dispatch_treats_any_non_default_value_as_real_mode(
    harness_module, target_table_name
):
    """Every non-default ``target_table_name`` value routes to Real_Mode."""
    harness_cls = harness_module.BlockingLocksHarness
    harness = _make_harness(harness_module, target_table_name=target_table_name)

    with patch.object(harness_cls, "_run_synthetic_mode", autospec=True) as synth, \
         patch.object(harness_cls, "_run_real_mode", autospec=True) as real:
        harness.run()

    assert real.call_count == 1
    assert synth.call_count == 0
