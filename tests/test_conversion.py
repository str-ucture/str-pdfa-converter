import unittest
from pathlib import Path

from str_pdf.conversion import _ps_string, parse_verapdf_report


class ReportParsing(unittest.TestCase):
    def test_compliant(self):
        xml = '<report><jobs><job><validationReport profileName="PDF/A-2b" statement="Pass" isCompliant="true"><details passedRules="1" failedRules="0"/></validationReport></job></jobs></report>'
        self.assertEqual(parse_verapdf_report(xml), (True, "Pass"))

    def test_failed_rules_listed(self):
        xml = '<report><job><validationReport statement="Fail" isCompliant="false"><rule status="failed" clause="6.2" testNumber="1"/></validationReport></job></report>'
        self.assertEqual(parse_verapdf_report(xml), (False, "Fail\nFailed rule 6.2-1"))

    def test_postscript_path_escaping(self):
        self.assertTrue(_ps_string(Path("C:/folder/a(b).icc")).endswith(r"a\(b\).icc"))


if __name__ == "__main__":
    unittest.main()
