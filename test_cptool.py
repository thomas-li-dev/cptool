#!/usr/bin/env python3
"""Tests for cptool."""

import argparse
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

# Import cptool modules by path (no .py extension, so we use loader directly)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

import importlib.util
import importlib.machinery

loader = importlib.machinery.SourceFileLoader("cptool", os.path.join(SCRIPT_DIR, "cptool"))
spec = importlib.util.spec_from_loader("cptool", loader)
cptool = importlib.util.module_from_spec(spec)
loader.exec_module(cptool)


class TempDirMixin:
    """Mixin that creates a temp directory and chdir into it for each test."""

    def setUp(self):
        self.orig_dir = os.getcwd()
        self.tmpdir = tempfile.mkdtemp(prefix="cptool_test_")
        os.chdir(self.tmpdir)

    def tearDown(self):
        os.chdir(self.orig_dir)
        shutil.rmtree(self.tmpdir)


class IsolatedConfigMixin:
    """Mixin that redirects CONFIG_DIR/CONFIG_FILE to a temp directory.

    Must be combined with TempDirMixin (which provides self.tmpdir).
    Sets up a fake config dir with a copy of the default template.
    """

    def setUp(self):
        super().setUp()
        self._orig_config_dir = cptool.CONFIG_DIR
        self._orig_config_file = cptool.CONFIG_FILE

        self.config_dir = os.path.join(self.tmpdir, "config")
        os.makedirs(self.config_dir)
        # Copy default template into fake config dir
        shutil.copy2(
            os.path.join(cptool.SCRIPT_DIR, "template.cpp"),
            os.path.join(self.config_dir, "template.cpp"),
        )
        cptool.CONFIG_DIR = self.config_dir
        cptool.CONFIG_FILE = os.path.join(self.config_dir, "config.json")

    def tearDown(self):
        cptool.CONFIG_DIR = self._orig_config_dir
        cptool.CONFIG_FILE = self._orig_config_file
        super().tearDown()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
class TestLoadConfig(IsolatedConfigMixin, TempDirMixin, unittest.TestCase):
    def test_default_config(self):
        config = cptool.load_config()
        self.assertIn("template", config)
        self.assertTrue(config["template"].endswith("template.cpp"))
        # Template should point into the config dir
        self.assertTrue(config["template"].startswith(self.config_dir))

    def test_custom_config_overrides(self):
        custom_template = os.path.join(self.tmpdir, "custom.cpp")
        with open(custom_template, "w") as f:
            f.write("// custom")

        with open(cptool.CONFIG_FILE, "w") as f:
            json.dump({"template": custom_template}, f)

        config = cptool.load_config()
        self.assertEqual(config["template"], custom_template)

    def test_tilde_expansion(self):
        with open(cptool.CONFIG_FILE, "w") as f:
            json.dump({"template": "~/some/template.cpp"}, f)

        config = cptool.load_config()
        self.assertNotIn("~", config["template"])
        self.assertTrue(config["template"].startswith("/"))

    def test_auto_creates_config_dir(self):
        # Point to a non-existent config dir
        new_dir = os.path.join(self.tmpdir, "newconfig")
        cptool.CONFIG_DIR = new_dir
        cptool.CONFIG_FILE = os.path.join(new_dir, "config.json")

        config = cptool.load_config()
        self.assertTrue(os.path.isdir(new_dir))
        self.assertTrue(os.path.isfile(os.path.join(new_dir, "template.cpp")))
        self.assertTrue(config["template"].endswith("template.cpp"))


# ---------------------------------------------------------------------------
# create_problem
# ---------------------------------------------------------------------------
class TestCreateProblem(IsolatedConfigMixin, TempDirMixin, unittest.TestCase):
    def get_config(self):
        return cptool.load_config()

    def test_creates_directory_structure(self):
        config = self.get_config()
        result = cptool.create_problem("sol", config)
        self.assertTrue(result)
        self.assertTrue(os.path.isdir("sol"))
        self.assertTrue(os.path.isdir("sol/samples"))
        self.assertTrue(os.path.isfile("sol/sol.cpp"))
        self.assertTrue(os.path.isfile("sol/Makefile"))

    def test_cpp_file_contains_template(self):
        config = self.get_config()
        cptool.create_problem("sol", config)
        with open("sol/sol.cpp") as f:
            content = f.read()
        with open(config["template"]) as f:
            expected = f.read()
        self.assertEqual(content, expected)

    def test_makefile_has_correct_prog_name(self):
        config = self.get_config()
        cptool.create_problem("myprog", config)
        with open("myprog/Makefile") as f:
            content = f.read()
        self.assertIn("PROG = myprog", content)
        self.assertNotIn("__PROG__", content)

    def test_makefile_has_debug_and_fast(self):
        config = self.get_config()
        cptool.create_problem("sol", config)
        with open("sol/Makefile") as f:
            content = f.read()
        self.assertIn("DEBUGFLAGS", content)
        self.assertIn("FASTFLAGS", content)
        self.assertIn("fast:", content)
        self.assertIn("_GLIBCXX_DEBUG", content)

    def test_samples_written(self):
        config = self.get_config()
        samples = [
            {"input": "1 2\n", "output": "3\n"},
            {"input": "5 10\n", "output": "15\n"},
        ]
        cptool.create_problem("sol", config, samples=samples)

        with open("sol/samples/1.in") as f:
            self.assertEqual(f.read(), "1 2\n")
        with open("sol/samples/1.out") as f:
            self.assertEqual(f.read(), "3\n")
        with open("sol/samples/2.in") as f:
            self.assertEqual(f.read(), "5 10\n")
        with open("sol/samples/2.out") as f:
            self.assertEqual(f.read(), "15\n")

    def test_no_samples_means_empty_samples_dir(self):
        config = self.get_config()
        cptool.create_problem("sol", config)
        self.assertTrue(os.path.isdir("sol/samples"))
        self.assertEqual(os.listdir("sol/samples"), [])

    def test_existing_directory_returns_false(self):
        config = self.get_config()
        os.makedirs("sol")
        result = cptool.create_problem("sol", config)
        self.assertFalse(result)

    def test_base_dir(self):
        config = self.get_config()
        os.makedirs("contest")
        result = cptool.create_problem("A", config, base_dir="contest")
        self.assertTrue(result)
        self.assertTrue(os.path.isdir("contest/A"))
        self.assertTrue(os.path.isfile("contest/A/A.cpp"))
        self.assertTrue(os.path.isfile("contest/A/Makefile"))
        with open("contest/A/Makefile") as f:
            self.assertIn("PROG = A", f.read())

    def test_missing_template_creates_empty_cpp(self):
        config = {"template": "/nonexistent/path/template.cpp"}
        cptool.create_problem("sol", config)
        with open("sol/sol.cpp") as f:
            self.assertEqual(f.read(), "")


# ---------------------------------------------------------------------------
# CLI: problem
# ---------------------------------------------------------------------------
class TestCmdProblem(TempDirMixin, unittest.TestCase):
    def run_cptool(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "cptool")] + list(args),
            capture_output=True, text=True,
        )

    def test_problem_no_download_creates_problem(self):
        r = self.run_cptool("problem", "abc", "--no-download")
        self.assertEqual(r.returncode, 0)
        self.assertIn("abc/abc.cpp", r.stdout)
        self.assertTrue(os.path.isfile("abc/abc.cpp"))
        self.assertTrue(os.path.isfile("abc/Makefile"))

    def test_problem_no_download_duplicate_fails(self):
        self.run_cptool("problem", "abc", "--no-download")
        r = self.run_cptool("problem", "abc", "--no-download")
        self.assertIn("already exists", r.stderr)


# ---------------------------------------------------------------------------
# CLI: contest
# ---------------------------------------------------------------------------
class TestCmdContest(TempDirMixin, unittest.TestCase):
    def run_cptool(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "cptool")] + list(args),
            capture_output=True, text=True,
        )

    def test_contest_no_download_creates_all_problems(self):
        r = self.run_cptool("contest", "cf100", "--no-download", "--count", "5")
        self.assertEqual(r.returncode, 0)
        for label in "ABCDE":
            self.assertTrue(os.path.isdir(f"cf100/{label}"))
            self.assertTrue(os.path.isfile(f"cf100/{label}/{label}.cpp"))
            self.assertTrue(os.path.isfile(f"cf100/{label}/Makefile"))
            with open(f"cf100/{label}/Makefile") as f:
                self.assertIn(f"PROG = {label}", f.read())

    def test_contest_no_download_duplicate_fails(self):
        self.run_cptool("contest", "cf100", "--no-download", "--count", "3")
        r = self.run_cptool("contest", "cf100", "--no-download", "--count", "3")
        self.assertIn("already exists", r.stderr)

    def test_contest_no_download_single_problem(self):
        r = self.run_cptool("contest", "single", "--no-download", "--count", "1")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(os.path.isfile("single/A/A.cpp"))

    def test_contest_no_download_many_problems(self):
        r = self.run_cptool("contest", "big", "--no-download", "--count", "28")
        self.assertEqual(r.returncode, 0)
        # A-Z plus A1, A2
        self.assertTrue(os.path.isdir("big/Z"))
        self.assertTrue(os.path.isdir("big/A1"))
        self.assertTrue(os.path.isdir("big/A2"))

    def test_contest_no_download_requires_count(self):
        r = self.run_cptool("contest", "cf100", "--no-download")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--count is required", r.stderr)


# ---------------------------------------------------------------------------
# Competitive Companion listener
# ---------------------------------------------------------------------------
_next_test_port = 11100  # unique ports to avoid conflicts between tests


def _alloc_port():
    global _next_test_port
    p = _next_test_port
    _next_test_port += 1
    return p


class TestListenForProblems(unittest.TestCase):
    def _post_data(self, data, port, delay=0.3):
        """Send a POST request to the listener after a short delay."""
        def _send():
            time.sleep(delay)
            conn = http.client.HTTPConnection("127.0.0.1", port)
            body = json.dumps(data)
            conn.request("POST", "/", body, {"Content-Type": "application/json"})
            conn.getresponse()
            conn.close()
        t = threading.Thread(target=_send, daemon=True)
        t.start()
        return t

    def test_single_problem(self):
        port = _alloc_port()
        data = {
            "name": "Test Problem",
            "tests": [{"input": "1\n", "output": "2\n"}],
            "batch": {"id": "abc", "size": 1},
        }
        self._post_data(data, port=port)
        problems = cptool.listen_for_problems(count=1, port=port)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["name"], "Test Problem")
        self.assertEqual(len(problems[0]["tests"]), 1)

    def test_batch_auto_detect(self):
        port = _alloc_port()
        for i in range(3):
            data = {
                "name": f"Problem {i}",
                "tests": [{"input": f"{i}\n", "output": f"{i*2}\n"}],
                "batch": {"id": "xyz", "size": 3},
            }
            self._post_data(data, port=port, delay=0.3 + i * 0.2)

        problems = cptool.listen_for_problems(count=None, port=port)
        self.assertEqual(len(problems), 3)
        self.assertEqual(problems[0]["name"], "Problem 0")
        self.assertEqual(problems[2]["name"], "Problem 2")

    def test_multiple_samples(self):
        port = _alloc_port()
        data = {
            "name": "Multi",
            "tests": [
                {"input": "a\n", "output": "b\n"},
                {"input": "c\n", "output": "d\n"},
                {"input": "e\n", "output": "f\n"},
            ],
            "batch": {"id": "m", "size": 1},
        }
        self._post_data(data, port=port)
        problems = cptool.listen_for_problems(count=1, port=port)
        self.assertEqual(len(problems[0]["tests"]), 3)


# ---------------------------------------------------------------------------
# CLI: problem download (end-to-end with simulated CC)
# ---------------------------------------------------------------------------
class TestCmdProblemDownload(TempDirMixin, unittest.TestCase):
    def run_cptool_bg(self, *args):
        """Run cptool in a subprocess (non-blocking)."""
        return subprocess.Popen(
            [sys.executable, os.path.join(SCRIPT_DIR, "cptool")] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def test_problem_download_creates_problem_with_samples(self):
        data = {
            "name": "A+B",
            "tests": [
                {"input": "1 2\n", "output": "3\n"},
                {"input": "10 20\n", "output": "30\n"},
            ],
            "batch": {"id": "t1", "size": 1},
        }
        proc = self.run_cptool_bg("problem", "aplusb")
        time.sleep(0.5)
        conn = http.client.HTTPConnection("127.0.0.1", cptool.CC_PORT)
        conn.request("POST", "/", json.dumps(data), {"Content-Type": "application/json"})
        conn.getresponse()
        conn.close()
        proc.wait(timeout=5)

        self.assertTrue(os.path.isfile("aplusb/aplusb.cpp"))
        self.assertTrue(os.path.isfile("aplusb/Makefile"))
        with open("aplusb/samples/1.in") as f:
            self.assertEqual(f.read(), "1 2\n")
        with open("aplusb/samples/2.out") as f:
            self.assertEqual(f.read(), "30\n")


# ---------------------------------------------------------------------------
# CLI: contest download (end-to-end with simulated CC batch)
# ---------------------------------------------------------------------------
class TestCmdContestDownload(TempDirMixin, unittest.TestCase):
    def run_cptool_bg(self, *args):
        return subprocess.Popen(
            [sys.executable, os.path.join(SCRIPT_DIR, "cptool")] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def test_contest_download_creates_all_problems(self):
        proc = self.run_cptool_bg("contest", "cf999")
        time.sleep(0.5)

        for i in range(3):
            data = {
                "name": f"Problem {chr(65+i)}",
                "tests": [{"input": f"{i}\n", "output": f"{i*10}\n"}],
                "batch": {"id": "b1", "size": 3},
            }
            conn = http.client.HTTPConnection("127.0.0.1", cptool.CC_PORT)
            conn.request("POST", "/", json.dumps(data), {"Content-Type": "application/json"})
            conn.getresponse()
            conn.close()
            time.sleep(0.2)

        proc.wait(timeout=5)

        for label in "ABC":
            self.assertTrue(os.path.isdir(f"cf999/{label}"))
            self.assertTrue(os.path.isfile(f"cf999/{label}/{label}.cpp"))
            self.assertTrue(os.path.isfile(f"cf999/{label}/Makefile"))
            self.assertTrue(os.path.isfile(f"cf999/{label}/samples/1.in"))
            self.assertTrue(os.path.isfile(f"cf999/{label}/samples/1.out"))

        # Verify sample content for problem C (index 2)
        with open("cf999/C/samples/1.in") as f:
            self.assertEqual(f.read(), "2\n")
        with open("cf999/C/samples/1.out") as f:
            self.assertEqual(f.read(), "20\n")


# ---------------------------------------------------------------------------
# Makefile template
# ---------------------------------------------------------------------------
class TestMakefileTemplate(unittest.TestCase):
    def test_template_file_exists(self):
        self.assertTrue(os.path.isfile(cptool.MAKEFILE_TEMPLATE))

    def test_template_has_placeholder(self):
        with open(cptool.MAKEFILE_TEMPLATE) as f:
            content = f.read()
        self.assertIn("__PROG__", content)

    def test_template_has_required_targets(self):
        with open(cptool.MAKEFILE_TEMPLATE) as f:
            content = f.read()
        self.assertIn("all:", content)
        self.assertIn("fast:", content)
        self.assertIn("test:", content)
        self.assertIn("clean:", content)

    def test_template_has_debug_and_fast_flags(self):
        with open(cptool.MAKEFILE_TEMPLATE) as f:
            content = f.read()
        # Debug should have glibcxx debug
        self.assertIn("_GLIBCXX_DEBUG", content)
        # Fast should not have debug macros (FASTFLAGS line)
        lines = content.splitlines()
        fast_line = [l for l in lines if l.startswith("FASTFLAGS")]
        self.assertEqual(len(fast_line), 1)
        self.assertNotIn("_GLIBCXX_DEBUG", fast_line[0])
        self.assertNotIn("_FORTIFY_SOURCE", fast_line[0])
        self.assertNotIn("fstack-protector", fast_line[0])

    def test_template_phony_targets(self):
        with open(cptool.MAKEFILE_TEMPLATE) as f:
            content = f.read()
        self.assertIn(".PHONY:", content)
        self.assertIn("fast", content)


# ---------------------------------------------------------------------------
# parse_makefile_flags
# ---------------------------------------------------------------------------
class TestParseMakefileFlags(unittest.TestCase):
    def test_parses_all_flag_sets(self):
        flags = cptool.parse_makefile_flags()
        self.assertIn("WARNFLAGS", flags)
        self.assertIn("DEBUGFLAGS", flags)
        self.assertIn("FASTFLAGS", flags)

    def test_warnflags_expanded_in_debug(self):
        flags = cptool.parse_makefile_flags()
        # DEBUGFLAGS should contain the actual warning flags, not $(WARNFLAGS)
        self.assertNotIn("$(WARNFLAGS)", flags["DEBUGFLAGS"])
        self.assertIn("-Wall", flags["DEBUGFLAGS"])

    def test_warnflags_expanded_in_fast(self):
        flags = cptool.parse_makefile_flags()
        self.assertNotIn("$(WARNFLAGS)", flags["FASTFLAGS"])
        self.assertIn("-Wall", flags["FASTFLAGS"])

    def test_debug_has_debug_macros(self):
        flags = cptool.parse_makefile_flags()
        self.assertIn("-D_GLIBCXX_DEBUG", flags["DEBUGFLAGS"])

    def test_fast_lacks_debug_macros(self):
        flags = cptool.parse_makefile_flags()
        self.assertNotIn("_GLIBCXX_DEBUG", flags["FASTFLAGS"])


# ---------------------------------------------------------------------------
# PCH command
# ---------------------------------------------------------------------------
class TestCmdPch(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._orig_pch_dir = cptool.PCH_DIR
        cptool.PCH_DIR = os.path.join(self.tmpdir, "pch")

    def tearDown(self):
        cptool.PCH_DIR = self._orig_pch_dir
        super().tearDown()

    def test_clean_nonexistent(self):
        args = argparse.Namespace(clean=True)
        # Should not raise
        cptool.cmd_pch(args)

    def test_clean_removes_dir(self):
        os.makedirs(cptool.PCH_DIR)
        args = argparse.Namespace(clean=True)
        cptool.cmd_pch(args)
        self.assertFalse(os.path.exists(cptool.PCH_DIR))

    def test_build_creates_gch_files(self):
        args = argparse.Namespace(clean=False)
        cptool.cmd_pch(args)
        gch_dir = os.path.join(cptool.PCH_DIR, "bits", "stdc++.h.gch")
        self.assertTrue(os.path.isfile(os.path.join(gch_dir, "debug.gch")))
        self.assertTrue(os.path.isfile(os.path.join(gch_dir, "fast.gch")))

    def test_build_creates_wrapper_header(self):
        args = argparse.Namespace(clean=False)
        cptool.cmd_pch(args)
        header = os.path.join(cptool.PCH_DIR, "bits", "stdc++.h")
        self.assertTrue(os.path.isfile(header))
        with open(header) as f:
            content = f.read()
        self.assertIn("#include_next", content)

    def test_rebuild_overwrites(self):
        args = argparse.Namespace(clean=False)
        cptool.cmd_pch(args)
        gch = os.path.join(cptool.PCH_DIR, "bits", "stdc++.h.gch", "debug.gch")
        mtime1 = os.path.getmtime(gch)
        import time
        time.sleep(0.1)
        cptool.cmd_pch(args)
        mtime2 = os.path.getmtime(gch)
        self.assertGreater(mtime2, mtime1)


# ---------------------------------------------------------------------------
# Makefile template includes PCHDIR
# ---------------------------------------------------------------------------
class TestMakefilePCH(TempDirMixin, unittest.TestCase):
    def test_makefile_has_pchdir(self):
        with open(cptool.MAKEFILE_TEMPLATE) as f:
            content = f.read()
        self.assertIn("PCHDIR", content)
        self.assertIn("-I$(PCHDIR)", content)

    def test_makefile_has_pch_auto_build_rules(self):
        with open(cptool.MAKEFILE_TEMPLATE) as f:
            content = f.read()
        self.assertIn("PCHHEADER", content)
        self.assertIn("PCHDEBUG", content)
        self.assertIn("PCHFAST", content)
        self.assertIn("g++ -x c++-header $(DEBUGFLAGS)", content)
        self.assertIn("g++ -x c++-header $(FASTFLAGS)", content)

    def test_makefile_auto_builds_pch(self):
        """Test that make auto-builds PCH if missing, then compiles."""
        # Use isolated PCH dir to avoid affecting real cache
        pch_dir = os.path.join(self.tmpdir, "pch")

        # Create problem directory with source file
        prob_dir = os.path.join(self.tmpdir, "prob")
        os.makedirs(os.path.join(prob_dir, "samples"))
        with open(os.path.join(prob_dir, "prob.cpp"), "w") as f:
            f.write('#include <bits/stdc++.h>\n'
                    'using namespace std;\n'
                    'signed main() { cout << 42 << endl; }\n')

        # Write Makefile from template, overriding PCHDIR
        with open(cptool.MAKEFILE_TEMPLATE) as f:
            makefile = f.read().replace("__PROG__", "prob")
        # Override PCHDIR to use our temp dir
        makefile = makefile.replace(
            "PCHDIR = $(HOME)/.cache/cptool/pch",
            f"PCHDIR = {pch_dir}",
        )
        with open(os.path.join(prob_dir, "Makefile"), "w") as f:
            f.write(makefile)

        # PCH should not exist yet
        self.assertFalse(os.path.exists(
            os.path.join(pch_dir, "bits", "stdc++.h.gch", "debug.gch")))

        # Running make should auto-build PCH then compile
        result = subprocess.run(
            ["make"], cwd=prob_dir,
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        # PCH should now exist
        self.assertTrue(os.path.exists(
            os.path.join(pch_dir, "bits", "stdc++.h.gch", "debug.gch")))
        # Binary should exist
        self.assertTrue(os.path.isfile(os.path.join(prob_dir, "prob")))

        # Verify output is correct
        run = subprocess.run(
            [os.path.join(prob_dir, "prob")],
            capture_output=True, text=True,
        )
        self.assertEqual(run.stdout.strip(), "42")

    def test_makefile_fast_auto_builds_pch(self):
        """Test that make fast auto-builds fast PCH if missing."""
        pch_dir = os.path.join(self.tmpdir, "pch")

        prob_dir = os.path.join(self.tmpdir, "prob")
        os.makedirs(os.path.join(prob_dir, "samples"))
        with open(os.path.join(prob_dir, "prob.cpp"), "w") as f:
            f.write('#include <bits/stdc++.h>\n'
                    'using namespace std;\n'
                    'signed main() { cout << 99 << endl; }\n')

        with open(cptool.MAKEFILE_TEMPLATE) as f:
            makefile = f.read().replace("__PROG__", "prob")
        makefile = makefile.replace(
            "PCHDIR = $(HOME)/.cache/cptool/pch",
            f"PCHDIR = {pch_dir}",
        )
        with open(os.path.join(prob_dir, "Makefile"), "w") as f:
            f.write(makefile)

        result = subprocess.run(
            ["make", "fast"], cwd=prob_dir,
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        # Fast PCH should exist
        self.assertTrue(os.path.exists(
            os.path.join(pch_dir, "bits", "stdc++.h.gch", "fast.gch")))
        # Debug PCH should NOT exist (only built what was needed)
        self.assertFalse(os.path.exists(
            os.path.join(pch_dir, "bits", "stdc++.h.gch", "debug.gch")))


# ---------------------------------------------------------------------------
# problem_labels
# ---------------------------------------------------------------------------
class TestProblemLabels(unittest.TestCase):
    def test_single(self):
        self.assertEqual(cptool.problem_labels(1), ["A"])

    def test_five(self):
        self.assertEqual(cptool.problem_labels(5), ["A", "B", "C", "D", "E"])

    def test_26(self):
        labels = cptool.problem_labels(26)
        self.assertEqual(labels[0], "A")
        self.assertEqual(labels[25], "Z")
        self.assertEqual(len(labels), 26)

    def test_overflow_past_z(self):
        labels = cptool.problem_labels(28)
        self.assertEqual(labels[25], "Z")
        self.assertEqual(labels[26], "A1")
        self.assertEqual(labels[27], "A2")

    def test_zero(self):
        self.assertEqual(cptool.problem_labels(0), [])


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------
class TestArgParsing(TempDirMixin, unittest.TestCase):
    def run_cptool(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "cptool")] + list(args),
            capture_output=True, text=True,
        )

    def test_no_args_shows_help(self):
        r = self.run_cptool()
        self.assertNotEqual(r.returncode, 0)

    def test_help_flag(self):
        r = self.run_cptool("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("problem", r.stdout)
        self.assertIn("contest", r.stdout)
        self.assertIn("pch", r.stdout)

    def test_problem_missing_name(self):
        r = self.run_cptool("problem")
        self.assertNotEqual(r.returncode, 0)

    def test_contest_no_download_non_integer_count(self):
        r = self.run_cptool("contest", "foo", "--no-download", "--count", "bar")
        self.assertNotEqual(r.returncode, 0)

    def test_invalid_subcommand(self):
        r = self.run_cptool("bogus")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
