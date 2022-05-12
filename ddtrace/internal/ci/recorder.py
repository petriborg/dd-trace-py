"""Configure tracer and generated spans."""

from typing import Any
from typing import ClassVar
from typing import Optional
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from ddtrace import Span

import attr

import ddtrace
from ddtrace.constants import AUTO_KEEP
from ddtrace.contrib.trace_utils import int_service
from ddtrace.ext import ci
from ddtrace.internal import compat
from ddtrace.internal import forksafe
from ddtrace.internal.ci.filters import TraceCiVisibilityFilter
from ddtrace.internal.logger import get_logger


log = get_logger(__name__)


def _extract_repository_name(repository_url):
    # type: (str) -> str
    """Extract repository name from repository url."""
    try:
        return compat.parse.urlparse(repository_url).path.rstrip(".git").rpartition("/")[-1]
    except ValueError:
        # In case of parsing error, default to repository url
        log.warning("Repository name cannot be parsed from repository_url: %s", repository_url)
        return repository_url


@attr.s(eq=False)
class CIRecorder:
    # It behaves similar to a Pin by keeping track of used tracer and other configuration.
    # The important difference is that it is a singleton as it doesn't make sense to have
    # to enable CI Visibility mode multiple times.

    tracer = attr.ib(type=ddtrace.Tracer, default=None)
    # DEV: add coverage reporter here
    config = attr.ib(default=None)
    _tags = attr.ib(type=dict, factory=ci.tags)
    _service = attr.ib(type=str, default=None)

    enabled = False
    _instance = None  # type: ClassVar[Optional[CIRecorder]]
    _lock = forksafe.Lock()

    def __attrs_post_init__(self):
        # type: () -> None
        self.tracer = self.tracer or ddtrace.tracer
        self.tracer.on_start_span(self._set_test_defaults_on_span)

        # detect service name from repository URL if needed
        service = int_service(None, self.config)
        if (
            # repository URL was detected from environment or .git
            self._tags.get(ci.git.REPOSITORY_URL, None)
            # the service name was not changed
            and self.config
            and service == self.config._default_service
        ):
            repository_name = _extract_repository_name(self._tags[ci.git.REPOSITORY_URL])
            self._service = repository_name
        else:
            self._service = self._service or service

    def _set_test_defaults_on_span(
        self,
        span,  # type: Span
    ):
        # type: (...) -> None
        if span.parent_id is None:
            span.service = self._service
            span.context.dd_origin = ci.CI_APP_TEST_ORIGIN
            span.context.sampling_priority = AUTO_KEEP
            span.set_tags(self._tags)

    @classmethod
    def disable(cls):
        # type: () -> None
        with cls._lock:
            if cls._instance is None:
                return

            forksafe.unregister(cls._restart)

            recorder = cls._instance
            try:
                recorder.tracer.shutdown()
            except Exception:
                log.warning("Failed to shutdown tracer", exc_info=True)

            # Remove required tracer filters
            # tracer_filters = recorder.tracer._filters
            # if any(isinstance(tracer_filter, TraceCiVisibilityFilter) for tracer_filter in tracer_filters):
            #     tracer_filters = [
            #         tracer_filter
            #         for tracer_filter in tracer_filters
            #         if not isinstance(tracer_filter, TraceCiVisibilityFilter)
            #     ]
            #     recorder.tracer.configure(settings={"FILTERS": tracer_filters})

            cls._instance = None
            cls.enabled = False

    @classmethod
    def _restart(cls):
        cls.disable()
        cls.enable()

    @classmethod
    def enable(cls, tracer=None, config=None):
        # type: (Optional[ddtrace.Tracer], Optional[Any]) -> None
        with cls._lock:
            if cls._instance is not None:
                return
            recorder = cls(tracer=tracer, config=config)  # type: ignore[arg-type]
            # DEV: start coverage collector worker here
            # DEV: enable agentless mode is required for CI

            # Add required tracer filters
            tracer_filters = recorder.tracer._filters
            if not any(isinstance(tracer_filter, TraceCiVisibilityFilter) for tracer_filter in tracer_filters):
                tracer_filters += [TraceCiVisibilityFilter()]
                recorder.tracer.configure(settings={"FILTERS": tracer_filters})

            forksafe.register(cls._restart)

            cls._instance = recorder
            cls.enabled = True
