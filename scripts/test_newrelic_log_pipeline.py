import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class NewRelicLogPipelineTests(unittest.TestCase):
    def setUp(self):
        self.kubernetes = (ROOT / "infra/newrelic/kubernetes.tf").read_text(encoding="utf-8")
        self.values = (ROOT / "infra/newrelic/values.yaml").read_text(encoding="utf-8")

    def test_low_data_filter_parses_json_and_preserves_only_safe_correlation_fields(self):
        match = re.search(
            r"lowDataModeFilters\s*=\s*<<-FILTER\n(?P<filter>.*?)\n\s*FILTER",
            self.kubernetes,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "A configuração lowDataModeFilters precisa ser explícita")
        filters = match.group("filter")

        self.assertIn("Merge_Log           On", filters)
        self.assertIn("Merge_Log_Trim      On", filters)
        self.assertLess(filters.index("Merge_Log           On"), filters.index("Allowlist_key"))

        allowed_fields = {
            "container_name",
            "namespace_name",
            "pod_name",
            "stream",
            "log",
            "timestamp",
            "level",
            "logger",
            "message",
            "service.name",
            "deployment.environment",
            "request.id",
            "trace.id",
            "span.id",
            "exception.type",
        }
        configured_fields = set(re.findall(r"^\s*Allowlist_key\s+([^\s]+)\s*$", filters, re.MULTILINE))
        self.assertEqual(configured_fields, allowed_fields)

        for sensitive_field in ("cpf", "cnpj", "jwt", "authorization", "password", "senha", "token"):
            with self.subTest(field=sensitive_field):
                self.assertNotIn(f"allowlist_key  {sensitive_field}", filters.lower())

        self.assertIn("Labels              Off", filters)
        self.assertIn("Annotations         Off", filters)

    def test_low_data_mode_and_namespace_scope_remain_enabled(self):
        self.assertRegex(self.values, r"(?m)^global:\n\s+lowDataMode: true$")
        self.assertRegex(self.values, r"(?m)^newrelic-logging:\n\s+enabled: true\n\s+lowDataMode: true$")
        self.assertIn("Regex  namespace_name ^${var.newrelic_namespace}$", self.kubernetes)

    def test_application_fields_used_by_dashboard_are_preserved(self):
        dashboard = (ROOT / "infra/newrelic/dashboard.tf").read_text(encoding="utf-8")
        log_widget = dashboard.split('title  = "Logs correlacionáveis por request/trace"', 1)[1].split("\n    }", 1)[0]
        for field in ("service.name", "deployment.environment", "request.id", "trace.id", "span.id"):
            with self.subTest(field=field):
                self.assertIn(field, log_widget)


if __name__ == "__main__":
    unittest.main()
