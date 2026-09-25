import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from str_pdf.app import PdfConverterApp, TkinterDnD, path_key, target_for, unique_name


class Naming(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.source = self.folder / "a.pdf"
        self.source.write_bytes(b"%PDF-1.4\n")

    def test_targets(self):
        self.assertEqual(target_for(self.source, "next", None).name, "a_pdfa.pdf")
        self.assertEqual(target_for(self.source, "folder", self.folder / "out"), self.folder / "out" / "a.pdf")
        self.assertEqual(target_for(self.source, "overwrite", None), self.source)

    def test_unique_name_skips_reserved(self):
        self.assertEqual(unique_name(self.source, "-copy", set()).name, "a-copy.pdf")
        reserved = {path_key(self.source.with_name("a-copy.pdf"))}
        self.assertEqual(unique_name(self.source, "-copy", reserved).name, "a-copy-2.pdf")

    def test_queue_add_dedupe_remove(self):
        root = (TkinterDnD.Tk if TkinterDnD else tk.Tk)()
        root.withdraw()
        try:
            app = PdfConverterApp(root)
            app._add_paths([str(self.source), str(self.source), str(self.folder / "missing.pdf")])
            self.assertEqual(len(app.tree.get_children()), 1)
            app.tree.selection_set(app.tree.get_children())
            app._remove_selected()
            self.assertFalse(app.rows)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
