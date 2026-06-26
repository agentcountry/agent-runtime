"""
Watchdog — scheduled health checks and alerting.

Phase 2: Monitors OSS expiry, SSL certificates, account balances,
and other infrastructure health indicators. Runs on cron or manual trigger.
"""

import asyncio
import json
import logging
import os
import ssl
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from . import Runtime

logger = logging.getLogger("agent-runtime.watchdog")


class CheckStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    CRITICAL = "critical"
    ERROR = "error"


@dataclass
class CheckResult:
    """Result of a single health check."""
    name: str
    status: CheckStatus
    message: str
    detail: dict = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = _now_iso()


class Watchdog:
    """Runs health checks and triggers alerts."""

    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime
        self._checks: dict[str, dict] = {}  # name → {interval, last_run, config}
        self._results: list[CheckResult] = []
        self._running = False

    # ── Check Registration ──────────────────────────────

    def add_check(
        self,
        name: str,
        interval_hours: int = 24,
        config: dict = None,
    ):
        """Register a health check."""
        self._checks[name] = {
            "interval_hours": interval_hours,
            "last_run": "",
            "config": config or {},
        }
        logger.info(f"Watchdog check registered: {name} (every {interval_hours}h)")

    def remove_check(self, name: str):
        if name in self._checks:
            del self._checks[name]

    # ── Built-in Checks ─────────────────────────────────

    async def check_ssl(self, domain: str, port: int = 443) -> CheckResult:
        """Check SSL certificate expiry for a domain."""
        try:
            context = ssl.create_default_context()
            with socket.create_connection((domain, port), timeout=10) as sock:
                with context.wrap_socket(sock, server_hostname=domain) as ssock:
                    cert = ssock.getpeercert()
                    not_after = cert.get("notAfter", "")
                    if not_after:
                        # Parse ASN.1 GENERALIZEDTIME or UTCTIME
                        from datetime import datetime as dt
                        try:
                            expire_date = dt.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                        except ValueError:
                            expire_date = dt.strptime(not_after[:14], "%Y%m%d%H%M%S")

                        days_left = (expire_date - dt.now(timezone.utc)).days

                        if days_left <= 7:
                            status = CheckStatus.CRITICAL
                        elif days_left <= 30:
                            status = CheckStatus.WARN
                        else:
                            status = CheckStatus.OK

                        return CheckResult(
                            name=f"ssl:{domain}",
                            status=status,
                            message=f"SSL for {domain}: {days_left} days until expiry",
                            detail={
                                "domain": domain,
                                "days_left": days_left,
                                "expires": expire_date.isoformat(),
                                "issuer": dict(cert.get("issuer", [])),
                            },
                        )
        except Exception as e:
            return CheckResult(
                name=f"ssl:{domain}",
                status=CheckStatus.ERROR,
                message=f"Failed to check SSL for {domain}: {e}",
            )

        return CheckResult(
            name=f"ssl:{domain}",
            status=CheckStatus.ERROR,
            message=f"Could not parse certificate for {domain}",
        )

    async def check_http(self, url: str, expected_status: int = 200) -> CheckResult:
        """Check if an HTTP endpoint is reachable."""
        import urllib.request
        try:
            req = urllib.request.Request(url, method="HEAD")
            response = urllib.request.urlopen(req, timeout=10)
            is_ok = response.status == expected_status
            return CheckResult(
                name=f"http:{url}",
                status=CheckStatus.OK if is_ok else CheckStatus.CRITICAL,
                message=f"HTTP {response.status} for {url}",
                detail={"url": url, "status": response.status, "expected": expected_status},
            )
        except Exception as e:
            return CheckResult(
                name=f"http:{url}",
                status=CheckStatus.ERROR,
                message=f"HTTP check failed for {url}: {e}",
            )

    async def check_disk(self, path: str = "/", warn_pct: float = 80.0, critical_pct: float = 95.0) -> CheckResult:
        """Check disk usage."""
        try:
            stat = os.statvfs(path)
            total = stat.f_frsize * stat.f_blocks
            free = stat.f_frsize * stat.f_bavail
            used_pct = ((total - free) / total) * 100

            if used_pct >= critical_pct:
                status = CheckStatus.CRITICAL
            elif used_pct >= warn_pct:
                status = CheckStatus.WARN
            else:
                status = CheckStatus.OK

            return CheckResult(
                name=f"disk:{path}",
                status=status,
                message=f"Disk {path}: {used_pct:.1f}% used ({_format_bytes(free)} free)",
                detail={
                    "path": path,
                    "used_pct": round(used_pct, 1),
                    "total": _format_bytes(total),
                    "free": _format_bytes(free),
                },
            )
        except Exception as e:
            return CheckResult(
                name=f"disk:{path}",
                status=CheckStatus.ERROR,
                message=f"Disk check failed for {path}: {e}",
            )

    async def check_cert_expiry(self, cert_paths: list[str]) -> list[CheckResult]:
        """Check local certificate file expiry dates."""
        results = []
        from datetime import datetime as dt
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend

        for path in cert_paths:
            try:
                with open(path, "rb") as f:
                    cert = x509.load_pem_x509_certificate(f.read(), default_backend())
                days_left = (cert.not_valid_after_utc - dt.now(timezone.utc)).days

                if days_left <= 7:
                    status = CheckStatus.CRITICAL
                elif days_left <= 30:
                    status = CheckStatus.WARN
                else:
                    status = CheckStatus.OK

                results.append(CheckResult(
                    name=f"cert:{os.path.basename(path)}",
                    status=status,
                    message=f"Cert {os.path.basename(path)}: {days_left} days left",
                    detail={"path": path, "days_left": days_left},
                ))
            except Exception as e:
                results.append(CheckResult(
                    name=f"cert:{os.path.basename(path)}",
                    status=CheckStatus.ERROR,
                    message=f"Failed to read cert {path}: {e}",
                ))
        return results

    # ── Orchestration ───────────────────────────────────

    async def run_all(self) -> list[CheckResult]:
        """Run all registered checks."""
        results: list[CheckResult] = []

        # Built-in checks (configured via add_check config)
        for name, check in self._checks.items():
            try:
                result = await self._execute_check(name, check["config"])
                results.append(result)
                check["last_run"] = _now_iso()

                if result.status in (CheckStatus.WARN, CheckStatus.CRITICAL):
                    await self._alert(result)
            except Exception as e:
                logger.error(f"Check '{name}' failed: {e}")
                results.append(CheckResult(
                    name=name,
                    status=CheckStatus.ERROR,
                    message=f"Check execution error: {e}",
                ))

        self._results.extend(results)
        # Keep last 200 results
        if len(self._results) > 200:
            self._results = self._results[-200:]

        return results

    async def _execute_check(self, name: str, config: dict) -> CheckResult:
        """Dispatch to the right check function based on name prefix."""
        if name.startswith("ssl:"):
            domain = config.get("domain", name.split("ssl:", 1)[1])
            return await self.check_ssl(domain, config.get("port", 443))
        elif name.startswith("http:"):
            url = config.get("url", name.split("http:", 1)[1])
            return await self.check_http(url, config.get("expected_status", 200))
        elif name.startswith("disk:"):
            path = config.get("path", name.split("disk:", 1)[1])
            return await self.check_disk(path, config.get("warn_pct", 80), config.get("critical_pct", 95))
        elif name == "cert_files":
            paths = config.get("paths", [])
            results = await self.check_cert_expiry(paths)
            # Return aggregate
            critical = [r for r in results if r.status == CheckStatus.CRITICAL]
            warn = [r for r in results if r.status == CheckStatus.WARN]
            ok = [r for r in results if r.status == CheckStatus.OK]
            return CheckResult(
                name=name,
                status=CheckStatus.CRITICAL if critical else (CheckStatus.WARN if warn else CheckStatus.OK),
                message=f"Cert check: {len(ok)} OK, {len(warn)} warn, {len(critical)} critical",
                detail={"results": [r.detail for r in results]},
            )
        else:
            return CheckResult(
                name=name,
                status=CheckStatus.ERROR,
                message=f"Unknown check type: {name}",
            )

    async def _alert(self, result: CheckResult):
        """Send alert for a warning/critical check."""
        severity = "warn" if result.status == CheckStatus.WARN else "error"
        await self.runtime.notifier.notify(
            f"🔔 {result.name}: {result.message}",
            severity=severity,
        )
        self.runtime.storage.audit("watchdog_alert", {
            "check": result.name,
            "status": result.status.value,
            "message": result.message,
        })

    # ── Status ──────────────────────────────────────────

    @property
    def last_results(self) -> list[CheckResult]:
        return self._results[-20:]

    def summary(self) -> dict:
        """Quick health summary."""
        recent = self._results[-50:]
        return {
            "total_checks": len(self._checks),
            "ok": sum(1 for r in recent if r.status == CheckStatus.OK),
            "warn": sum(1 for r in recent if r.status == CheckStatus.WARN),
            "critical": sum(1 for r in recent if r.status == CheckStatus.CRITICAL),
            "error": sum(1 for r in recent if r.status == CheckStatus.ERROR),
            "last_run": self._results[-1].timestamp if self._results else "never",
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
