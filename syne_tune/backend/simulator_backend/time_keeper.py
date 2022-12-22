# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.
from dataclasses import dataclass, field
import time
from datetime import datetime, timedelta
from typing import NoReturn, Optional, Union

from syne_tune.backend.time_keeper import TimeKeeper


@dataclass
class SimulatedTimeKeeper(TimeKeeper):
    """
    Here, time is simulated. It needs to be advanced explicitly.

    In addition, :meth:`mark_exit` and :meth:`real_time_since_last_recent_exit`
    are used to measure real time spent outside the back-end (i.e., in the tuner
    loop and scheduler). Namely, every method of
    :class:`~syne_tune.backend.SimulatorBackend` calls :meth:`mark_exit` before
    leaving, and :meth:`real_time_since_last_recent_exit` at the start, advancing
    the time counter accordingly.
    """

    _current_time: Optional[float] = field(default=None, init=False)
    _start_time_stamp: Optional[datetime] = field(default=None, init=False)
    _last_recent_exit: Optional[float] = field(default=None, init=False)

    @property
    def start_time_stamp(self) -> datetime:
        """
        :return: Time stamp (datetime) of (last recent) call of ``start_of_time``
        """
        self._assert_has_started()
        return self._start_time_stamp  # type: ignore[return-value]

    def start_of_time(self) -> None:
        # This can be called multiple times, if multiple experiments are
        # run in sequence
        self._current_time = 0
        self._start_time_stamp = datetime.now()
        self.mark_exit()

    def _assert_has_started(self) -> Union[None, NoReturn]:
        assert (
            self._current_time is not None
        ), "RealTimeKeeper needs to be started, by calling start_of_time"
        return None

    def time(self) -> float:
        self._assert_has_started()
        return self._current_time  # type: ignore

    def time_stamp(self) -> datetime:
        self._assert_has_started()
        assert self._start_time_stamp is not None
        delta = timedelta(seconds=self._current_time)  # type: ignore[arg-type]
        return self._start_time_stamp + delta

    def advance(self, step: float) -> None:
        self._assert_has_started()
        assert step >= 0
        self._current_time += step  # type: ignore[operator]

    def advance_to(self, to_time: float) -> None:
        self._assert_has_started()
        self._current_time = max(
            to_time, self._current_time  # type: ignore[arg-type, type-var]
        )

    def mark_exit(self) -> None:
        self._last_recent_exit = time.time()

    def real_time_since_last_recent_exit(self) -> float:
        self._assert_has_started()
        return time.time() - self._last_recent_exit  # type: ignore[operator]
