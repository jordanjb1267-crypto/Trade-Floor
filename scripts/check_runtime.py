#!/usr/bin/env python3
"""Validate the interpreter the supervisor will actually run under.

Two checks, both of which have already failed in this repository's history and
neither of which the existing verifiers could catch:

1. **Python >= 3.11 (§23).** launchd runs with PATH=/usr/bin:/bin:/usr/sbin:
   /sbin, so a plist that resolves `python3` gets the macOS system interpreter
   (3.9.x), not the project's. The supervisor then dies on import syntax and
   the installer reports success.

2. **TLS to the OANDA practice host.** A python.org framework build ships no
   root certificates: `ssl.get_default_verify_paths()` returns None, every
   HTTPS call fails with CERTIFICATE_VERIFY_FAILED, and the error names a
   certificate problem while looking exactly like a bad credential to anyone
   reading a preflight summary. This performs a bare TLS handshake — SNI and
   nothing else. **No credential is read, loaded, or transmitted.**

This file is deliberately written in conservative syntax with no project
imports before the version gate, so that running it under Python 3.9 produces
the explanatory failure rather than a SyntaxError.

On failure it PRINTS the certificate remediation and exits nonzero. It does not
perform it: modifying a system trust store is an owner decision made knowingly,
not a side effect of running an installer (see deploy/macos/README.md).
"""

import socket
import ssl
import sys

MIN_PYTHON = (3, 11)

# Mirrors trading_firm.execution.oanda_transport.PRACTICE_HOST. Duplicated
# rather than imported so this script still runs when the package import is
# what is broken; tests/unit/test_check_runtime.py asserts the two never drift.
PRACTICE_TLS_HOST = "api-fxpractice.oanda.com"
TLS_PORT = 443
TLS_TIMEOUT_SECONDS = 20.0

CERT_REMEDIATION = """\
  The interpreter has no usable root certificate bundle. This is a local trust
  store problem, NOT a credential problem: the handshake never completed, so no
  token was transmitted or evaluated.

  Repair it manually (python.org framework builds ship no roots and expect
  certifi to supply them):

      /usr/local/bin/python3 -m pip install --upgrade certifi
      mkdir -p /Library/Frameworks/Python.framework/Versions/3.11/etc/openssl
      ln -sf "$(/usr/local/bin/python3 -c 'import certifi;print(certifi.where())')" \\
             /Library/Frameworks/Python.framework/Versions/3.11/etc/openssl/cert.pem

  Then recreate the virtualenv so it inherits the repaired trust store, or
  confirm with:  .venv/bin/python scripts/check_runtime.py

  The installer will not do this for you. Changing a system trust store affects
  every program using that interpreter, so it stays an explicit owner action."""


def check_python():
    actual = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info < MIN_PYTHON:
        wanted = ".".join(str(part) for part in MIN_PYTHON)
        return (
            False,
            f"Python >= {wanted} (found {actual} at {sys.executable})",
            f"  §23 requires >= {wanted}. Under launchd, `/usr/bin/env python3` "
            f"resolves\n  to the system interpreter; the plist must name an "
            f"absolute venv path.",
        )
    return (True, f"Python {actual} at {sys.executable}", "")


def check_tls():
    context = ssl.create_default_context()
    try:
        with socket.create_connection(
            (PRACTICE_TLS_HOST, TLS_PORT), timeout=TLS_TIMEOUT_SECONDS
        ) as raw:
            with context.wrap_socket(raw, server_hostname=PRACTICE_TLS_HOST) as tls:
                tls.getpeercert()
                version = tls.version()
    except ssl.SSLCertVerificationError as error:
        reason = error.verify_message or "certificate verify failed"
        return (False, f"TLS to {PRACTICE_TLS_HOST}: {reason}", CERT_REMEDIATION)
    except ssl.SSLError as error:
        return (False, f"TLS to {PRACTICE_TLS_HOST}: {error}", CERT_REMEDIATION)
    except (OSError, TimeoutError) as error:
        return (
            False,
            f"TLS to {PRACTICE_TLS_HOST}: {error}",
            "  The host was not reachable. This is a NETWORK result, not a credential\n"
            "  one — check egress policy, proxy rules, and DNS before touching any token.",
        )
    return (True, f"TLS to {PRACTICE_TLS_HOST} negotiated ({version})", "")


def main():
    results = [("python", check_python()), ("tls", check_tls())]
    failed = 0
    for name, (ok, summary, remedy) in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<6} {summary}")
        if not ok:
            failed += 1
            if remedy:
                print(remedy)
    print("")
    if failed:
        print(f"{failed} of {len(results)} runtime check(s) FAILED. Nothing was changed.")
        return 1
    print(f"{len(results)}/{len(results)} runtime checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
