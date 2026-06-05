# Feature: database-blocking-locks-real-table-targeting, Property 1: Mode dispatch is exact
"""Unit tests verifying ``BlockingLocksHarness.prepare_target()`` dispatch.

These tests verify the *dispatch clause* of Property 1 (Mode dispatch is exact):
``prepare_target()`` must invoke ``_prepare_synthetic_target`` exactly once when
``target_table_name`` is the default synthetic table name, and must invoke
``_prepare_real_target`` exactly once when it is anything else. The two methods
are mutually exclusive — the other branch must never be called.

Mode dispatch is the only place in the harness that branches on mode;
everything downstream of ``prepare_target()`` operates on the resolved
``TargetSpec`` and is mode-agnostic. The dispatch property is therefore the
sufficient guarantee that selecting a non-default ``TargetTableName`` exercises
Real_Mode and not Synthetic_Mode.

The pure-helper clause of Property 1 (``is_real_mode`` itself) is covered by
the property test in ``test_property_1_mode_dispatch.py``.

Validates: Requirements 1.2, 1.3, 8.1
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


# Constructor parameters that are valid Python values but never actually used
# by ``prepare_target()`` once both mode branches are mocked. The harness
# reads them on the constructor only to populate instance attributes.
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


def test_default_target_table_name_dispatches_to_synthetic_preparer(harness_module):
    """Default ``TargetTableName`` → ``_prepare_synthetic_target`` is called exactly once."""
    harness_cls = harness_module.BlockingLocksHarness
    harness = _make_harness(
        harness_module,
        target_table_name=harness_module.DEFAULT_SYNTHETIC_TABLE,
    )

    with patch.object(harness_cls, "_prepare_synthetic_target", autospec=True) as synth, \
         patch.object(harness_cls, "_prepare_real_target", autospec=True) as real:
        harness.prepare_target()

    assert synth.call_count == 1, (
        "Default TargetTableName must dispatch to _prepare_synthetic_target exactly once; "
        "got %d calls" % synth.call_count
    )
    assert real.call_count == 0, (
        "Default TargetTableName must NOT dispatch to _prepare_real_target; "
        "got %d calls" % real.call_count
    )


def test_non_default_target_table_name_dispatches_to_real_preparer(harness_module):
    """Non-default ``TargetTableName`` → ``_prepare_real_target`` is called exactly once."""
    harness_cls = harness_module.BlockingLocksHarness
    harness = _make_harness(
        harness_module,
        target_table_name="application_orders",
    )

    with patch.object(harness_cls, "_prepare_synthetic_target", autospec=True) as synth, \
         patch.object(harness_cls, "_prepare_real_target", autospec=True) as real:
        harness.prepare_target()

    assert real.call_count == 1, (
        "Non-default TargetTableName must dispatch to _prepare_real_target exactly once; "
        "got %d calls" % real.call_count
    )
    assert synth.call_count == 0, (
        "Non-default TargetTableName must NOT dispatch to _prepare_synthetic_target; "
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
    """Every non-default ``target_table_name`` value routes to the real preparer."""
    harness_cls = harness_module.BlockingLocksHarness
    harness = _make_harness(harness_module, target_table_name=target_table_name)

    with patch.object(harness_cls, "_prepare_synthetic_target", autospec=True) as synth, \
         patch.object(harness_cls, "_prepare_real_target", autospec=True) as real:
        harness.prepare_target()

    assert real.call_count == 1
    assert synth.call_count == 0
