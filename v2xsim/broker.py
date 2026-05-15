"""In-process V2X broker (Sprint 3 module 5).

Glue layer between RSU publishers and CAV subscribers. Implements PUB/SUB
semantics over an in-memory queue; deliberately avoids OS-level transport
(ZeroMQ, etc.) so that ablation runs stay deterministic given seeded RNGs
and so that broker behaviour is fully covered by pytest.

(Process isolation across physical hosts is proposal §6 Future Work — when
that happens, this Broker becomes the wire-compatible reference that the
process-isolated implementation must match bit-for-bit.)

Per outgoing CPM, broker applies three channel effects:

  1. **PDR draw** per (sender, receiver) pair using `PDRModel`.
     False ⇒ that receiver does not get this message; no scheduling cost.
  2. **Latency draw** per surviving pair using `LatencyModel`.
     The drawn latency sets `sim_time_deliver_ms = sim_time_sent_ms + latency`.
  3. **CBR feedback** — every publish() call charges the channel for
     `t_tx_ms` (a function of payload size at current CBR). Future publishes
     observe the updated CBR via a sliding window of recent transmissions.

Receivers are passed in explicitly per publish() — the caller (RSU /
simulator main loop) decides who is in range. Broker is topology-agnostic.

CARLA main loop pattern (caller side, conceptual):

    for tick in simulation:
        sim_time_ms = tick * 50  # CARLA dt = 0.05 s
        for rsu in rsus:
            cpm_bytes = rsu.encode_current_observation()
            receivers = [(cav.id, distance(rsu, cav)) for cav in cavs_near(rsu)]
            broker.publish(rsu.id, cpm_bytes, receivers, sim_time_ms)
        for msg in broker.deliveries_due(sim_time_ms):
            cav_by_id[msg.receiver_id].on_cpm(msg.payload_bytes)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .latency import LatencyModel
from .pdr import PDRModel


@dataclass(frozen=True)
class CPMTransmission:
    """One scheduled CPM delivery to one receiver.

    Frozen so callers can safely cache references; broker emits fresh
    instances for every accepted (sender, receiver) pair.
    """
    msg_id: int
    sender_id: str
    receiver_id: str
    sim_time_sent_ms: float
    sim_time_deliver_ms: float
    payload_bytes: bytes


@dataclass
class Broker:
    """In-process PUB/SUB broker with literature-grounded channel effects.

    Deterministic given the seeded RNGs in `latency` and `pdr`. Tick-driven:
    the caller advances simulation time and calls `deliveries_due(t)` to
    pull messages whose scheduled delivery time is ≤ t.
    """

    latency: LatencyModel
    pdr: PDRModel
    cbr_window_ms: float = 1000.0

    # Internal state — do not mutate directly.
    _next_msg_id: int = field(default=0, init=False, repr=False)
    _pending: list[CPMTransmission] = field(default_factory=list, init=False, repr=False)
    # (sim_time_ms, tx_duration_ms) for each successful publish() call.
    _tx_history: list[tuple[float, float]] = field(default_factory=list, init=False, repr=False)

    # --- publication ----------------------------------------------------

    def publish(
        self,
        sender_id: str,
        payload_bytes: bytes,
        receivers: Iterable[tuple[str, float]],
        sim_time_ms: float,
    ) -> list[CPMTransmission]:
        """Publish one CPM to a list of receivers, each with its own distance.

        Returns the list of CPMTransmissions accepted (PDR-survived and
        scheduled for future delivery). Per-receiver decisions are independent.

        Charges the channel exactly once per publish(), regardless of the
        receiver count — broadcast radio is shared, not multiplied. Empty
        receivers still charges the channel (RSU broadcasts whether or not
        anyone listens).
        """
        cbr = self.channel_busy_ratio(sim_time_ms)
        payload_size = len(payload_bytes)

        # Channel-occupation time, evaluated once at current CBR.
        tx_duration_ms = self.latency.components(0.0, payload_size, cbr)["t_tx_ms"]
        self._tx_history.append((sim_time_ms, tx_duration_ms))

        accepted: list[CPMTransmission] = []
        for receiver_id, distance_m in receivers:
            if not self.pdr.delivers(distance_m, cbr):
                continue

            latency_ms = self.latency.sample(distance_m, payload_size, cbr)
            msg = CPMTransmission(
                msg_id=self._next_msg_id,
                sender_id=sender_id,
                receiver_id=receiver_id,
                sim_time_sent_ms=sim_time_ms,
                sim_time_deliver_ms=sim_time_ms + latency_ms,
                payload_bytes=payload_bytes,
            )
            self._next_msg_id += 1
            self._pending.append(msg)
            accepted.append(msg)

        return accepted

    # --- delivery -------------------------------------------------------

    def deliveries_due(
        self,
        sim_time_ms: float,
        receiver_id: str | None = None,
    ) -> list[CPMTransmission]:
        """Pop pending transmissions whose deliver time ≤ sim_time_ms.

        If `receiver_id` is given, only that receiver's due messages are
        popped; the rest stay in the queue for their own consumers. If None,
        all due messages are popped (single-consumer pattern; legacy default
        and convenient for tests with one collector).

        Returned list is sorted by (deliver_time, sender_id, msg_id) for
        deterministic replay across runs with the same seed.
        """
        due: list[CPMTransmission] = []
        keep: list[CPMTransmission] = []
        for m in self._pending:
            if m.sim_time_deliver_ms <= sim_time_ms and (
                receiver_id is None or m.receiver_id == receiver_id
            ):
                due.append(m)
            else:
                keep.append(m)
        self._pending = keep
        due.sort(key=lambda m: (m.sim_time_deliver_ms, m.sender_id, m.msg_id))
        return due

    # --- CBR ------------------------------------------------------------

    def channel_busy_ratio(self, sim_time_ms: float | None = None) -> float:
        """Estimate channel busy ratio over the last `cbr_window_ms`.

        CBR = sum(tx_duration in window) / cbr_window_ms, clamped to [0, 1].
        If `sim_time_ms` is None, uses the most recent transmission's time
        as the window endpoint.

        Side effect: prunes `_tx_history` entries older than the window.
        Safe to call repeatedly.
        """
        if not self._tx_history:
            return 0.0

        if sim_time_ms is None:
            sim_time_ms = self._tx_history[-1][0]

        cutoff = sim_time_ms - self.cbr_window_ms
        self._tx_history = [(t, d) for (t, d) in self._tx_history if t >= cutoff]

        if not self._tx_history:
            return 0.0

        total_busy_ms = sum(d for _, d in self._tx_history)
        return min(1.0, total_busy_ms / self.cbr_window_ms)

    # --- diagnostics ----------------------------------------------------

    def pending_count(self) -> int:
        """Number of in-flight (scheduled but undelivered) transmissions."""
        return len(self._pending)
