from __future__ import annotations

import os
import stat
import unittest
from pathlib import Path


class CompareCommandTests(unittest.TestCase):
    def test_compare_v0_v1_command_is_executable(self) -> None:
        path = Path(__file__).resolve().parents[1] / "bin" / "compare-v0-v1"
        metadata = path.stat()
        self.assertTrue(stat.S_ISREG(metadata.st_mode))
        self.assertTrue(metadata.st_mode & stat.S_IXUSR)
        self.assertTrue(os.access(path, os.X_OK))


if __name__ == "__main__":
    unittest.main()
