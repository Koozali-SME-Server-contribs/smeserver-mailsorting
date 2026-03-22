#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Perl Sieve generator regression tests (standalone)
- Uses a mocked e-smith config/db implementation
- No external dependencies
"""

import json
import subprocess
import sys
import os
from pathlib import Path
from typing import Tuple, List, Dict, Any
import re

PERL_TEMPLATE_PATH = "/home/brianr/GITFiles/smecontribs/smeserver-mailsorting/root/etc/e-smith/templates-user/.before.sieve/85sieve-user"


def verify_perl_template() -> str:
    path = Path(PERL_TEMPLATE_PATH)
    if not path.exists():
        raise FileNotFoundError("Perl template not found: {0}".format(PERL_TEMPLATE_PATH))
    print("✓ Using Perl template: {0}".format(PERL_TEMPLATE_PATH))
    return path.read_text(encoding="utf-8")


def mock_esmith_db_content(username: str, case: Dict[str, str]) -> str:
    """Generate esmith DB content as string (processmail|testrule|prop|\"value\")"""
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
    perl_template = verify_perl_template()

    # Remove original use statements (allow leading whitespace)
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
        "        my @parts = split /\\|/, $line, 4;  # processmail, rulekey, prop, value\n"
        "        next unless @parts == 4;\n"
        "        my ($table, $rulekey, $propname, $value) = @parts;\n"
        "        next unless $rulekey eq $key;\n"
        "        next unless $propname eq $prop;\n"
        "        $value =~ s/^\"//;\n"
        "        $value =~ s/\"$//;\n"
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
        "my %processmail;\n"
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
        out = result.stdout or ""
        err = (result.stderr or "").strip()

        if result.returncode != 0:
            return "", err or ("Perl failed with returncode {0}".format(result.returncode))

        return out, err
    except subprocess.TimeoutExpired:
        return "", "Timeout"


def load_test_cases() -> List[Dict[str, Any]]:
    json_path = Path("output/regression_test_cases.json")
    if not json_path.exists():
        print("❌ Missing JSON - create output/regression_test_cases.json first!")
        sys.exit(1)
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    cases = load_test_cases()

    # Reset all baselines
    for case in cases:
        case.pop("expected_sieve", None)

    print("🟢 CAPTURING FRESH BASELINE (first 5 tests)...")
    Path("output").mkdir(exist_ok=True)

    success_count = 0
    for case in cases:
        print("  {0:<3} {1:<35}".format(case["id"], case["expect"]), end="")
        output, error = run_perl_test_case(case)

        if output.strip():
            case["expected_sieve"] = output.strip()
            print("✅ {0} chars".format(len(output.strip())))
            print("    {0}...".format(repr(output.strip()[:80])))
            success_count += 1
        else:
            print("❌ perl returned no output")
            case["expected_sieve"] = "# ERROR: " + (error if error else "NO_STDERR")

    # Save updated JSON
    with open("output/regression_test_cases.json", "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

    print("\n✅ BASELINE CAPTURE COMPLETE: {0}/{1} tests produced output".format(success_count, len(cases)))
    if success_count > 0:
        print("\n🔄 Run AGAIN for full regression testing!")
    else:
        print("\n❌ NO TESTS WORKED - check template path and JSON format")


if __name__ == "__main__":
    main()
