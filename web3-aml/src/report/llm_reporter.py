"""Current reporting entry; legacy string checks remain explicit baselines only."""
from src.report.audited_reporter import AuditedReportGenerator
from src.report.legacy_reporter import KEYS, resolve_reference, validate_and_render


class LLMReporter(AuditedReportGenerator):
    pass
