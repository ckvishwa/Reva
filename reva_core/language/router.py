"""A small deterministic intent router for the real voice loop (MASTER-LOOP B1.3).

It handles one thing end to end so the dialogue state is exercised by a live turn: drafting an
expense and changing the draft ("add twelve dollars for lunch" -> "make it fifteen"). Everything
else is `chat` and goes to the assistant orchestrator. S09 replaces this with the full rule fast
path, resolution ladder and `authorize()`; the contract stays: the router only *proposes*.

Safety:
* The router never commits anything. Accepting a draft calls `DialogueTracker.accept_proposal`
  (so "undo" and "it" work) and says nothing was saved, because no executor exists yet. "Done" is
  never claimed from this module.
* Every reply is a template. No model text reaches the user from here.
* Ambiguous amounts ("twelve fifty") are asked about, never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from reva_core.language import outcomes
from reva_core.language.dialogue import DialogueTracker, Entity, Option
from reva_core.language.entities import AppResolver
from reva_core.language.normalizer import TypedValue, normalize
from reva_core.language.rules import RuleHit, parse
from reva_core.policy import authorize as policy
from reva_core.policy.broker import ActionView
from reva_core.policy.registry import DEFAULT_REGISTRY
from reva_core.shared.ids import new_id

TurnKind = Literal[
    "proposed", "amended", "accepted", "dismissed", "clarify", "unresolved", "chat",
    "action", "approval", "refused",
]  # fmt: skip

LOCAL = "local"


class ActionPort(Protocol):
    """What the router needs from the broker. The router proposes; it never grants."""

    def propose(self, proposal: policy.Proposal) -> ActionView: ...


ENTITY_KIND = "proposal"
MAX_DESCRIPTION = 40
INTENT = "finance.add_transaction"

_ADD = re.compile(
    r"^(?:add|log|record|put|enter)\s+(?:an?\s+)?(?:expense\s+(?:of\s+)?)?(?P<rest>.+)$",
    re.IGNORECASE,
)
_FOR = re.compile(r"\b(?:for|on)\s+(?P<what>[a-z][a-z0-9 &'-]*)$", re.IGNORECASE)
_AMEND = re.compile(
    r"^(?:(?:no|actually)[, ]+)?(?:make|change|set|update)\s+"
    r"(?P<ref>it|that one|that|this one|this|the last one|the one before)"
    r"(?:\s+(?:to|be))?\s+(?P<rest>.+)$",
    re.IGNORECASE,
)
_YES = re.compile(
    r"^(?:yes|yep|yeah|yup|confirm|confirmed|save it|do it|go ahead|that'?s right|correct)$",
    re.IGNORECASE,
)
_NO = re.compile(
    r"^(?:no|nope|cancel|cancel that|never ?mind|forget it|drop it|don'?t)$", re.IGNORECASE
)


@dataclass(frozen=True)
class Proposal:
    action_id: str
    intent: str
    amount_minor: int
    currency: str
    description: str

    @property
    def label(self) -> str:
        return money_label(self.amount_minor, self.currency)


@dataclass(frozen=True)
class RoutedTurn:
    kind: TurnKind
    reply: str | None = None
    proposal: Proposal | None = None
    action: ActionView | None = None


def money_label(amount_minor: int, currency: str) -> str:
    amount = Decimal(amount_minor) / 100
    symbol = {"USD": "$", "EUR": "EUR ", "GBP": "GBP "}.get(currency, currency + " ")
    return f"{symbol}{amount:,.2f}"


def _clean_description(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9 &'-]", "", text.lower()).strip()
    return re.sub(r"\s+", " ", cleaned)[:MAX_DESCRIPTION].strip()


class IntentRouter:
    """One per voice session: remembers the draft being talked about."""

    def __init__(
        self,
        dialogue: DialogueTracker,
        actions: ActionPort | None = None,
        resolver: AppResolver | None = None,
    ) -> None:
        self._dialogue = dialogue
        self._actions = actions
        self._resolver = resolver or AppResolver(_app_keys())
        self._guess: RuleHit | None = None  # an app name we only guessed; waiting for yes/no
        self._pending: Proposal | None = None
        self._awaiting_amount: tuple[str, TypedValue, bool] | None = None

    @property
    def pending(self) -> Proposal | None:
        return self._pending

    def route(self, transcript: str, *, now: datetime) -> RoutedTurn:
        text = re.sub(r"\s+", " ", transcript.strip().strip(".!?,")).strip()
        if not text:
            return RoutedTurn("chat")
        normalized = normalize(text, now=now)
        cleaned = normalized.cleaned.strip().strip(".!?,")

        if self._awaiting_amount is not None:
            answered = self._answer_amount(cleaned)
            if answered is not None:
                return answered

        if self._guess is not None:
            answered = self._answer_guess(cleaned)
            if answered is not None:
                return answered

        if self._pending is not None:
            if _YES.match(cleaned):
                return self._accept()
            if _NO.match(cleaned):
                return self._dismiss()

        amend = _AMEND.match(cleaned)
        if amend is not None:
            return self._amend(amend.group("ref"), normalized.values)

        if self._actions is not None:
            hit = parse(cleaned, self._resolver)
            if hit is not None:
                return self._from_rule(hit)

        add = _ADD.match(cleaned)
        if add is not None:
            return self._propose(add.group("rest"), normalized.values)
        return RoutedTurn("chat")

    # ------------------------------------------------------------------ steps

    def _propose(self, rest: str, values: tuple[TypedValue, ...]) -> RoutedTurn:
        money = [v for v in values if v.kind == "money"]
        what = _FOR.search(rest)
        description = _clean_description(what.group("what")) if what else ""
        if not money:
            return RoutedTurn("chat")  # not an expense; the assistant can ask what they mean
        if len(money) > 1:
            return RoutedTurn("clarify", "I heard more than one amount. Which one is it?")
        if not description:
            return RoutedTurn("clarify", "What was it for?")
        return self._with_amount(money[0], description, amended=False)

    def _with_amount(self, value: TypedValue, description: str, *, amended: bool) -> RoutedTurn:
        if value.ambiguous:
            options = [
                Option(f"amount-{index}", money_label(r.value["amount_minor"], r.value["currency"]))
                for index, r in enumerate(value.readings[:3])
            ]
            self._dialogue.ask("amount", options)
            self._awaiting_amount = (description, value, amended)
            labels = " or ".join(o.label for o in options)
            return RoutedTurn("clarify", f"Did you mean {labels}?")
        return self._set(value.readings[0].value, description, amended=amended)

    def _set(self, money: dict[str, object], description: str, *, amended: bool) -> RoutedTurn:
        proposal = Proposal(
            action_id=self._pending.action_id if amended and self._pending else new_id(),
            intent=INTENT,
            amount_minor=int(money["amount_minor"]),  # type: ignore[call-overload]
            currency=str(money["currency"]),
            description=description,
        )
        self._pending = proposal
        self._awaiting_amount = None
        self._dialogue.begin_intent(
            INTENT,
            {"amount_minor": proposal.amount_minor, "description": description},
            [],
        )
        self._dialogue.reference(
            Entity(proposal.action_id, ENTITY_KIND, f"{proposal.label} {description}")
        )
        verb = "Changed to" if amended else "Add"
        stop = "." if amended else "?"
        reply = f"{verb} {proposal.label} for {description}{stop} Say yes to confirm."
        return RoutedTurn("amended" if amended else "proposed", reply, proposal)

    def _amend(self, ref: str, values: tuple[TypedValue, ...]) -> RoutedTurn:
        pending = self._pending
        reference = self._dialogue.resolve_reference(ref)
        if (
            pending is None
            or reference.status != "resolved"
            or reference.entity is None
            or reference.entity.id != pending.action_id
        ):
            return RoutedTurn("unresolved", "I'm not sure which one you mean.")
        money = [v for v in values if v.kind == "money"]
        numbers = [v for v in values if v.kind == "number"]
        if len(money) == 1 and not numbers:
            value = money[0]
        elif len(numbers) == 1 and not money:
            amount = Decimal(numbers[0].value["number"])
            value = _as_money(numbers[0], amount, pending.currency)
        else:
            return RoutedTurn("clarify", "What should the amount be?")
        return self._with_amount(value, pending.description, amended=True)

    def _answer_amount(self, cleaned: str) -> RoutedTurn | None:
        assert self._awaiting_amount is not None
        description, held, amended = self._awaiting_amount
        reference = self._dialogue.resolve_reference(cleaned)
        if reference.status == "resolved" and reference.entity is not None:
            self._dialogue.answer_clarification()
            index = int(reference.entity.id.removeprefix("amount-"))
            chosen = held.readings[index].value
            return self._set(chosen, description, amended=amended)
        return None

    # ------------------------------------------------------------ the action path

    def _from_rule(self, hit: RuleHit) -> RoutedTurn:
        if hit.unknown_app is not None:
            return RoutedTurn("refused", outcomes.UNKNOWN_APP)
        if hit.guess is not None:
            # Only a guess ("notepad?" for "note pad"): never act on it, ask first.
            options = list(hit.guess.entity.candidates) or [str(hit.args["app_key"])]
            self._guess = hit
            return RoutedTurn("clarify", outcomes.which_app_question(options[:3]))
        return self._propose_action(hit.capability, hit.args, hit.entities, hit.unresolved_terms)

    def _propose_action(
        self,
        capability: str,
        args: dict[str, object],
        entities: tuple[policy.Entity, ...] = (),
        unresolved: tuple[str, ...] = (),
    ) -> RoutedTurn:
        assert self._actions is not None
        view = self._actions.propose(
            policy.Proposal(
                proposal_id=new_id(),
                capability=capability,
                args=args,
                entities=entities,
                unresolved_terms=unresolved,
                source="voice",
                origin_device=LOCAL,
                target_device=LOCAL,
            )
        )
        if view.status == "allowed":
            return RoutedTurn("chat", action=view)  # read-only: the assistant answers from data
        if view.status == "awaiting_approval":
            reply = outcomes.approval_prompt(capability, args)
            return RoutedTurn("approval", reply, action=view)
        if view.status == "granted":
            return RoutedTurn("action", outcomes.requested_text(capability, args), action=view)
        reply = view.speak or outcomes.REFUSED_GENERIC
        return RoutedTurn("refused", reply, action=view)

    def _answer_guess(self, cleaned: str) -> RoutedTurn | None:
        guess = self._guess
        assert guess is not None and guess.guess is not None
        if _NO.match(cleaned):
            self._guess = None
            return RoutedTurn("dismissed", "Okay, dropped it.")
        if not _YES.match(cleaned):
            self._guess = None  # they said something else; treat it as a new request
            return None
        self._guess = None
        key = str(guess.args["app_key"])
        confirmed = policy.Entity("app", guess.guess.entity.phrase, policy.Resolution.CONFIRMED)
        return self._propose_action(guess.capability, {"app_key": key}, (confirmed,))

    def _accept(self) -> RoutedTurn:
        assert self._pending is not None
        proposal, self._pending = self._pending, None
        self._dialogue.accept_proposal(
            proposal.action_id,
            [Entity(proposal.action_id, ENTITY_KIND, f"{proposal.label} {proposal.description}")],
        )
        if self._actions is not None:
            # A spoken yes is not an approval (T2): the broker waits for a tap on the screen.
            return self._propose_action(
                INTENT,
                {
                    "amount": float(Decimal(proposal.amount_minor) / 100),
                    "currency": proposal.currency,
                    "category": proposal.description or "uncategorised",
                    "note": proposal.description,
                },
                (policy.Entity("amount", proposal.label, policy.Resolution.TYPED_VALUE),),
            )
        # No executor exists yet (S09): accepting a draft must not sound like a saved transaction.
        return RoutedTurn(
            "accepted",
            "Okay, noted. Nothing is saved yet; saving by voice isn't connected.",
            proposal,
        )

    def _dismiss(self) -> RoutedTurn:
        self._pending = None
        self._awaiting_amount = None
        return RoutedTurn("dismissed", "Okay, dropped it.")


def _as_money(number: TypedValue, amount: Decimal, currency: str) -> TypedValue:
    from reva_core.language.normalizer import Reading

    minor = int((amount * 100).quantize(Decimal(1)))
    reading = Reading(
        "money-0",
        money_label(minor, currency),
        {"amount": f"{amount:.2f}", "amount_minor": minor, "currency": currency},
        1.0,
    )
    return TypedValue("money", number.phrase, (reading,))


def _app_keys() -> tuple[str, ...]:
    capability = DEFAULT_REGISTRY.get("windows.app.open")
    assert capability is not None
    return tuple(capability.args_schema["properties"]["app_key"]["enum"])
