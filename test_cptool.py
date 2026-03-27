#!/usr/bin/env python3
"""Tests for cpt."""

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

import importlib.util
import importlib.machinery

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CPT = os.path.join(SCRIPT_DIR, "cpt")

loader = importlib.machinery.SourceFileLoader("cpt", CPT)
spec = importlib.util.spec_from_loader("cpt", loader)
cpt = importlib.util.module_from_spec(spec)
loader.exec_module(cpt)


class TempDirMixin:
    """Creates a temp directory and chdir into it for each test."""

    def setUp(self):
        self.orig_dir = os.getcwd()
        self.tmpdir = tempfile.mkdtemp(prefix="cpt_test_")
        os.chdir(self.tmpdir)

    def tearDown(self):
        os.chdir(self.orig_dir)
        shutil.rmtree(self.tmpdir)


class IsolatedConfigMixin:
    """Redirects CONFIG_DIR to a temp directory with a copy of the default template."""

    def setUp(self):
        super().setUp()
        self._orig_config_dir = cpt.CONFIG_DIR
        self.config_dir = os.path.join(self.tmpdir, "config")
        os.makedirs(self.config_dir)
        shutil.copy2(
            os.path.join(cpt.SCRIPT_DIR, "template.cpp"),
            os.path.join(self.config_dir, "template.cpp"),
        )
        cpt.CONFIG_DIR = self.config_dir

    def tearDown(self):
        cpt.CONFIG_DIR = self._orig_config_dir
        super().tearDown()


def run_cpt(*args):
    return subprocess.run(
        [sys.executable, CPT] + list(args),
        capture_output=True, text=True,
    )


def run_cpt_bg(*args):
    return subprocess.Popen(
        [sys.executable, CPT] + list(args),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
class TestLoadConfig(IsolatedConfigMixin, TempDirMixin, unittest.TestCase):
    def test_default_config(self):
        config = cpt.load_config()
        self.assertTrue(config["template"].endswith("template.cpp"))
        self.assertTrue(config["template"].startswith(self.config_dir))

    def test_custom_config_overrides(self):
        custom = os.path.join(self.tmpdir, "custom.cpp")
        open(custom, "w").close()
        with open(os.path.join(self.config_dir, "config.json"), "w") as f:
            json.dump({"template": custom}, f)
        self.assertEqual(cpt.load_config()["template"], custom)

    def test_tilde_expansion(self):
        with open(os.path.join(self.config_dir, "config.json"), "w") as f:
            json.dump({"template": "~/some/template.cpp"}, f)
        config = cpt.load_config()
        self.assertNotIn("~", config["template"])
        self.assertTrue(config["template"].startswith("/"))

    def test_auto_creates_config_dir(self):
        new_dir = os.path.join(self.tmpdir, "newconfig")
        cpt.CONFIG_DIR = new_dir
        cpt.load_config()
        self.assertTrue(os.path.isdir(new_dir))
        self.assertTrue(os.path.isfile(os.path.join(new_dir, "template.cpp")))


# ---------------------------------------------------------------------------
# create_problem
# ---------------------------------------------------------------------------
class TestCreateProblem(IsolatedConfigMixin, TempDirMixin, unittest.TestCase):
    def config(self):
        return cpt.load_config()

    def test_creates_directory_structure(self):
        self.assertTrue(cpt.create_problem("sol", self.config()))
        self.assertTrue(os.path.isdir("sol/samples"))
        self.assertTrue(os.path.isfile("sol/sol.cpp"))
        self.assertTrue(os.path.isfile("sol/Makefile"))

    def test_cpp_file_matches_template(self):
        config = self.config()
        cpt.create_problem("sol", config)
        with open("sol/sol.cpp") as f:
            got = f.read()
        with open(config["template"]) as f:
            want = f.read()
        self.assertEqual(got, want)

    def test_makefile_has_correct_prog_name(self):
        cpt.create_problem("myprog", self.config())
        with open("myprog/Makefile") as f:
            content = f.read()
        self.assertIn("PROG = myprog", content)
        self.assertNotIn("__PROG__", content)

    def test_makefile_has_debug_and_fast(self):
        cpt.create_problem("sol", self.config())
        with open("sol/Makefile") as f:
            content = f.read()
        self.assertIn("DEBUGFLAGS", content)
        self.assertIn("FASTFLAGS", content)
        self.assertIn("fast:", content)
        self.assertIn("_GLIBCXX_DEBUG", content)

    def test_samples_written(self):
        samples = [
            {"input": "1 2\n", "output": "3\n"},
            {"input": "5 10\n", "output": "15\n"},
        ]
        cpt.create_problem("sol", self.config(), samples=samples)
        with open("sol/samples/1.in") as f:
            self.assertEqual(f.read(), "1 2\n")
        with open("sol/samples/2.out") as f:
            self.assertEqual(f.read(), "15\n")

    def test_no_samples_means_empty_dir(self):
        cpt.create_problem("sol", self.config())
        self.assertEqual(os.listdir("sol/samples"), [])

    def test_existing_directory_returns_false(self):
        os.makedirs("sol")
        self.assertFalse(cpt.create_problem("sol", self.config()))

    def test_missing_template_creates_empty_cpp(self):
        cpt.create_problem("sol", {"template": "/nonexistent"})
        with open("sol/sol.cpp") as f:
            self.assertEqual(f.read(), "")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class TestCLI(TempDirMixin, unittest.TestCase):
    def test_no_download(self):
        r = run_cpt("abc", "--no-download")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(os.path.isfile("abc/abc.cpp"))
        self.assertTrue(os.path.isfile("abc/Makefile"))

    def test_no_download_duplicate_fails(self):
        run_cpt("abc", "--no-download")
        r = run_cpt("abc", "--no-download")
        self.assertIn("already exists", r.stderr)

    def test_no_download_multiple(self):
        r = run_cpt("A", "B", "C", "--no-download")
        self.assertEqual(r.returncode, 0)
        for name in "ABC":
            self.assertTrue(os.path.isfile(f"{name}/{name}.cpp"))

    def test_no_args_fails(self):
        self.assertNotEqual(run_cpt().returncode, 0)

    def test_help(self):
        r = run_cpt("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("names", r.stdout)

    def test_no_download_alone_fails(self):
        self.assertNotEqual(run_cpt("--no-download").returncode, 0)


# ---------------------------------------------------------------------------
# Competitive Companion listener
# ---------------------------------------------------------------------------
_next_port = 11100


def _alloc_port():
    global _next_port
    p = _next_port
    _next_port += 1
    return p


class TestListener(unittest.TestCase):
    def _post(self, data, port, delay=0.3):
        def send():
            time.sleep(delay)
            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.request("POST", "/", json.dumps(data),
                         {"Content-Type": "application/json"})
            conn.getresponse()
            conn.close()
        t = threading.Thread(target=send, daemon=True)
        t.start()
        return t

    def test_single_problem(self):
        port = _alloc_port()
        self._post({"name": "P", "tests": [{"input": "1\n", "output": "2\n"}]}, port)
        problems = cpt.listen_for_problems(count=1, port=port)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["name"], "P")

    def test_multiple_problems(self):
        port = _alloc_port()
        for i in range(3):
            self._post(
                {"name": f"P{i}", "tests": [{"input": f"{i}\n", "output": f"{i*2}\n"}]},
                port, delay=0.3 + i * 0.2,
            )
        problems = cpt.listen_for_problems(count=3, port=port)
        self.assertEqual(len(problems), 3)
        self.assertEqual(problems[2]["name"], "P2")

    def test_multiple_samples(self):
        port = _alloc_port()
        self._post({"name": "M", "tests": [
            {"input": "a\n", "output": "b\n"},
            {"input": "c\n", "output": "d\n"},
            {"input": "e\n", "output": "f\n"},
        ]}, port)
        problems = cpt.listen_for_problems(count=1, port=port)
        self.assertEqual(len(problems[0]["tests"]), 3)


# ---------------------------------------------------------------------------
# Download (end-to-end with simulated CC)
# ---------------------------------------------------------------------------
class TestDownload(TempDirMixin, unittest.TestCase):
    def test_single(self):
        proc = run_cpt_bg("aplusb")
        time.sleep(0.5)
        data = {"name": "A+B", "tests": [
            {"input": "1 2\n", "output": "3\n"},
            {"input": "10 20\n", "output": "30\n"},
        ]}
        conn = http.client.HTTPConnection("127.0.0.1", cpt.CC_PORT)
        conn.request("POST", "/", json.dumps(data),
                     {"Content-Type": "application/json"})
        conn.getresponse()
        conn.close()
        proc.wait(timeout=5)

        self.assertTrue(os.path.isfile("aplusb/aplusb.cpp"))
        with open("aplusb/samples/1.in") as f:
            self.assertEqual(f.read(), "1 2\n")
        with open("aplusb/samples/2.out") as f:
            self.assertEqual(f.read(), "30\n")

    def test_multiple(self):
        proc = run_cpt_bg("A", "B", "C")
        time.sleep(0.5)
        for i in range(3):
            conn = http.client.HTTPConnection("127.0.0.1", cpt.CC_PORT)
            conn.request("POST", "/", json.dumps({
                "name": f"Problem {chr(65+i)}",
                "tests": [{"input": f"{i}\n", "output": f"{i*10}\n"}],
            }), {"Content-Type": "application/json"})
            conn.getresponse()
            conn.close()
            time.sleep(0.2)
        proc.wait(timeout=5)

        for label in "ABC":
            self.assertTrue(os.path.isfile(f"{label}/{label}.cpp"))
            self.assertTrue(os.path.isfile(f"{label}/samples/1.in"))
        with open("C/samples/1.out") as f:
            self.assertEqual(f.read(), "20\n")


# ---------------------------------------------------------------------------
# Makefile template
# ---------------------------------------------------------------------------
class TestMakefile(unittest.TestCase):
    def _read(self):
        with open(cpt.MAKEFILE_TEMPLATE) as f:
            return f.read()

    def test_exists(self):
        self.assertTrue(os.path.isfile(cpt.MAKEFILE_TEMPLATE))

    def test_placeholder(self):
        self.assertIn("__PROG__", self._read())

    def test_targets(self):
        content = self._read()
        for target in ["all:", "fast:", "test:", "clean:", ".PHONY:"]:
            self.assertIn(target, content)

    def test_debug_flags(self):
        content = self._read()
        self.assertIn("_GLIBCXX_DEBUG", content)
        fast_line = [l for l in content.splitlines() if l.startswith("FASTFLAGS")][0]
        self.assertNotIn("_GLIBCXX_DEBUG", fast_line)

    def test_pch_support(self):
        content = self._read()
        self.assertIn("-I$(PCHDIR)", content)
        self.assertIn("g++ -x c++-header $(DEBUGFLAGS)", content)
        self.assertIn("g++ -x c++-header $(FASTFLAGS)", content)


class TestMakefilePCH(TempDirMixin, unittest.TestCase):
    def _setup_prob(self, output_val):
        pch_dir = os.path.join(self.tmpdir, "pch")
        prob_dir = os.path.join(self.tmpdir, "prob")
        os.makedirs(os.path.join(prob_dir, "samples"))
        with open(os.path.join(prob_dir, "prob.cpp"), "w") as f:
            f.write(f'#include <bits/stdc++.h>\n'
                    f'using namespace std;\n'
                    f'signed main() {{ cout << {output_val} << endl; }}\n')
        with open(cpt.MAKEFILE_TEMPLATE) as f:
            makefile = f.read().replace("__PROG__", "prob")
        makefile = makefile.replace(
            "PCHDIR = $(HOME)/.cache/cpt/pch", f"PCHDIR = {pch_dir}")
        with open(os.path.join(prob_dir, "Makefile"), "w") as f:
            f.write(makefile)
        return prob_dir, pch_dir

    def test_debug_pch_auto_builds(self):
        prob_dir, pch_dir = self._setup_prob(42)
        result = subprocess.run(["make"], cwd=prob_dir,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isfile(
            os.path.join(pch_dir, "bits", "stdc++.h.gch", "debug.gch")))
        run = subprocess.run([os.path.join(prob_dir, "prob")],
                             capture_output=True, text=True)
        self.assertEqual(run.stdout.strip(), "42")

    def test_fast_pch_auto_builds(self):
        prob_dir, pch_dir = self._setup_prob(99)
        result = subprocess.run(["make", "fast"], cwd=prob_dir,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isfile(
            os.path.join(pch_dir, "bits", "stdc++.h.gch", "fast.gch")))
        self.assertFalse(os.path.isfile(
            os.path.join(pch_dir, "bits", "stdc++.h.gch", "debug.gch")))


if __name__ == "__main__":
    unittest.main()
