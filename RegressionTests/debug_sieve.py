#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Perl Sieve generator - DEBUG VERSION with FULL OUTPUT
Shows exactly what Perl produces
"""

import json
import subprocess
import sys
import re
import os
from pathlib import Path
from typing import Tuple, List, Dict, Any
import tempfile

PERL_TEMPLATE_PATH = "/home/brianr/GITFiles/smecontribs/smeserver-mailsorting/root/etc/e-smith/templates-user/.before.sieve/85sieve-user"

def verify_perl_template() -> str:
    path = Path(PERL_TEMPLATE_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Perl template not found: {PERL_TEMPLATE_PATH}")
    print(f"✓ Using Perl template: {PERL_TEMPLATE_PATH}")
    return path.read_text(encoding='utf-8')

def mock_esmith_db(username: str, case: Dict[str, str], db_dir: Path) -> Path:
    db_path = db_dir / "processmail"
    props = {
        'testrule': {
            'type': username,
            'basis': case['basis'],
            'criterion': case['criterion'],
            'basis2': case.get('basis2', ''),
            'criterion2': case.get('criterion2', ''),
            'copy': case.get('copy', 'no'),
            'action': case['action'],
            'action2': case.get('action2', ''),
            'deliver': case.get('deliver', ''),
            'deliver2': case.get('deliver2', '')
        }
    }
    
    db_path.parent.mkdir(exist_ok=True)
    with db_path.open('w', encoding='utf-8') as f:
        for rule, rule_props in props.items():
            for prop, value in rule_props.items():
                f.write(f"processmail|{rule}|{prop}|{value}\n")
    return db_path

def run_perl_test_case(case: Dict[str, str], username: str = "testuser") -> Tuple[str, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_dir = Path(tmpdir)
        mock_db_path = mock_esmith_db(username, case, db_dir)
        perl_code = verify_perl_template()
        
        # SIMPLIFIED WORKING MOCK - no complex package issues
        esmith_mock = '''package esmith::config;
sub TIEHASH { bless {}, shift; }
sub FETCH { "/home/e-smith/db/processmail" }

package esmith::db;
sub new { bless {{ path => shift() || "/dev/null" }}, shift; }
sub get_prop {
    my ($self, $keyref, $key, $prop, $def) = @_;
    $def = "" unless defined $def;
    return $def unless ref($keyref) eq "HASH";
    
    my $path = $self->{{path}};
    return $def unless -f $path;
    
    open my $fh, "<", $path or return $def;
    while (<$fh>) {
        chomp;
        if (/^processmail\\|$key\\|$prop\\|(.*)$/) {
            close $fh;
            return $1;
        }
    }
    close $fh;
    return $def;
}
sub get_type {
    my ($self, $keyref, $key) = @_;
    return "" unless ref($keyref) eq "HASH";
    my $path = $self->{{path}};
    return "" unless -f $path;
    open my $fh, "<", $path or return "";
    while (<$fh>) {
        chomp;
        if (/^processmail\\|$key\\|type\\|(.*)$/) {
            close $fh;
            return $1;
        }
    }
    close $fh;
    return "";
}'''

        # CRITICAL: Match your template's EXACT structure
        test_wrapper = f'''use strict; use warnings;
{esmith_mock}

# Template globals - EXACTLY as your template expects
$USERNAME = "{username}";
$OUT = "";

my %processmail;
tie %processmail, "esmith::config";

# RUN THE ACTUAL TEMPLATE
{perl_code}

# DEBUG: Always print something
print "DEBUG: OUT=|" . (defined $OUT ? $OUT : "UNDEFINED") . "|\n";
print "DEBUG: length=" . (defined $OUT ? length($OUT) : 0) . "\n";
print $OUT if defined $OUT && length($OUT);'''

        env = {**os.environ, 'HOME': str(db_dir)}
        
        try:
            result = subprocess.run(['perl'], input=test_wrapper, text=True,
                                  capture_output=True, cwd=str(db_dir), env=env, timeout=30)
            
            if result.returncode != 0:
                return "", f"ERROR {result.returncode}: {result.stderr}"
            
            return result.stdout, ""
        except subprocess.TimeoutExpired:
            return "", "Timeout"

def load_test_cases() -> List[Dict[str, Any]]:
    json_path = Path("output/regression_test_cases.json")
    if not json_path.exists():
        print("❌ Missing JSON!")
        sys.exit(1)
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)

def debug_single_test():
    """DEBUG: Run just FIRST test case with FULL output"""
    cases = load_test_cases()
    case = cases[0]  # T01 - basic subject test
    print(f"\n🔍 DEBUGGING CASE: {case['id']} {case['expect']}")
    print(f"  basis={case['basis']!r}")
    print(f"  criterion={case['criterion']!r}")
    
    output, error = run_perl_test_case(case)
    print("\n📤 FULL PERL OUTPUT:")
    print(repr(output))
    print("\n📤 RAW BYTES:")
    print(repr(output.encode('utf-8', errors='replace')))
    return output

def reset_and_test():
    """Reset JSON and test ONE case"""
    cases = load_test_cases()
    for case in cases:
        case.pop('expected_sieve', None)
    
    # Test just first case
    output, error = run_perl_test_case(cases[0])
    print("\n🎯 FIRST TEST RESULT:")
    print(f"OUTPUT: {repr(output)}")
    print(f"ERROR:  {repr(error)}")
    print(f"LENGTH: {len(output) if output else 0}")
    
    if output.strip():
        cases[0]['expected_sieve'] = output.strip()
        with open("output/regression_test_cases.json", "w", encoding="utf-8") as f:
            json.dump(cases, f, ensure_ascii=False, indent=2)
        print("✅ SAVED FIRST BASELINE")
    return output

if __name__ == "__main__":
    print("🐛 DEBUG MODE - Analyzing why NO OUTPUT")
    debug_single_test()
    print("\n🔄 Now resetting JSON and testing first case...")
    reset_and_test()
    print("\n✅ Check above for what Perl actually produces!")
