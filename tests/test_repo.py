"""Repository checks: the nine skills, the manifests, the README, the safety
block on every skill on the way to an order, and no leftovers from the US pack."""

import json
import os
import re
import unittest

from _load import ROOT

SKILLS = ["trader-scanner", "trader-news", "trader-entry", "trader-exit", "trader-timemachine",
          "trader-risk", "trader-budget", "trader-broker", "trader-alerts"]
REMOVED = ["trader-pelosi", "trader-analyst", "trader-copycat", "trader-screener", "trader-tax",
           "trader-rebalance"]
# skills on the way to an order carry the safety block
ORDER_PATH = ["trader-scanner", "trader-entry", "trader-exit", "trader-timemachine", "trader-budget",
              "trader-risk", "trader-broker", "trader-alerts"]
FORK = "https://github.com/AmitDGit/day-trader-skill-bsense"


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), text


def every_text_file():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            if f.endswith((".md", ".py", ".json", ".csv", ".txt", ".xml")) or f == "LICENSE":
                yield os.path.join(base, f)


def skill_texts():
    for s in SKILLS:
        folder = os.path.join(ROOT, s)
        for f in os.listdir(folder):
            if f.endswith((".md", ".py", ".json")):
                with open(os.path.join(folder, f), encoding="utf-8") as fh:
                    yield "%s/%s" % (s, f), fh.read()


class Repo(unittest.TestCase):
    def test_nine_skill_folders_at_the_root(self):
        found = sorted(d for d in os.listdir(ROOT)
                       if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))
        self.assertEqual(found, sorted(SKILLS))
        for gone in REMOVED:
            self.assertFalse(os.path.exists(os.path.join(ROOT, gone)), gone)

    def test_frontmatter_name_and_description(self):
        for s in SKILLS:
            fm, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            self.assertIn("name: %s\n" % s, fm + "\n", s)
            self.assertRegex(fm, r"description: ", s)
            self.assertGreater(len(fm), 200, "%s description is too thin" % s)
            desc = " ".join(l.strip() for l in fm.split("description: >-", 1)[-1].split("\nargument-hint")[0].splitlines())
            self.assertLessEqual(len(desc.strip()), 1024, "%s description is over the 1024 limit" % s)
            self.assertGreater(len(text.splitlines()), 60, s)

    def test_order_path_skills_carry_the_safety_block(self):
        for s in ORDER_PATH:
            _, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            low = " ".join(text.lower().split())
            for words in ("not financial advice", "yes", "dry run by default", "always allow"):
                self.assertIn(words, low, "%s: %s" % (s, words))

    def test_skills_speak_nse_not_us(self):
        for rel, text in skill_texts():
            for old in ("New York", "NYSE", "Nasdaq", "Alpaca", "TSLA", "EDGAR", "Pelosi", "$5,000"):
                self.assertNotIn(old, text, "%s still says %s" % (rel, old))
        for s in SKILLS:
            _, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            self.assertTrue("IST" in text or "NSE" in text, s)

    def test_plugin_manifests_point_at_the_fork(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json")) as fh:
            plugin = json.load(fh)
        self.assertEqual(plugin["skills"], "./")
        self.assertEqual(plugin["license"], "MIT")
        self.assertEqual((plugin["homepage"], plugin["repository"]), (FORK, FORK))
        self.assertIn("9 Claude skills", plugin["description"])
        self.assertIn("Kite", plugin["description"])
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as fh:
            market = json.load(fh)
        self.assertEqual(market["plugins"][0]["name"], plugin["name"])
        self.assertEqual(market["plugins"][0]["homepage"], FORK)

    def test_readme(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = " ".join(fh.read().split())
        self.assertTrue(readme.startswith("# The Day Trader skill"))
        for line in (FORK, "/plugin marketplace add AmitDGit/day-trader-skill-bsense",
                     "Jakeschincariol/day-trader-skill", "## Fine print", "dry run", "Needs approval"):
            self.assertIn(line, readme)
        for s in SKILLS:
            self.assertIn("/" + s, readme, s)

    def test_license_keeps_the_original_author(self):
        with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as fh:
            self.assertIn("Jake Schincariol", fh.read())

    def test_no_em_dashes_and_no_personal_email(self):
        for path in every_text_file():
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            rel = os.path.relpath(path, ROOT)
            if not rel.startswith(os.path.join("tests", "fixtures")):
                self.assertNotIn("\u2014", text, rel)
            self.assertNotRegex(text, r"[\w.]+@(gmail|rediffmail|yahoo)\.com", rel)

    def test_every_tool_runs_on_python_3_8(self):
        for s in SKILLS:
            folder = os.path.join(ROOT, s)
            for f in os.listdir(folder):
                if not f.endswith(".py"):
                    continue
                with open(os.path.join(folder, f), encoding="utf-8") as fh:
                    src = fh.read()
                for bad in ("import zoneinfo", "from zoneinfo", ".removeprefix(", ".removesuffix("):
                    self.assertNotIn(bad, src, "%s/%s" % (s, f))
                self.assertNotRegex(src, r"(?m)^\s+match \w+.*:$", "%s/%s" % (s, f))
                for bad in ("list[", "dict[", "tuple["):
                    self.assertNotRegex(src, r"(?<![\w.])%s" % re.escape(bad), "%s/%s" % (s, f))

    def test_day_trading_limits_ship_in_the_example_config(self):
        with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        for k in ("max_loss_per_trade_inr", "max_daily_loss_inr", "max_trades_per_day",
                  "min_reward_risk", "require_stop", "no_entries_after", "flat_by", "costs"):
            self.assertIn(k, cfg, k)
        self.assertIs(cfg["require_stop"], True)
        self.assertLess(cfg["flat_by"], "15:20")  # before Zerodha's MIS square-off
        for k in ("allow_short", "allow_margin", "allow_options"):
            self.assertIs(cfg.get(k, False), False, k)

    def test_dry_run_is_the_default(self):
        with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        self.assertIs(cfg["dry_run"], True)
        self.assertNotIn("paper", cfg)


if __name__ == "__main__":
    unittest.main()
