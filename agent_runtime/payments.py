"""
Payments — L4 payment integration with SSHPay.

Phase 3: Enables L4 agents to execute payments through SSHPay
with mandatory secondary confirmation via Matrix interactive messages.
All payment operations are audit-logged with hash-chain integrity.
"""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from . import Runtime

logger = logging.getLogger("agent-runtime.payments")


class PaymentStatus(str, Enum):
    PENDING = "pending"             # Awaiting confirmation
    CONFIRMED = "confirmed"         # Confirmed by owner
    PROCESSING = "processing"       # Sent to SSHPay
    COMPLETED = "completed"         # Payment successful
    FAILED = "failed"               # Payment failed
    REJECTED = "rejected"           # Rejected by owner
    EXPIRED = "expired"             # Confirmation timed out


class Currency(str, Enum):
    USD = "USD"
    USDC = "USDC"
    SOL = "SOL"


@dataclass
class PaymentRequest:
    """A payment request awaiting L4 confirmation."""
    request_id: str
    amount: float
    currency: Currency = Currency.USD
    recipient: str = ""                     # DID or SSHPay recipient ID
    description: str = ""
    status: PaymentStatus = PaymentStatus.PENDING
    confirmation_code: str = ""             # Short code owner must provide
    confirmation_deadline: str = ""          # ISO timestamp
    sshpay_transaction_id: str = ""
    result: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""

    def __post_init__(self):
        now = _now_iso()
        if not self.created_at:
            self.created_at = now
        self.updated_at = now


class PaymentManager:
    """L4 payment execution with mandatory confirmation."""

    # Confirmation timeout in seconds
    CONFIRMATION_TIMEOUT = 300  # 5 minutes
    # Max payment without additional verification
    AUTO_APPROVE_LIMIT = 0.0  # Never auto-approve

    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime
        self._requests: dict[str, PaymentRequest] = {}
        self._sshpay_endpoint = ""
        self._sshpay_api_key = ""
        self._check_task: Optional[asyncio.Task] = None

    def configure(self, endpoint: str = "", api_key: str = ""):
        """Configure SSHPay connection."""
        self._sshpay_endpoint = endpoint or os.environ.get("SSHPAY_ENDPOINT", "")
        self._sshpay_api_key = api_key or os.environ.get("SSHPAY_API_KEY", "")

    # ── Payment Request Lifecycle ──────────────────────

    async def request(
        self,
        amount: float,
        currency: Currency = Currency.USD,
        recipient: str = "",
        description: str = "",
    ) -> PaymentRequest:
        """Create a payment request. Blocks until confirmed or rejected."""
        if not self.runtime.permissions.can_pay():
            raise PermissionError(
                f"Payments require L4. Current: L{self.runtime.permissions.level}"
            )

        import uuid
        import secrets

        confirmation_code = secrets.token_hex(4).upper()[:8]
        request_id = f"PAY-{uuid.uuid4().hex[:8].upper()}"

        payment = PaymentRequest(
            request_id=request_id,
            amount=amount,
            currency=currency,
            recipient=recipient or f"sshpay:{description[:20]}",
            description=description,
            confirmation_code=confirmation_code,
            confirmation_deadline=_iso_offset(PaymentManager.CONFIRMATION_TIMEOUT),
        )

        self._requests[request_id] = payment

        # Send confirmation request to owner via Matrix
        await self._send_confirmation_request(payment)

        # Log
        self.runtime.storage.audit("payment_requested", {
            "request_id": request_id,
            "amount": amount,
            "currency": currency.value,
            "recipient": recipient,
            "description": description,
        })

        logger.info(f"Payment requested: {request_id} — {amount} {currency.value}")
        return payment

    async def confirm(self, request_id: str, code: str) -> bool:
        """Confirm a payment with the confirmation code."""
        payment = self._requests.get(request_id)
        if not payment:
            logger.error(f"Payment not found: {request_id}")
            return False

        if payment.status != PaymentStatus.PENDING:
            logger.warning(f"Payment {request_id} is not PENDING ({payment.status.value})")
            return False

        # Check deadline
        if payment.confirmation_deadline:
            deadline = datetime.fromisoformat(payment.confirmation_deadline)
            if datetime.now(timezone.utc) > deadline:
                payment.status = PaymentStatus.EXPIRED
                payment.updated_at = _now_iso()
                logger.warning(f"Payment {request_id} expired")
                return False

        # Verify code
        if code.upper() != payment.confirmation_code:
            logger.warning(f"Invalid confirmation code for {request_id}")
            self.runtime.storage.audit("payment_confirmation_failed", {
                "request_id": request_id,
                "reason": "invalid_code",
            })
            return False

        # Confirm
        payment.status = PaymentStatus.CONFIRMED
        payment.updated_at = _now_iso()

        self.runtime.storage.audit("payment_confirmed", {
            "request_id": request_id,
            "amount": payment.amount,
            "currency": payment.currency.value,
        })

        # Execute payment asynchronously
        asyncio.create_task(self._execute_payment(request_id))

        logger.info(f"Payment confirmed: {request_id}")
        return True

    async def reject(self, request_id: str, reason: str = "") -> bool:
        """Reject a payment request."""
        payment = self._requests.get(request_id)
        if not payment:
            return False

        payment.status = PaymentStatus.REJECTED
        payment.updated_at = _now_iso()
        payment.completed_at = _now_iso()

        self.runtime.storage.audit("payment_rejected", {
            "request_id": request_id,
            "reason": reason,
        })

        await self.runtime.notifier.notify(
            f"❌ Payment rejected: {request_id}\nAmount: {payment.amount} {payment.currency.value}\nReason: {reason}",
            severity="warn",
        )
        return True

    # ── Payment Execution ───────────────────────────────

    async def _execute_payment(self, request_id: str):
        """Execute a confirmed payment through SSHPay."""
        payment = self._requests.get(request_id)
        if not payment or payment.status != PaymentStatus.CONFIRMED:
            return

        payment.status = PaymentStatus.PROCESSING
        payment.updated_at = _now_iso()

        try:
            # Call SSHPay API
            result = await self._call_sshpay(payment)

            if result.get("success"):
                payment.status = PaymentStatus.COMPLETED
                payment.sshpay_transaction_id = result.get("transaction_id", "")
                payment.result = result
                payment.completed_at = _now_iso()

                self.runtime.storage.audit("payment_completed", {
                    "request_id": request_id,
                    "transaction_id": payment.sshpay_transaction_id,
                    "amount": payment.amount,
                })

                await self.runtime.notifier.notify(
                    f"💸 Payment completed: {request_id}\n"
                    f"Amount: {payment.amount} {payment.currency.value}\n"
                    f"TX: {payment.sshpay_transaction_id}",
                    severity="info",
                )
            else:
                payment.status = PaymentStatus.FAILED
                payment.result = result
                payment.completed_at = _now_iso()

                self.runtime.storage.audit("payment_failed", {
                    "request_id": request_id,
                    "error": result.get("error", "unknown"),
                })

                await self.runtime.notifier.notify(
                    f"❌ Payment failed: {request_id}\nError: {result.get('error', 'unknown')}",
                    severity="error",
                )
        except Exception as e:
            payment.status = PaymentStatus.FAILED
            payment.completed_at = _now_iso()
            payment.result = {"error": str(e)}

            logger.error(f"Payment execution error: {e}")

        payment.updated_at = _now_iso()

    async def _call_sshpay(self, payment: PaymentRequest) -> dict:
        """Call SSHPay API to execute a payment."""
        if not self._sshpay_endpoint:
            return {"success": False, "error": "SSHPay not configured"}

        import urllib.request

        payload = json.dumps({
            "amount": payment.amount,
            "currency": payment.currency.value,
            "recipient": payment.recipient,
            "description": payment.description,
            "idempotency_key": payment.request_id,
        }).encode()

        req = urllib.request.Request(
            f"{self._sshpay_endpoint}/v1/payments",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._sshpay_api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Confirmation Request ────────────────────────────

    async def _send_confirmation_request(self, payment: PaymentRequest):
        """Send an interactive confirmation message to the owner."""
        message = (
            f"🔐 Payment Confirmation Required\n\n"
            f"Request: {payment.request_id}\n"
            f"Amount: {payment.amount} {payment.currency.value}\n"
            f"To: {payment.recipient}\n"
            f"For: {payment.description}\n\n"
            f"Confirmation code: **{payment.confirmation_code}**\n"
            f"Expires: {payment.confirmation_deadline[:19]}\n\n"
            f"Reply with the code to confirm, or 'reject' to cancel."
        )

        await self.runtime.notifier.notify(message, severity="warn")

    # ── Queries ─────────────────────────────────────────

    def get(self, request_id: str) -> Optional[PaymentRequest]:
        return self._requests.get(request_id)

    def list_pending(self) -> list[PaymentRequest]:
        return [p for p in self._requests.values() if p.status == PaymentStatus.PENDING]

    def stats(self) -> dict:
        requests = list(self._requests.values())
        return {
            "total": len(requests),
            "pending": sum(1 for r in requests if r.status == PaymentStatus.PENDING),
            "confirmed": sum(1 for r in requests if r.status == PaymentStatus.CONFIRMED),
            "completed": sum(1 for r in requests if r.status == PaymentStatus.COMPLETED),
            "failed": sum(1 for r in requests if r.status == PaymentStatus.FAILED),
            "rejected": sum(1 for r in requests if r.status == PaymentStatus.REJECTED),
            "total_volume": sum(r.amount for r in requests if r.status == PaymentStatus.COMPLETED),
        }


import os


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_offset(seconds: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
