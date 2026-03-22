#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import subprocess
import sys
import os
from pathlib import Path
import re
from typing import Tuple, List, Dict, Any

PERL_TEMPLATE_PATH = "/home/brianr/GITFiles/smecontribs/smeserver-mailsorting/root/etc/e-smith/templates-user/.before.sieve/85sieve-user"
JSON_PATH = "output/regression_test_cases.json"
REPORT_PATH = "output/regression_report.json"


def verify_perl_template() -> str:
    path = Path(PERL_TEMPLATE_PATH)
    if not path.exists():
        raise FileNotFoundError("Perl template not found: {0}".format(PERL_TEMPLATE_PATH))
    return path.read_text(encoding="utf-8")


def mock_esmith_db_content(username: str, case: Dict[str, str]) -> str:
    props = {
        "testrule": {
            "type": username,
            "basis": case["basis"],
            "criterion": case["criterion"],
            "basis2": case.get("basis2", ""),
            "criterion2": case.get("criterion2", ""),
            "copy": case.get("copy", "no"),
            "action": case["action"],
            "action2": case.get("action2", ""),
            "deliver": case.get("deliver", ""),
            "deliver2": case.get("deliver2", ""),
        }
    }

    lines = []
    for rule, rule_props in props.items():
        for prop, value in rule_props.items():
            escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append('processmail|{0}|{1}|"'.format(rule, prop) + escaped_value + '"')
    return "\n".join(lines)


def run_perl_test_case(case: Dict[str, str], username: str = "testuser") -> Tuple[str, str]:
    """
    Returns: (actual_output, error_string)
    If error occurs, actual_output is "" and error_string contains details.
    """
    perl_template = verify_perl_template()

    perl_template = re.sub(
        r"^\s*use\s+esmith::[^\n]*\n?",
        "",
        perl_template,
        flags=re.MULTILINE,
    )

    db_content = mock_esmith_db_content(username, case)

    mock_code = (
        "# COMPLETE ESMITH MOCK - NO EXTERNAL MODULES\n"
        "package esmith::config;\n"
        "sub TIEHASH {\n"
        "    my ($class, $path) = @_;\n"
        "    return bless { path => $path, keys => ['testrule'], idx => 0 }, $class;\n"
        "}\n"
        "sub FETCH { return undef; }\n"
        "sub FIRSTKEY {\n"
        "    my ($self) = @_;\n"
        "    $self->{idx} = 0;\n"
        "    return undef unless $self->{keys} && @{$self->{keys}};\n"
        "    return $self->{keys}[0];\n"
        "}\n"
        "sub NEXTKEY {\n"
        "    my ($self) = @_;\n"
        "    $self->{idx}++;\n"
        "    return undef if !$self->{keys} || $self->{idx} >= @{$self->{keys}};\n"
        "    return $self->{keys}[$self->{idx}];\n"
        "}\n"
        "\n"
        "package esmith::db;\n"
        "sub new {\n"
        "    my $class = shift;\n"
        "    my @lines = split /\\n/, <<'DBLINES';\n"
        + db_content + "\n"
        "DBLINES\n"
        "    return bless { lines => \\@lines, path => \"/mock\" }, $class;\n"
        "}\n"
        "sub get_prop {\n"
        "    my ($self, $keyref, $key, $prop, $def) = @_;\n"
        "    $def = \"\" unless defined $def;\n"
        "    foreach my $line (@{$self->{lines}}) {\n"
        "        chomp($line);\n"
        "        next unless $line =~ /^processmail\\|/;\n"
        "        my @parts = split /\\|/, $line, 4;\n"
        "        next unless @parts == 4;\n"
        "        my ($table, $rulekey, $propname, $value) = @parts;\n"
        "        next unless $rulekey eq $key;\n"
        "        next unless $propname eq $prop;\n"
        "        $value =~ s/^\\\"//;\n"
        "        $value =~ s/\\\"$//;\n"
        "        return $value;\n"
        "    }\n"
        "    return $def;\n"
        "}\n"
        "sub get_type {\n"
        "    my ($self, $keyref, $key) = @_;\n"
        "    return $self->get_prop($keyref, $key, 'type', '');\n"
        "}\n"
        "\n"
        "$INC{\"esmith/config.pm\"} = 1;\n"
        "$INC{\"esmith/db.pm\"} = 1;\n"
        "\n"
        "package main;\n"
        + 'our $USERNAME = "' + username + '";\n'
        "our $OUT = \"\";\n"
        "my $DB = esmith::db->new();\n"
        "sub db_get_prop {\n"
        "    my ($href, $key, $prop, $def) = @_;\n"
        "    return $DB->get_prop($href, $key, $prop, $def);\n"
        "}\n"
        "sub db_get_type {\n"
        "    my ($href, $key) = @_;\n"
        "    return $DB->get_type($href, $key);\n"
        "}\n"
        "tie %processmail, \"esmith::config\";\n"
    )

    test_wrapper = (
        mock_code
        + "\n"
        + "eval {\n"
        + perl_template
        + "\n};\n"
        + "if ($@) { print STDERR \"PERL_EVAL_ERROR:$@\\n\"; exit 1; }\n"
        + 'print $OUT if defined $OUT && length($OUT);'
    )

    env = os.environ.copy()

    try:
        result = subprocess.run(
            ["perl"],
            input=test_wrapper,
            text=True,
            capture_output=True,
            timeout=30,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return "", "Timeout", 124
    
    out = result.stdout or ""
    err = (result.stderr or "").strip()

    # If perl crashed, preserve stderr
    if result.returncode != 0:
        return "", err or ("Perl failed with returncode {0}".format(result.returncode)), result.returncode

    # Perl exited cleanly; return whatever it produced (may be empty)
    return out, err, result.returncode



def normalize_output(s: str) -> str:
    """
    Normalize for comparison.
    If you want exact matching only, return s directly.
    """
    # Common normalization: strip trailing whitespace only.
    return s.strip()


def diff_summary(expected: str, actual: str, max_chars: int = 4000) -> str:
    expected_n = normalize_output(expected)
    actual_n = normalize_output(actual)

    if expected_n == actual_n:
        return ""

    # Small human diff summary: show first differing region
    a = actual_n
    e = expected_n
    n = min(len(a), len(e))
    i = 0
    while i < n and a[i] == e[i]:
        i += 1

    start = max(0, i - 80)
    end_a = min(len(a), i + 80)
    end_e = min(len(e), i + 80)

    snippet_a = a[start:end_a]
    snippet_e = e[start:end_e]

    return (
        "First difference at index {0}\n"
        "---- expected snippet ----\n"
        "{1}\n"
        "---- actual snippet ----\n"
        "{2}\n"
    ).format(i, snippet_e, snippet_a)


def load_cases() -> List[Dict[str, Any]]:
    json_path = Path(JSON_PATH)
    if not json_path.exists():
        raise FileNotFoundError("Missing JSON: {0}".format(JSON_PATH))
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    cases = load_cases()

    total = len(cases)
    passed = 0
    failed = 0

    report = {
        "total": total,
        "passed": 0,
        "failed": 0,
        "items": [],
    }

    for case in cases:
        case_id = case.get("id", "")
        expected = case.get("expected_sieve", "")
        actual, err, rc = run_perl_test_case(case)
        
        expected_norm = normalize_output(expected)
        actual_norm = normalize_output(actual)
        
        ok = (expected_norm == actual_norm) and (rc == 0) and (err == "")
        # (You can decide whether stderr should force failure; usually for this use-case, yes.)
        
        item_report = {
            "id": case_id,
            "ok": ok,
            "expected_len": len(expected_norm),
            "actual_len": len(actual_norm),
            "expected_text": expected_norm,
            "actual_text": actual_norm,
            "returncode": rc,
        }
        
        if err:
            item_report["stderr"] = err
        elif actual_norm == "" and expected_norm != "":
            item_report["stderr"] = "(no stderr; Perl produced empty output)"

        if not ok:
            item_report["diff"] = diff_summary(expected, actual)

        report["items"].append(item_report)

        print("{0} {1}".format("✅" if ok else "❌", case_id))

    report["passed"] = passed
    report["failed"] = failed

    Path("output").mkdir(exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\nSummary: passed={0}, failed={1}, total={2}".format(passed, failed, total))
    print("Report written to: {0}".format(REPORT_PATH))


if __name__ == "__main__":
    main()
