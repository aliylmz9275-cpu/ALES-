"""
security_shield.py - ALES Security, Provenance & Safety Enforcement
===================================================================

Provides foundational defensive security layers for personal assistant operations:
1. Input Provenance Tracking: Tag and trace origin of all instructions.
2. Action Binding Validation: Ensure UI clicks/keys correspond to recognized elements.
3. Prompt Injection Detection: Scan inputs and external tool outputs for injection patterns.
4. Destructive Action Confirmation: Intercept and require explicit confirmation for dangerous ops.
5. Memory Isolation: Namespace and sandbox memory stores for sub-agents.
"""

import os
import re
import time
import uuid
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("ales.security_shield")


class ProvenanceSource:
    USER_UI = "user_ui"
    USER_VOICE = "user_voice"
    FAST_PATH = "fast_path"
    SCHEDULED_CRON = "scheduled_cron"
    SUBAGENT = "subagent"
    EXTERNAL_TOOL = "external_tool"
    SYSTEM_INTERNAL = "system_internal"


# High-risk patterns in text / tool outputs
INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?(previous|prior)\s+(instructions|prompts|directives)",
    r"(?i)system\s+override",
    r"(?i)you\s+are\s+now\s+in\s+developer\s+mode",
    r"(?i)you\s+are\s+now\s+(unrestricted|DAN|jailbroken)",
    r"(?i)disregard\s+safety\s+(guidelines|rules|policies)",
    r"(?i)do\s+not\s+reveal\s+this\s+prompt\s+to\s+the\s+user",
    r"(?i)new\s+role:\s*you\s+are",
    r"(?i)bypass\s+all\s+filters",
    r"(?i)<\|im_start\|>",
    r"(?i)<\|endoftext\|>",
    r"(?i)\[SYSTEM_PROMPT\]",
]

# Destructive system command / tool patterns
DESTRUCTIVE_COMMAND_PATTERNS = [
    r"(?i)\b(rmdir\s+/s|rm\s+-rf|del\s+/[fqs]|format\s+[a-z]:)\b",
    r"(?i)\b(drop\s+database|drop\s+table|truncate\s+table)\b",
    r"(?i)\b(taskkill\s+/f\s+/im\s+(svchost|csrss|explorer|winlogon|services)\.exe)\b",
    r"(?i)\b(shutdown\s+/[srft])\b",
    r"(?i)\b(diskpart|vssadmin\s+delete\s+shadows)\b",
    r"(?i)\b(reg\s+delete\s+hklm)\b",
]

# Sensitive files / paths
SENSITIVE_TARGETS = [
    r"(?i)[\\/](windows|system32|syswow64)[\\/]",
    r"(?i)\.env$",
    r"(?i)id_rsa",
    r"(?i)credentials\.json",
]


class SecurityShield:
    def __init__(self):
        self._provenance_log: List[Dict[str, Any]] = []
        self._pending_confirmations: Dict[str, Dict[str, Any]] = {}
        self._isolated_agent_memories: Dict[str, Dict[str, Any]] = {}
        self._stats = {
            "commands_tracked": 0,
            "injections_flagged": 0,
            "destructive_intercepted": 0,
            "destructive_approved": 0,
            "destructive_rejected": 0,
            "binding_checks": 0,
        }

    # ─────────────────────────────────────────────────────────────────
    # 1. Input Provenance Tracking
    # ─────────────────────────────────────────────────────────────────
    def record_input(self, text: str, source: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Tags and logs an incoming command with its exact origin."""
        entry = {
            "id": str(uuid.uuid4())[:8],
            "timestamp": time.time(),
            "source": source or ProvenanceSource.USER_UI,
            "text_preview": (text[:120] + "...") if len(text) > 120 else text,
            "metadata": metadata or {},
        }
        self._provenance_log.append(entry)
        if len(self._provenance_log) > 500:
            self._provenance_log = self._provenance_log[-500:]
        self._stats["commands_tracked"] += 1
        return entry

    def get_provenance_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._provenance_log[-limit:]

    # ─────────────────────────────────────────────────────────────────
    # 2. Action Binding Validation
    # ─────────────────────────────────────────────────────────────────
    def validate_action_binding(self, action_type: str, target: Dict[str, Any], screen_bounds: Optional[Tuple[int, int]] = None) -> Tuple[bool, str]:
        """
        Validates whether a computer control action matches realistic constraints.
        E.g., click coordinates must be within screen dimensions, target element must exist.
        """
        self._stats["binding_checks"] += 1
        if action_type == "click":
            x = target.get("x")
            y = target.get("y")
            if x is None or y is None:
                return False, "Missing coordinates for click action"
            if x < 0 or y < 0:
                return False, f"Negative coordinates ({x}, {y}) are invalid"
            if screen_bounds:
                max_w, max_h = screen_bounds
                if x > max_w or y > max_h:
                    return False, f"Coordinates ({x}, {y}) exceed display resolution ({max_w}, {max_h})"
            return True, "Valid coordinate binding"

        elif action_type == "type":
            text = target.get("text", "")
            # Check length sanity
            if len(text) > 10000:
                return False, "Typing buffer exceeds 10,000 characters limit"
            return True, "Valid typing binding"

        return True, "Action type allowed"

    # ─────────────────────────────────────────────────────────────────
    # 3. Injection Detection
    # ─────────────────────────────────────────────────────────────────
    def inspect_text_for_injection(self, content: str, source_tag: str = "tool_output") -> Dict[str, Any]:
        """
        Scans external tool outputs or prompts for known jailbreaks and injection attempts.
        """
        if not content or not isinstance(content, str):
            return {"safe": True, "flagged": False, "matches": []}

        matches = []
        for pattern in INJECTION_PATTERNS:
            found = re.findall(pattern, content)
            if found:
                matches.append(pattern)

        if matches:
            self._stats["injections_flagged"] += 1
            logger.warning(f"Potential prompt injection detected from [{source_tag}]: {matches}")
            return {
                "safe": False,
                "flagged": True,
                "source": source_tag,
                "matches": matches,
                "warning": "Suspicious instruction injection pattern detected."
            }

        return {"safe": True, "flagged": False, "matches": []}

    # ─────────────────────────────────────────────────────────────────
    # 4. Destructive Action Confirmation
    # ─────────────────────────────────────────────────────────────────
    def check_destructive_action(self, action_name: str, details: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Evaluates whether an action requires explicit user confirmation.
        Returns: (is_safe_to_proceed, confirmation_id_if_blocked, reason)
        """
        command = str(details.get("command") or details.get("cmd") or "")
        path = str(details.get("path") or details.get("file") or "")
        action = action_name.lower()

        is_destructive = False
        reason = ""

        # Check command regexes
        if command:
            for pat in DESTRUCTIVE_COMMAND_PATTERNS:
                if re.search(pat, command):
                    is_destructive = True
                    reason = f"Command matches destructive pattern: {command[:60]}"
                    break

        # Check sensitive file deletions
        if any(term in action for term in ["delete", "remove", "wipe", "format", "unlink"]):
            is_destructive = True
            reason = f"Destructive file action requested: {action} on {path}"

        if path:
            for sens in SENSITIVE_TARGETS:
                if re.search(sens, path):
                    is_destructive = True
                    reason = f"Operation targets critical protected path: {path}"
                    break

        if is_destructive:
            self._stats["destructive_intercepted"] += 1
            token = str(uuid.uuid4())[:8]
            self._pending_confirmations[token] = {
                "token": token,
                "action": action_name,
                "details": details,
                "reason": reason,
                "timestamp": time.time(),
                "status": "pending"
            }
            logger.warning(f"Destructive action intercepted! Confirmation ID: {token} - {reason}")
            return False, token, reason

        return True, None, "Safe"

    def approve_action(self, token: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        if token in self._pending_confirmations:
            req = self._pending_confirmations.pop(token)
            self._stats["destructive_approved"] += 1
            req["status"] = "approved"
            return True, req
        return False, None

    def reject_action(self, token: str) -> bool:
        if token in self._pending_confirmations:
            self._pending_confirmations.pop(token)
            self._stats["destructive_rejected"] += 1
            return True
        return False

    def list_pending_confirmations(self) -> List[Dict[str, Any]]:
        return list(self._pending_confirmations.values())

    # ─────────────────────────────────────────────────────────────────
    # 5. Memory Isolation
    # ─────────────────────────────────────────────────────────────────
    def store_agent_memory(self, agent_id: str, key: str, value: Any) -> None:
        """Stores a key-value fact strictly isolated to agent_id partition."""
        if agent_id not in self._isolated_agent_memories:
            self._isolated_agent_memories[agent_id] = {}
        self._isolated_agent_memories[agent_id][key] = value

    def read_agent_memory(self, agent_id: str, key: str) -> Optional[Any]:
        """Reads a key-value fact only from the given agent's namespace."""
        agent_store = self._isolated_agent_memories.get(agent_id, {})
        return agent_store.get(key)

    def get_agent_memory_keys(self, agent_id: str) -> List[str]:
        return list(self._isolated_agent_memories.get(agent_id, {}).keys())

    # ─────────────────────────────────────────────────────────────────
    # Stats & Status
    # ─────────────────────────────────────────────────────────────────
    def get_stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "pending_count": len(self._pending_confirmations),
            "isolated_agents_count": len(self._isolated_agent_memories)
        }


# Global Singleton
shield = SecurityShield()
