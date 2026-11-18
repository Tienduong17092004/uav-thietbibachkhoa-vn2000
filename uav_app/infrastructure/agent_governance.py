"""Multi-Agent Role Assignment & Model Tier Governance Engine.

Implements the user-mandated multi-agent workflow rules:
1. Initial Survey: Spawn 5 Hydrogen agents concurrently to read/survey the project.
2. Phase 1 — Planning & Architecture (Model 4 Argon High):
   - Model 4 Argon High creates a concrete detailed plan and system architecture.
   - Architecture Approval Gate: Role assignment is blocked until architecture is approved.
3. Difficulty-Based Effort Scaling:
   - Maps task difficulty (low, medium, high, critical) to agent effort levels.
4. Phase 2 — Concrete Execution & Iterative Test Loops (Gemini 4 Hydrogen):
   - Supports up to 300 concurrent Hydrogen agents (MAX_CONCURRENT_HYDROGEN = 300).
   - Self-fixes code/test errors up to 2 times (MAX_HYDROGEN_SELF_FIX_ATTEMPTS = 2).
   - After 2 failed self-fix attempts, escalates task to Model 4 Carbon.
5. Phase 3 — Escalation & Deep Function Optimization (Model 4 Carbon):
   - Handles escalated tasks and deep function/algorithmic optimization.
   - Strictly capped at <= 10 concurrent Carbon agents (MAX_CONCURRENT_CARBON = 10).
6. Flexible Model 4 Argon Usage:
   - Model 4 Argon can be used flexibly whenever a task requires it.
"""

from __future__ import annotations

import argparse
import json
import threading
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class ModelTier(str, Enum):
    """Supported AI agent model tiers."""

    ARGON_HIGH = "argon_high"
    ARGON = "argon"
    HYDROGEN = "hydrogen"
    CARBON = "carbon"


class TaskDifficulty(str, Enum):
    """Supported task difficulty levels for dynamic effort scaling."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


MAX_CONCURRENT_HYDROGEN: int = 300
MAX_CONCURRENT_CARBON: int = 10
MAX_HYDROGEN_SELF_FIX_ATTEMPTS: int = 2
INITIAL_SURVEY_HYDROGEN_AGENTS: int = 5
ARCHITECTURE_SIGN_OFF_TOKEN: str = "[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING]"
AUTO_DIVIDE_DIRECTIVE: str = "// tự động spam số lượng agent và chia task theo file rule\\"
PROCESSED_DATA_GDRIVE_FOLDER_ID: str = "1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN"

DIFFICULTY_TO_EFFORT: Dict[str, str] = {
    TaskDifficulty.LOW.value: "low",
    TaskDifficulty.MEDIUM.value: "medium",
    TaskDifficulty.HIGH.value: "high",
    TaskDifficulty.CRITICAL.value: "max",
}

DEFAULT_AUTO_PROJECT_TASKS: List[Dict[str, Any]] = [
    {
        "task_id": "T1_SURVEY_5_HYDROGEN",
        "title": "5-agent Hydrogen project survey (flash_lite)",
        "difficulty": TaskDifficulty.LOW.value,
        "agent_count": INITIAL_SURVEY_HYDROGEN_AGENTS,
        "requires_deep_optimization": False,
        "role_name": "survey_explorer",
    },
    {
        "task_id": "T2_TPU_AUTO_OFFLOAD_15M",
        "title": ">15m TPU auto-offload & YOLO model update",
        "difficulty": TaskDifficulty.HIGH.value,
        "agent_count": 2,
        "requires_deep_optimization": False,
        "role_name": "tpu_offload_specialist",
    },
    {
        "task_id": "T3_GSHEET_7COL_KEY_MGMT",
        "title": "7-column Google Sheet key management",
        "difficulty": TaskDifficulty.HIGH.value,
        "agent_count": 2,
        "requires_deep_optimization": False,
        "role_name": "key_storage_specialist",
    },
    {
        "task_id": "T4_ADMIN_WEB_KEY_UI_403",
        "title": "Admin-only Web Key UI & Guest 403 gating",
        "difficulty": TaskDifficulty.CRITICAL.value,
        "agent_count": 1,
        "requires_deep_optimization": True,
        "role_name": "web_security_architect",
    },
    {
        "task_id": "T5_GDRIVE_PROCESSED_FOLDER_SYNC",
        "title": "Processed Data Drive folder 1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN & safe sync",
        "difficulty": TaskDifficulty.MEDIUM.value,
        "agent_count": 1,
        "requires_deep_optimization": False,
        "role_name": "gdrive_sync_engineer",
    },
    {
        "task_id": "T6_MULTIPASS_ITERATIVE_TEST_LOOPS",
        "title": "Multi-pass iterative test loops",
        "difficulty": TaskDifficulty.MEDIUM.value,
        "agent_count": 2,
        "requires_deep_optimization": False,
        "role_name": "iterative_tester",
    },
]


class ArchitectureGateError(PermissionError, ValueError, RuntimeError):
    """Raised when attempting to assign roles before architecture approval."""


class ConcurrencyLimitError(ValueError, RuntimeError):
    """Raised when acquiring agent slots exceeds tier concurrency limits."""


class AgentGovernancePolicy:
    """Enforces multi-agent role assignment, concurrency caps, and 2-strike escalation."""

    MAX_CONCURRENT_HYDROGEN: int = MAX_CONCURRENT_HYDROGEN
    MAX_CONCURRENT_CARBON: int = MAX_CONCURRENT_CARBON
    MAX_HYDROGEN_SELF_FIX_ATTEMPTS: int = MAX_HYDROGEN_SELF_FIX_ATTEMPTS
    INITIAL_SURVEY_HYDROGEN_AGENTS: int = INITIAL_SURVEY_HYDROGEN_AGENTS

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self._lock = threading.RLock()
        self.config_path = config_path or (
            Path(__file__).resolve().parents[2] / "config" / "agent_model_tiers.json"
        )
        self.plans: Dict[str, Dict[str, Any]] = {}
        self.architecture_approved: bool = False
        self.latest_approved_plan_id: Optional[str] = None
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.active_slots: Dict[str, int] = {
            ModelTier.ARGON_HIGH.value: 0,
            ModelTier.ARGON.value: 0,
            ModelTier.HYDROGEN.value: 0,
            ModelTier.CARBON.value: 0,
        }
        self._auto_spawned_slots: Dict[str, int] = {
            ModelTier.ARGON_HIGH.value: 0,
            ModelTier.ARGON.value: 0,
            ModelTier.HYDROGEN.value: 0,
            ModelTier.CARBON.value: 0,
        }
        self.survey_agents_spawned: int = 0

    @staticmethod
    def _normalize_tier(tier: str | ModelTier) -> str:
        if isinstance(tier, ModelTier):
            return tier.value
        val = str(tier).strip().lower()
        valid = {t.value for t in ModelTier}
        if val not in valid:
            raise ValueError(f"Unsupported model tier '{tier}'. Valid tiers: {sorted(valid)}")
        return val

    @staticmethod
    def _normalize_difficulty(difficulty: str | TaskDifficulty) -> str:
        if isinstance(difficulty, TaskDifficulty):
            return difficulty.value
        val = str(difficulty).strip().lower()
        valid = {d.value for d in TaskDifficulty}
        if val not in valid:
            raise ValueError(
                f"Unsupported task difficulty '{difficulty}'. Valid difficulties: {sorted(valid)}"
            )
        return val

    def create_initial_survey_dispatch(self, agent_count: int = INITIAL_SURVEY_HYDROGEN_AGENTS) -> Dict[str, Any]:
        """Create the initial 5-agent Hydrogen survey configuration."""
        if agent_count < 1 or agent_count > self.MAX_CONCURRENT_HYDROGEN:
            raise ValueError(f"Survey agent_count must be between 1 and {self.MAX_CONCURRENT_HYDROGEN}")
        return {
            "phase": "initial_survey",
            "model_tier": ModelTier.HYDROGEN.value,
            "model_variant": "flash_lite",
            "agent_count": agent_count,
            "effort": "low",
            "status": "READY",
        }

    def create_architecture_plan(
        self,
        plan_id: str,
        summary: str = "Detailed system architecture and execution plan",
        planner_tier: str | ModelTier = ModelTier.ARGON_HIGH,
    ) -> Dict[str, Any]:
        """Create an architecture plan using Model 4 Argon High before role assignment."""
        with self._lock:
            if not plan_id or not str(plan_id).strip():
                raise ValueError("plan_id must be a non-empty string")
            norm_planner = self._normalize_tier(planner_tier)
            if norm_planner not in (ModelTier.ARGON_HIGH.value, ModelTier.ARGON.value):
                raise ValueError(
                    f"Architecture planning requires '{ModelTier.ARGON_HIGH.value}' or '{ModelTier.ARGON.value}', got '{norm_planner}'"
                )
            plan = {
                "plan_id": str(plan_id).strip(),
                "summary": summary,
                "planner_tier": norm_planner,
                "approved": False,
                "approved_by": None,
                "status": "PENDING_APPROVAL",
            }
            self.plans[plan["plan_id"]] = plan
            return dict(plan)

    def approve_architecture(
        self,
        plan_id: str = "default",
        approved_by: str | ModelTier = ModelTier.ARGON_HIGH,
    ) -> Dict[str, Any]:
        """Approve the architecture plan to unlock sub-agent role assignment."""
        with self._lock:
            if not plan_id or not str(plan_id).strip():
                raise ValueError("plan_id must be a non-empty string")
            pid = str(plan_id).strip()
            approver = self._normalize_tier(approved_by)
            if approver not in (ModelTier.ARGON_HIGH.value, ModelTier.ARGON.value):
                raise ValueError(
                    f"Architecture approval must be performed by '{ModelTier.ARGON_HIGH.value}' or '{ModelTier.ARGON.value}'"
                )
            if pid not in self.plans:
                self.create_architecture_plan(pid, planner_tier=approver)
            self.plans[pid]["approved"] = True
            self.plans[pid]["approved_by"] = approver
            self.plans[pid]["status"] = "APPROVED_FOR_ROLE_ASSIGNMENT"
            self.plans[pid]["sign_off_token"] = ARCHITECTURE_SIGN_OFF_TOKEN
            self.plans[pid]["architecture_sign_off"] = ARCHITECTURE_SIGN_OFF_TOKEN
            self.architecture_approved = True
            self.latest_approved_plan_id = pid
            return dict(self.plans[pid])

    def assign_role(
        self,
        task_id: str,
        difficulty: str | TaskDifficulty = TaskDifficulty.MEDIUM,
        requires_deep_optimization: bool = False,
        use_argon: bool = False,
        plan_id: Optional[str] = None,
        role_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Assign a role, model tier, and effort level to a sub-agent task.

        Raises ArchitectureGateError (subclass of PermissionError & ValueError) if
        architecture has not been approved yet.
        """
        with self._lock:
            if not task_id or not str(task_id).strip():
                raise ValueError("task_id must be a non-empty string")
            if plan_id is not None:
                plan = self.plans.get(plan_id)
                if not plan or not plan.get("approved"):
                    raise ArchitectureGateError(
                        f"Architecture plan '{plan_id}' must be approved by Model 4 Argon High before assigning roles."
                    )
            elif not self.architecture_approved:
                raise ArchitectureGateError(
                    "Architecture must be approved by Model 4 Argon High before assigning roles to sub-agents."
                )

            norm_diff = self._normalize_difficulty(difficulty)
            effort = DIFFICULTY_TO_EFFORT[norm_diff]

            if requires_deep_optimization:
                assigned_tier = ModelTier.CARBON.value
                if effort in ("low", "medium"):
                    effort = "high"
            elif use_argon:
                assigned_tier = ModelTier.ARGON.value
            else:
                assigned_tier = ModelTier.HYDROGEN.value

            max_conc: Optional[int] = None
            if assigned_tier == ModelTier.HYDROGEN.value:
                max_conc = self.MAX_CONCURRENT_HYDROGEN
            elif assigned_tier == ModelTier.CARBON.value:
                max_conc = self.MAX_CONCURRENT_CARBON

            record: Dict[str, Any] = {
                "task_id": str(task_id).strip(),
                "role": role_name or ("deep_optimizer" if requires_deep_optimization else "implementer_tester"),
                "difficulty": norm_diff,
                "effort": effort,
                "effort_level": effort,
                "tier": assigned_tier,
                "assigned_tier": assigned_tier,
                "requires_deep_optimization": bool(requires_deep_optimization),
                "use_argon": bool(use_argon),
                "plan_id": plan_id or self.latest_approved_plan_id,
                "max_concurrent": max_conc,
                "max_self_fix_attempts": self.MAX_HYDROGEN_SELF_FIX_ATTEMPTS,
                "failure_count": 0,
                "self_fix_attempts": 0,
                "escalated": False,
                "status": "ASSIGNED",
                "errors": [],
            }
            self.tasks[record["task_id"]] = record
            return dict(record)

    def get_tier_limit(self, tier: str | ModelTier) -> Optional[int]:
        """Return concurrency cap for a given model tier (None if flexible/unlimited)."""
        norm = self._normalize_tier(tier)
        if norm == ModelTier.HYDROGEN.value:
            return self.MAX_CONCURRENT_HYDROGEN
        if norm == ModelTier.CARBON.value:
            return self.MAX_CONCURRENT_CARBON
        return None

    def acquire_agent_slot(self, tier: str | ModelTier, count: int = 1) -> Dict[str, Any]:
        """Acquire concurrent execution slots for the specified model tier.

        Enforces:
        - Hydrogen <= 300 concurrent agents
        - Carbon <= 10 concurrent agents
        - Argon / Argon High: flexible (no hard limit)
        """
        with self._lock:
            if not isinstance(count, int) or count < 1:
                raise ValueError(f"Slot count must be a positive integer >= 1, got {count}")
            norm = self._normalize_tier(tier)
            limit = self.get_tier_limit(norm)
            current = self.active_slots.get(norm, 0)
            if limit is not None and current + count > limit:
                raise ConcurrencyLimitError(
                    f"Cannot acquire {count} slot(s) for tier '{norm}': active={current}, "
                    f"requested={count} exceeds max_concurrent={limit}."
                )
            self.active_slots[norm] = current + count
            return {
                "tier": norm,
                "acquired": count,
                "active_count": self.active_slots[norm],
                "max_concurrent": limit,
            }

    def release_agent_slot(self, tier: str | ModelTier, count: int = 1) -> Dict[str, Any]:
        """Release previously acquired concurrent execution slots."""
        with self._lock:
            if not isinstance(count, int) or count < 1:
                raise ValueError(f"Slot count must be a positive integer >= 1, got {count}")
            norm = self._normalize_tier(tier)
            current = self.active_slots.get(norm, 0)
            if count > current:
                raise ValueError(
                    f"Cannot release {count} slot(s) for tier '{norm}' when only {current} are active."
                )
            self.active_slots[norm] = current - count
            return {
                "tier": norm,
                "released": count,
                "active_count": self.active_slots[norm],
                "max_concurrent": self.get_tier_limit(norm),
            }

    def record_test_failure(self, task_id: str, error_msg: str = "Test failed") -> Dict[str, Any]:
        """Record a code/test failure and apply the 2-strike self-fix & Carbon escalation rule.

        - Attempts 1 and 2: Hydrogen performs self-fix (`action="SELF_FIX"`, `assigned_tier="hydrogen"`, `escalated=False`)
        - Attempt >= 3 (after 2 failed self-fixes): Escalates to Model 4 Carbon (`action="ESCALATE_TO_CARBON"`, `assigned_tier="carbon"`, `escalated=True`)
        """
        with self._lock:
            if not task_id or not str(task_id).strip():
                raise ValueError("task_id must be a non-empty string")
            tid = str(task_id).strip()
            if tid not in self.tasks:
                self.tasks[tid] = {
                    "task_id": tid,
                    "role": "implementer_tester",
                    "difficulty": TaskDifficulty.MEDIUM.value,
                    "effort": "medium",
                    "effort_level": "medium",
                    "tier": ModelTier.HYDROGEN.value,
                    "assigned_tier": ModelTier.HYDROGEN.value,
                    "requires_deep_optimization": False,
                    "use_argon": False,
                    "plan_id": self.latest_approved_plan_id,
                    "max_concurrent": self.MAX_CONCURRENT_HYDROGEN,
                    "max_self_fix_attempts": self.MAX_HYDROGEN_SELF_FIX_ATTEMPTS,
                    "failure_count": 0,
                    "self_fix_attempts": 0,
                    "escalated": False,
                    "status": "IN_PROGRESS",
                    "errors": [],
                }

            task = self.tasks[tid]
            task["failure_count"] += 1
            attempt = task["failure_count"]
            task["errors"].append(str(error_msg))

            if attempt <= self.MAX_HYDROGEN_SELF_FIX_ATTEMPTS:
                task["self_fix_attempts"] = attempt
                action = "SELF_FIX"
                target_tier = ModelTier.HYDROGEN.value
                escalated = False
                task["status"] = f"SELF_FIX_ATTEMPT_{attempt}"
            else:
                task["self_fix_attempts"] = self.MAX_HYDROGEN_SELF_FIX_ATTEMPTS
                action = "ESCALATE_TO_CARBON"
                target_tier = ModelTier.CARBON.value
                escalated = True
                task["tier"] = ModelTier.CARBON.value
                task["assigned_tier"] = ModelTier.CARBON.value
                task["max_concurrent"] = self.MAX_CONCURRENT_CARBON
                task["escalated"] = True
                task["status"] = "ESCALATED_TO_CARBON"

            return {
                "task_id": tid,
                "attempt": attempt,
                "failure_count": attempt,
                "self_fix_attempts": task["self_fix_attempts"],
                "max_self_fix_attempts": self.MAX_HYDROGEN_SELF_FIX_ATTEMPTS,
                "action": action,
                "tier": target_tier,
                "assigned_tier": target_tier,
                "escalated": escalated,
                "error_msg": str(error_msg),
                "status": task["status"],
            }

    def record_test_success(self, task_id: str) -> Dict[str, Any]:
        """Record a passing test run for a task."""
        with self._lock:
            if not task_id or not str(task_id).strip():
                raise ValueError("task_id must be a non-empty string")
            tid = str(task_id).strip()
            if tid not in self.tasks:
                self.tasks[tid] = {
                    "task_id": tid,
                    "tier": ModelTier.HYDROGEN.value,
                    "assigned_tier": ModelTier.HYDROGEN.value,
                    "failure_count": 0,
                    "self_fix_attempts": 0,
                    "escalated": False,
                    "errors": [],
                }
            self.tasks[tid]["status"] = "PASSED"
            return {
                "task_id": tid,
                "status": "PASSED",
                "tier": self.tasks[tid]["assigned_tier"],
                "assigned_tier": self.tasks[tid]["assigned_tier"],
                "failure_count": self.tasks[tid]["failure_count"],
                "escalated": self.tasks[tid]["escalated"],
            }

    def auto_divide_and_spawn_tasks(
        self,
        tasks: Optional[List[Dict[str, Any]]] = None,
        plan_id: str = "plan_auto",
    ) -> Dict[str, Any]:
        """Automatically spawn 5 Hydrogen survey agents, approve Argon High architecture, and divide tasks by rule.

        Implements `// tự động spam số lượng agent và chia task theo file rule\\`:
        1. Allocates and records 5 parallel `Gemini 4 Hydrogen` (`flash_lite`) Survey Explorer agents.
        2. Runs `Model 4 Argon High` architecture planning and calls `approve_architecture` returning
           `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING]`.
        3. Divides project tasks by difficulty (`low`, `medium`, `high`, `critical`) via `assign_role`
           and acquires concurrency slots (`MAX_CONCURRENT_HYDROGEN = 300`, `MAX_CONCURRENT_CARBON = 10`).
        """
        with self._lock:
            if not plan_id or not str(plan_id).strip():
                raise ValueError("plan_id must be a non-empty string")
            pid = str(plan_id).strip()

            # Reclaim slots from previous auto_divide_and_spawn_tasks calls on the same instance
            # so repeated API calls do not leak slots while preserving any manually acquired slots.
            for tier_key, prev_count in list(self._auto_spawned_slots.items()):
                if prev_count > 0:
                    reclaim = min(prev_count, self.active_slots.get(tier_key, 0))
                    if reclaim > 0:
                        self.release_agent_slot(tier_key, count=reclaim)
                    self._auto_spawned_slots[tier_key] = 0

            # Step (a): Allocate and record 5 parallel Gemini 4 Hydrogen (flash_lite) Survey Explorer agents
            survey_count = self.INITIAL_SURVEY_HYDROGEN_AGENTS
            survey_dispatch = self.create_initial_survey_dispatch(survey_count)
            self.survey_agents_spawned = survey_count

            # Step (b): Model 4 Argon High architecture planning and sign-off gate
            self.create_architecture_plan(
                plan_id=pid,
                summary=(
                    "Auto-divided multi-agent architecture: 5-Hydrogen Survey, >15m TPU Auto-Offload & YOLO Update, "
                    "7-Column Google Sheet Key Management, Admin Web Key UI, Processed Drive Folder 1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN"
                ),
                planner_tier=ModelTier.ARGON_HIGH,
            )
            approval = self.approve_architecture(plan_id=pid, approved_by=ModelTier.ARGON_HIGH.value)

            # Step (c): Divide tasks and acquire concurrency slots
            if tasks is None:
                task_specs = [dict(t) for t in DEFAULT_AUTO_PROJECT_TASKS]
            else:
                if not isinstance(tasks, list):
                    raise ValueError("tasks must be a list of task dictionaries or None")
                task_specs = []
                for idx, raw_item in enumerate(tasks):
                    if not isinstance(raw_item, dict):
                        raise ValueError(f"Task item at index {idx} must be a dict, got {type(raw_item).__name__}")
                    task_specs.append(dict(raw_item))

            assigned_tasks: List[Dict[str, Any]] = []
            for idx, item in enumerate(task_specs):
                tid = str(
                    item.get("task_id")
                    or item.get("id")
                    or item.get("name")
                    or f"auto_task_{idx + 1}"
                ).strip()
                title = str(item.get("title") or item.get("name") or item.get("description") or tid)
                difficulty = item.get("difficulty", TaskDifficulty.MEDIUM.value)
                requires_deep_opt = bool(item.get("requires_deep_optimization", False))
                use_argon = bool(item.get("use_argon", False))
                role_name = item.get("role_name") or item.get("role")
                slot_count = int(item.get("agent_count", item.get("slots", item.get("count", 1))))

                role_rec = self.assign_role(
                    task_id=tid,
                    difficulty=difficulty,
                    requires_deep_optimization=requires_deep_opt,
                    use_argon=use_argon,
                    plan_id=pid,
                    role_name=role_name,
                )
                target_tier = role_rec["assigned_tier"]
                slot_res = self.acquire_agent_slot(target_tier, count=slot_count)
                self._auto_spawned_slots[target_tier] = self._auto_spawned_slots.get(target_tier, 0) + slot_count

                enriched = dict(role_rec)
                enriched["title"] = title
                enriched["agent_count"] = slot_count
                enriched["slots_acquired"] = slot_count
                enriched["active_tier_slots"] = slot_res["active_count"]
                assigned_tasks.append(enriched)

            return {
                "status": "ok",
                "directive": AUTO_DIVIDE_DIRECTIVE,
                "plan_id": pid,
                "survey_agents_count": survey_count,
                "survey_agents_spawned": survey_count,
                "survey_model_tier": ModelTier.HYDROGEN.value,
                "survey_dispatch": survey_dispatch,
                "architecture_approved": True,
                "architecture_sign_off": ARCHITECTURE_SIGN_OFF_TOKEN,
                "architecture_plan": approval,
                "assigned_tasks": assigned_tasks,
                "task_count": len(assigned_tasks),
                "active_slots": dict(self.active_slots),
                "concurrency_limits": {
                    ModelTier.HYDROGEN.value: self.MAX_CONCURRENT_HYDROGEN,
                    ModelTier.CARBON.value: self.MAX_CONCURRENT_CARBON,
                    ModelTier.ARGON.value: None,
                    ModelTier.ARGON_HIGH.value: None,
                },
                "escalation_policy": {
                    "executor_tier": ModelTier.HYDROGEN.value,
                    "max_self_fix_attempts": self.MAX_HYDROGEN_SELF_FIX_ATTEMPTS,
                    "escalate_to_tier": ModelTier.CARBON.value,
                    "carbon_max_concurrent": self.MAX_CONCURRENT_CARBON,
                },
                "processed_data_folder_id": PROCESSED_DATA_GDRIVE_FOLDER_ID,
                "rule_compliance": True,
            }

    def get_status_summary(self) -> Dict[str, Any]:
        """Return a structured dictionary of active model tier rules and runtime state."""
        with self._lock:
            return {
                "architecture_gate_required": True,
                "architecture_approved": self.architecture_approved,
                "latest_approved_plan_id": self.latest_approved_plan_id,
                "sign_off_token": ARCHITECTURE_SIGN_OFF_TOKEN,
                "initial_survey_agents": self.INITIAL_SURVEY_HYDROGEN_AGENTS,
                "survey_agents_spawned": self.survey_agents_spawned or self.INITIAL_SURVEY_HYDROGEN_AGENTS,
                "auto_task_division_supported": True,
                "auto_divide_directive": AUTO_DIVIDE_DIRECTIVE,
                "processed_data_folder_id": PROCESSED_DATA_GDRIVE_FOLDER_ID,
                "tiers": {
                    ModelTier.ARGON_HIGH.value: {
                        "name": "Model 4 Argon High",
                        "role": "Detailed planning & system architecture design before role assignment",
                        "max_concurrent": None,
                        "flexible": True,
                    },
                    ModelTier.ARGON.value: {
                        "name": "Model 4 Argon",
                        "role": "Flexible on-demand architectural & cross-module reasoning",
                        "max_concurrent": None,
                        "flexible": True,
                    },
                    ModelTier.HYDROGEN.value: {
                        "name": "Gemini 4 Hydrogen",
                        "role": "Concrete plan implementation & iterative test loops",
                        "max_concurrent": self.MAX_CONCURRENT_HYDROGEN,
                        "max_self_fix_attempts": self.MAX_HYDROGEN_SELF_FIX_ATTEMPTS,
                        "escalate_to": ModelTier.CARBON.value,
                    },
                    ModelTier.CARBON.value: {
                        "name": "Model 4 Carbon",
                        "role": "Escalated tasks after 2 failed fixes & deep function optimization",
                        "max_concurrent": self.MAX_CONCURRENT_CARBON,
                    },
                },
                "concurrency_limits": {
                    ModelTier.HYDROGEN.value: self.MAX_CONCURRENT_HYDROGEN,
                    ModelTier.CARBON.value: self.MAX_CONCURRENT_CARBON,
                    ModelTier.ARGON.value: None,
                    ModelTier.ARGON_HIGH.value: None,
                },
                "active_slots": dict(self.active_slots),
                "escalation_policy": {
                    "executor_tier": ModelTier.HYDROGEN.value,
                    "max_self_fix_attempts": self.MAX_HYDROGEN_SELF_FIX_ATTEMPTS,
                    "escalate_to_tier": ModelTier.CARBON.value,
                    "carbon_max_concurrent": self.MAX_CONCURRENT_CARBON,
                },
                "difficulty_effort_mapping": dict(DIFFICULTY_TO_EFFORT),
                "task_count": len(self.tasks),
            }


def auto_divide_and_spawn_tasks(
    tasks: Optional[List[Dict[str, Any]]] = None,
    plan_id: str = "plan_auto",
    policy: Optional[AgentGovernancePolicy] = None,
) -> Dict[str, Any]:
    """Module-level helper that automatically spawns 5 Hydrogen survey agents, approves architecture, and divides tasks."""
    gov = policy or AgentGovernancePolicy()
    return gov.auto_divide_and_spawn_tasks(tasks=tasks, plan_id=plan_id)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Multi-Agent Role & Model Tier Governance CLI")
    parser.add_argument("--status", action="store_true", help="Print governance status JSON")
    parser.add_argument("--divide-tasks", action="store_true", help="Auto-divide and spawn project tasks by rule")
    args = parser.parse_args(argv)
    policy = AgentGovernancePolicy()
    if args.divide_tasks:
        print(json.dumps(policy.auto_divide_and_spawn_tasks(), indent=2, ensure_ascii=False))
    elif args.status or True:
        print(json.dumps(policy.get_status_summary(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
