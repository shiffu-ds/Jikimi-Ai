"""Simulated camera: scenario -> rendered frames + ground-truth tracks/poses."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import numpy as np
from jikimi_common.timeutil import PK_TZ

from ..ingest.sources import Frame
from .render import render
from .scenarios import Scenario, build
from .world import World


class SimSource:
    def __init__(
        self,
        camera_id: str,
        scenario: str | Scenario,
        fps: float = 5.0,
        start_ts: float | None = None,
        realtime: bool = True,
        loop: bool = False,
        seed: int = 1,
        label: str | None = None,
        tz: ZoneInfo = PK_TZ,
        render_frames: bool = True,
    ) -> None:
        self.camera_id = camera_id
        self._name = scenario if isinstance(scenario, str) else scenario.name
        self.scenario = build(scenario, seed, camera_id) if isinstance(scenario, str) else scenario
        self.fps = fps
        self.realtime = realtime
        self.loop = loop
        self.seed = seed
        self.label = label or camera_id.upper()
        self.tz = tz
        self.render_frames = render_frames
        self._start = time.time() if start_ts is None else start_ts
        self._t = 0.0
        self._loops = 0
        self._world = World(self.scenario.actors, seed=seed, track_offset=0)
        self._rng = np.random.default_rng(seed)

    @property
    def connected(self) -> bool:
        return True

    @property
    def sim_time(self) -> float:
        return self._t

    def _next_loop(self) -> None:
        self._loops += 1
        self._start += self.scenario.duration_s
        self._t = 0.0
        self.scenario = build(self._name, self.seed + self._loops, self.camera_id)
        self._world = World(self.scenario.actors, seed=self.seed + self._loops, track_offset=self._loops * 100_000)

    def read(self) -> Frame | None:
        if self._t > self.scenario.duration_s:
            if not self.loop:
                return None
            self._next_loop()
        ts = self._start + self._t
        if self.realtime:
            delay = ts - time.time()
            if delay > 0:
                time.sleep(delay)
        t = self._t
        self._t += 1.0 / self.fps
        state = self._world.state(t, ts)
        covered = self.scenario.is_covered(t)
        image = None
        if self.render_frames:
            local = datetime.fromtimestamp(ts, UTC).astimezone(self.tz)
            image = render(
                state,
                self.scenario.layout,
                self.label,
                local,
                seed=7,
                night=self.scenario.night,
                covered=covered,
                rng=self._rng,
            )
        return Frame(
            ts=ts,
            image=image,
            tracks=[] if covered else state.tracks,
            poses={} if covered else state.poses,
            truth={"t": t, "scenario": self.scenario.name, "loop": self._loops},
        )

    def close(self) -> None:
        return None
