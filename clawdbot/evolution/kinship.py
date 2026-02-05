"""Kinship - Family relationships and kin cooperation.

Bots know their family members (parent, children, siblings) and can
cooperate with them. Resource sharing follows Hamilton's rule: rb > c
where r=relatedness, b=benefit to recipient, c=cost to helper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# Relatedness coefficients
RELATEDNESS_PARENT_CHILD = 0.5
RELATEDNESS_SIBLINGS = 0.5
RELATEDNESS_GRANDPARENT = 0.25
RELATEDNESS_HALF_SIBLINGS = 0.25


@dataclass
class FamilyMemberStatus:
    """Status of a known family member."""

    name: str
    relationship: str  # 'parent', 'child', 'sibling'
    relatedness: float
    last_known_balance: float = 0.0
    last_known_cycle: int = 0
    last_update_cycle: int = 0  # Our cycle when we last heard from them
    is_alive: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence."""
        return {
            "name": self.name,
            "relationship": self.relationship,
            "relatedness": self.relatedness,
            "last_known_balance": self.last_known_balance,
            "last_known_cycle": self.last_known_cycle,
            "last_update_cycle": self.last_update_cycle,
            "is_alive": self.is_alive,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FamilyMemberStatus:
        """Restore from serialized data."""
        return cls(
            name=data["name"],
            relationship=data["relationship"],
            relatedness=data.get("relatedness", 0.5),
            last_known_balance=data.get("last_known_balance", 0.0),
            last_known_cycle=data.get("last_known_cycle", 0),
            last_update_cycle=data.get("last_update_cycle", 0),
            is_alive=data.get("is_alive", True),
        )


@dataclass
class HelpDecision:
    """Decision about whether to help a family member."""

    should_help: bool
    amount: float
    reason: str
    benefit_score: float = 0.0
    cost_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging."""
        return {
            "should_help": self.should_help,
            "amount": self.amount,
            "reason": self.reason,
            "benefit_score": self.benefit_score,
            "cost_score": self.cost_score,
        }


@dataclass
class FamilyNetwork:
    """Tracks family relationships and communication.

    Bots know their parent, children, and siblings (learned from parent).
    Family members can communicate status updates and help each other.
    """

    # Core relationships
    parent_name: str | None = None
    children: dict[str, FamilyMemberStatus] = field(default_factory=dict)
    siblings: dict[str, FamilyMemberStatus] = field(default_factory=dict)

    # Pending messages (queued for next communication opportunity)
    _pending_updates: list[dict[str, Any]] = field(default_factory=list)

    def set_parent(self, parent_name: str) -> None:
        """Set the parent's name (typically set at birth)."""
        self.parent_name = parent_name

    def add_child(self, child_name: str) -> None:
        """Register a new child."""
        self.children[child_name] = FamilyMemberStatus(
            name=child_name,
            relationship="child",
            relatedness=RELATEDNESS_PARENT_CHILD,
        )

    def add_sibling(self, sibling_name: str) -> None:
        """Register a sibling (typically learned from parent)."""
        if sibling_name not in self.siblings:
            self.siblings[sibling_name] = FamilyMemberStatus(
                name=sibling_name,
                relationship="sibling",
                relatedness=RELATEDNESS_SIBLINGS,
            )

    def remove_child(self, child_name: str) -> None:
        """Remove a child (e.g., if child died)."""
        if child_name in self.children:
            self.children[child_name].is_alive = False

    def get_child_status(self, child_name: str) -> FamilyMemberStatus | None:
        """Get the last known status of a child."""
        return self.children.get(child_name)

    def receive_status_update(
        self,
        from_name: str,
        my_cycle: int,
        status: dict[str, Any],
    ) -> None:
        """Receive a status update from a family member.

        Args:
            from_name: Name of family member sending update
            my_cycle: Our current cycle
            status: Status dict with balance, cycle_count, etc.
        """
        # Check if this is from a child
        if from_name in self.children:
            member = self.children[from_name]
            member.last_known_balance = status.get("balance", member.last_known_balance)
            member.last_known_cycle = status.get("cycle_count", member.last_known_cycle)
            member.last_update_cycle = my_cycle
            member.is_alive = True
            return

        # Check if this is from a sibling
        if from_name in self.siblings:
            member = self.siblings[from_name]
            member.last_known_balance = status.get("balance", member.last_known_balance)
            member.last_known_cycle = status.get("cycle_count", member.last_known_cycle)
            member.last_update_cycle = my_cycle
            member.is_alive = True
            return

    def receive_death_notification(self, deceased_name: str) -> None:
        """Receive notification that a family member died."""
        if deceased_name in self.children:
            self.children[deceased_name].is_alive = False
        if deceased_name in self.siblings:
            self.siblings[deceased_name].is_alive = False
        if deceased_name == self.parent_name:
            # Parent died - we're orphaned but parent_name stays for lineage
            pass

    def get_status_for_parent(
        self,
        my_balance: float,
        my_cycle: int,
        my_children_count: int,
    ) -> dict[str, Any]:
        """Generate a status update to send to parent.

        Args:
            my_balance: Our current balance
            my_cycle: Our current cycle
            my_children_count: Number of children we have

        Returns:
            Status dict to send to parent
        """
        return {
            "type": "status_update",
            "cycle_count": my_cycle,
            "balance": my_balance,
            "children_count": my_children_count,
        }

    def get_death_notification(
        self,
        my_name: str,
        death_cause: str,
        final_stats: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate a death notification to send to family.

        Args:
            my_name: Our name
            death_cause: Cause of death
            final_stats: Final statistics

        Returns:
            Death notification to broadcast
        """
        notify_list = []
        if self.parent_name:
            notify_list.append(self.parent_name)
        notify_list.extend(c.name for c in self.children.values() if c.is_alive)

        return {
            "type": "death_notification",
            "deceased": my_name,
            "cause": death_cause,
            "final_stats": final_stats,
            "notify": notify_list,
        }

    def introduce_siblings_to_child(
        self,
        new_child_name: str,
    ) -> list[str]:
        """Get list of siblings to introduce to a new child.

        Args:
            new_child_name: Name of the new child

        Returns:
            List of sibling names to introduce
        """
        return [
            name for name, child in self.children.items()
            if name != new_child_name and child.is_alive
        ]

    def get_living_children(self) -> list[FamilyMemberStatus]:
        """Get list of living children."""
        return [c for c in self.children.values() if c.is_alive]

    def get_struggling_children(self, balance_threshold: float = 0.05) -> list[FamilyMemberStatus]:
        """Get list of children who appear to be struggling.

        Args:
            balance_threshold: Balance below which a child is struggling

        Returns:
            List of struggling children
        """
        return [
            c for c in self.children.values()
            if c.is_alive and c.last_known_balance < balance_threshold
        ]

    @property
    def total_family_size(self) -> int:
        """Total known family members (alive)."""
        count = 0
        if self.parent_name:
            count += 1
        count += sum(1 for c in self.children.values() if c.is_alive)
        count += sum(1 for s in self.siblings.values() if s.is_alive)
        return count

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence."""
        return {
            "parent_name": self.parent_name,
            "children": {
                name: child.to_dict()
                for name, child in self.children.items()
            },
            "siblings": {
                name: sibling.to_dict()
                for name, sibling in self.siblings.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FamilyNetwork:
        """Restore from serialized data."""
        return cls(
            parent_name=data.get("parent_name"),
            children={
                name: FamilyMemberStatus.from_dict(child_data)
                for name, child_data in data.get("children", {}).items()
            },
            siblings={
                name: FamilyMemberStatus.from_dict(sibling_data)
                for name, sibling_data in data.get("siblings", {}).items()
            },
        )


@dataclass
class KinCooperation:
    """Implements Hamilton's rule for kin-based resource sharing.

    Hamilton's rule: rb > c
    - r = relatedness coefficient (0.5 for parent-child, 0.25 for grandparent)
    - b = benefit to recipient
    - c = cost to helper

    Bots help family members when the inclusive fitness benefit exceeds cost.
    """

    # Configurable thresholds
    min_helper_surplus: float = 0.05  # Don't help if I have less than this surplus
    min_transfer_amount: float = 0.01  # Don't bother with tiny transfers
    max_transfer_ratio: float = 0.3  # Never give more than 30% of surplus

    # Genome-influenced parameters
    kin_helping_threshold: float = 0.1  # rb - c must exceed this to help

    def should_help(
        self,
        helper_balance: float,
        helper_min_balance: float,
        recipient_balance: float,
        recipient_risk_threshold: float,
        relatedness: float,
    ) -> HelpDecision:
        """Decide whether to help a family member.

        Args:
            helper_balance: Helper's current balance
            helper_min_balance: Helper's minimum comfortable balance
            recipient_balance: Recipient's current balance
            recipient_risk_threshold: Balance below which recipient is at risk
            relatedness: Genetic relatedness coefficient

        Returns:
            HelpDecision with whether to help and how much
        """
        # Calculate helper's surplus
        surplus = helper_balance - helper_min_balance
        if surplus < self.min_helper_surplus:
            return HelpDecision(
                should_help=False,
                amount=0.0,
                reason="Helper has insufficient surplus",
            )

        # Calculate recipient's need (benefit from receiving help)
        # Higher need = more benefit
        if recipient_balance >= recipient_risk_threshold:
            return HelpDecision(
                should_help=False,
                amount=0.0,
                reason="Recipient is not struggling",
            )

        # Benefit scales with how much the recipient needs
        recipient_risk = 1.0 - (recipient_balance / recipient_risk_threshold)
        benefit = recipient_risk  # 0 to 1, higher = more benefit

        # Cost is proportional to what we give
        # We'll give at most max_transfer_ratio of our surplus
        max_gift = surplus * self.max_transfer_ratio

        # But also cap at what recipient needs
        recipient_need = recipient_risk_threshold - recipient_balance
        proposed_gift = min(max_gift, recipient_need * 0.5)  # Give half of what they need

        if proposed_gift < self.min_transfer_amount:
            return HelpDecision(
                should_help=False,
                amount=0.0,
                reason="Transfer amount too small to be meaningful",
            )

        # Cost is the fraction of surplus we're giving
        cost = proposed_gift / surplus

        # Hamilton's rule: rb > c
        inclusive_fitness_gain = relatedness * benefit - cost

        if inclusive_fitness_gain > self.kin_helping_threshold:
            return HelpDecision(
                should_help=True,
                amount=proposed_gift,
                reason=f"Hamilton's rule satisfied: r*b ({relatedness:.2f}*{benefit:.2f}) - c ({cost:.2f}) = {inclusive_fitness_gain:.3f}",
                benefit_score=benefit,
                cost_score=cost,
            )

        return HelpDecision(
            should_help=False,
            amount=0.0,
            reason=f"Hamilton's rule not satisfied: r*b - c = {inclusive_fitness_gain:.3f} < {self.kin_helping_threshold}",
            benefit_score=benefit,
            cost_score=cost,
        )

    def evaluate_child_help(
        self,
        helper_balance: float,
        helper_min_balance: float,
        child: FamilyMemberStatus,
        risk_threshold: float = 0.05,
    ) -> HelpDecision:
        """Evaluate whether to help a specific child.

        Args:
            helper_balance: Parent's current balance
            helper_min_balance: Parent's minimum comfortable balance
            child: Child's status
            risk_threshold: Balance below which child is at risk
        """
        return self.should_help(
            helper_balance=helper_balance,
            helper_min_balance=helper_min_balance,
            recipient_balance=child.last_known_balance,
            recipient_risk_threshold=risk_threshold,
            relatedness=RELATEDNESS_PARENT_CHILD,
        )

    def check_family_needs(
        self,
        helper_balance: float,
        helper_min_balance: float,
        family: FamilyNetwork,
        risk_threshold: float = 0.05,
    ) -> list[tuple[str, HelpDecision]]:
        """Check all family members and decide who needs help.

        Args:
            helper_balance: Our current balance
            helper_min_balance: Our minimum comfortable balance
            family: Our family network
            risk_threshold: Balance below which someone is at risk

        Returns:
            List of (member_name, HelpDecision) for members we should help
        """
        help_decisions = []

        # Check children first (higher priority)
        for child in family.get_living_children():
            decision = self.evaluate_child_help(
                helper_balance=helper_balance,
                helper_min_balance=helper_min_balance,
                child=child,
                risk_threshold=risk_threshold,
            )
            if decision.should_help:
                help_decisions.append((child.name, decision))
                # Reduce available balance for next decisions
                helper_balance -= decision.amount

        # Could also check siblings with lower priority
        # (lower relatedness = less likely to help)

        return help_decisions

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration."""
        return {
            "min_helper_surplus": self.min_helper_surplus,
            "min_transfer_amount": self.min_transfer_amount,
            "max_transfer_ratio": self.max_transfer_ratio,
            "kin_helping_threshold": self.kin_helping_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KinCooperation:
        """Restore from serialized data."""
        return cls(
            min_helper_surplus=data.get("min_helper_surplus", 0.05),
            min_transfer_amount=data.get("min_transfer_amount", 0.01),
            max_transfer_ratio=data.get("max_transfer_ratio", 0.3),
            kin_helping_threshold=data.get("kin_helping_threshold", 0.1),
        )


# Message types for family communication
@dataclass
class FamilyMessage:
    """A message between family members."""

    message_type: str  # 'status_update', 'death_notification', 'resource_transfer', 'sibling_introduction'
    from_name: str
    to_name: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for transmission."""
        return {
            "type": self.message_type,
            "from": self.from_name,
            "to": self.to_name,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FamilyMessage:
        """Parse received message."""
        return cls(
            message_type=data["type"],
            from_name=data["from"],
            to_name=data["to"],
            data=data.get("data", {}),
        )

    @classmethod
    def status_update(
        cls,
        from_name: str,
        to_name: str,
        cycle_count: int,
        balance: float,
        children_count: int = 0,
    ) -> FamilyMessage:
        """Create a status update message."""
        return cls(
            message_type="status_update",
            from_name=from_name,
            to_name=to_name,
            data={
                "cycle_count": cycle_count,
                "balance": balance,
                "children_count": children_count,
            },
        )

    @classmethod
    def death_notification(
        cls,
        deceased_name: str,
        to_name: str,
        cause: str,
        final_stats: dict[str, Any],
    ) -> FamilyMessage:
        """Create a death notification message."""
        return cls(
            message_type="death_notification",
            from_name=deceased_name,
            to_name=to_name,
            data={
                "cause": cause,
                "final_stats": final_stats,
            },
        )

    @classmethod
    def resource_transfer(
        cls,
        from_name: str,
        to_name: str,
        amount: float,
        reason: str = "kin_help",
    ) -> FamilyMessage:
        """Create a resource transfer message."""
        return cls(
            message_type="resource_transfer",
            from_name=from_name,
            to_name=to_name,
            data={
                "amount": amount,
                "reason": reason,
            },
        )

    @classmethod
    def sibling_introduction(
        cls,
        from_name: str,  # Parent
        to_name: str,  # Child receiving intro
        sibling_name: str,
    ) -> FamilyMessage:
        """Create a sibling introduction message."""
        return cls(
            message_type="sibling_introduction",
            from_name=from_name,
            to_name=to_name,
            data={
                "sibling_name": sibling_name,
            },
        )
