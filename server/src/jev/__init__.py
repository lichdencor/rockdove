"""Jev (TypeSafe System One) decision layer for RockDove.

Jev is a decision model: it receives *state* (application context) plus a set
of *typed questions* and returns one typed, calibrated decision per question
in a single parallel pass. It never emits prose, so code can branch directly
on the answers.

RockDove uses it to turn per-peer network metrics into two operational
decisions in a single call:

  * ``redundancy_band`` (Score)   - the RS redundancy *degree* (gradient)
                                     needed for the current link quality.
  * ``should_relay``  (Noul)      - whether to *jump* through an intermediate
                                     relay host instead of sending directly.
  * ``relay_target``  (Choice)    - which of the candidate relays to use.

If Jev is disabled, unconfigured, or uncertain, the module falls back to the
existing deterministic quality table (``metrics.recommender``), so the feature
is additive and never degrades the current behaviour.
"""