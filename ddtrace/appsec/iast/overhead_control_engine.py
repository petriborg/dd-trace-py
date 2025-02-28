"""
The Overhead control engine (OCE) is an element that by design ensures that the overhead does not go over a maximum
limit. It will measure operations being executed in a request and it will deactivate detection
(and therefore reduce the overhead to nearly 0) if a certain threshold is reached.
"""
import os
import threading
from typing import TYPE_CHECKING


if TYPE_CHECKING:  # pragma: no cover
    from typing import Set
    from typing import Type

MAX_REQUESTS = int(os.environ.get("DD_IAST_MAX_CONCURRENT_REQUESTS", 2))
MAX_VULNERABILITIES_PER_REQUEST = int(os.environ.get("DD_IAST_VULNERABILITIES_PER_REQUEST", 2))


class Operation(object):
    """Common operation related to Overhead Control Engine (OCE). Every vulnerabilities/taint_sinks should inherit
    from this class. OCE instance calls these methods to control the overhead produced in each request.
    """

    _lock = threading.Lock()
    _vulnerability_quota = MAX_VULNERABILITIES_PER_REQUEST

    @classmethod
    def reset(cls):
        cls._vulnerability_quota = MAX_VULNERABILITIES_PER_REQUEST

    @classmethod
    def acquire_quota(cls):
        cls._lock.acquire()
        result = False
        if cls._vulnerability_quota > 0:
            cls._vulnerability_quota -= 1
            result = True
        cls._lock.release()
        return result

    @classmethod
    def has_quota(cls):
        cls._lock.acquire()
        result = cls._vulnerability_quota > 0
        cls._lock.release()
        return result


class OverheadControl(object):
    _request_quota = MAX_REQUESTS
    _enabled = False
    _vulnerabilities = set()  # type: Set[Type[Operation]]

    def acquire_request(self):
        """Block a request's quota at start of the request.

        TODO: Implement sampling request in this method
        """
        if self._request_quota > 0:
            self._request_quota -= 1
            self._enabled = True

    def release_request(self):
        """increment request's quota at end of the request.

        TODO: figure out how to check maximum requests per thread
        """
        if self._request_quota < MAX_REQUESTS:
            self._request_quota += 1
            self._enabled = False
        self.vulnerabilities_reset_quota()

    def register(self, klass):
        # type: (Type[Operation]) -> Type[Operation]
        """Register vulnerabilities/taint_sinks. This set of elements will restart for each request."""
        self._vulnerabilities.add(klass)
        return klass

    @property
    def request_has_quota(self):
        # type: () -> bool
        return self._enabled

    def vulnerabilities_reset_quota(self):
        # type: () -> None
        for k in self._vulnerabilities:
            k.reset()
