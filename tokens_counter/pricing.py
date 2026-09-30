"""
Pricing resolution: which rates apply to a model id seen in a transcript.

`models_config.json` holds the rates someone checked. A model Claude Code
starts using after that file was last edited would otherwise price as N/A
until a human adds it, so a lookup falls through four layers, most trusted
first, and every result says which one it came from:

1. configured - the exact id is in models_config.json.
2. alias      - a spelling of a configured model: date suffix
                (`claude-haiku-4-5-20251001`), `[1m]` context tag, Bedrock
                (`us.anthropic.claude-...-v1:0`) or Vertex (`...@20251001`)
                forms. Same model, same price, so it's as exact as (1).
3. learned    - derived from Claude Code's own cost figures. Some
                transcripts carry `cost-state` records with `modelUsage`:
                per-model token counts plus the `costUSD` Claude Code itself
                charged. See learn_rates() for how a rate is accepted.
4. estimated  - the nearest configured version of the same family
                (`claude-opus-5-6` -> `claude-opus-5-5`). Shown with a "~"
                and the model it was borrowed from; never passed off as exact.

A model that fits none of them (not a recognizable Claude id) stays
unpriced - None, rendered N/A - rather than guessed.

Token convention here is the API's own, and it is ADDITIVE: `input_tokens`
excludes cached tokens, and `cache_read`/`cache_write` are counted
separately. That is how every transcript line reports usage.
"""

import math
import re

# Web search is billed per request on top of tokens: $10 per 1,000.
WEB_SEARCH_COST_PER_REQUEST = 0.01

# Anthropic's documented multipliers on the input rate. A 1-hour cache write
# costs 2x input, a 5-minute one 1.25x; Claude Code writes 1-hour entries, so
# pricing every write at 1.25x understated real cost by ~7%. Output has been
# 5x input across every Claude family, which learn_rates() relies on.
OUTPUT_MULTIPLIER = 5.0
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_5M_MULTIPLIER = 1.25
CACHE_WRITE_1H_MULTIPLIER = 2.0

# learn_rates() acceptance: a derived input rate must land on a whole cent
# (every published Claude rate does) and at least this many DIFFERENT usage
# records must agree on it.
LEARN_MIN_AGREEING_RECORDS = 2
LEARN_CENT_TOLERANCE = 1e-4
# Below this many token-equivalents a record can't pin a rate to the cent.
LEARN_MIN_WEIGHT = 10_000

_BRACKET_TAG = re.compile(r"\[[^\]]*\]$")
_BEDROCK_PREFIX = re.compile(r"^(?:[a-z]{2,6}\.)?anthropic\.")
_BEDROCK_VERSION = re.compile(r"-v\d+(?::\d+)?$")
_DATE_SUFFIX = re.compile(r"-\d{8}$")
# claude-opus-4-8, claude-fable-5-1, claude-sonnet-5
_MODERN_ID = re.compile(r"^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?$")
# claude-3-5-sonnet, claude-3-opus
_LEGACY_ID = re.compile(r"^claude-(\d+)(?:-(\d{1,2}))?-([a-z]+)$")


def normalize_model_id(model):
    """
    The canonical spelling of a model id, or the input unchanged if it isn't
    a string. Strips everything that names the same model differently.
    """
    if not isinstance(model, str):
        return model
    text = model.strip().lower()
    text = _BRACKET_TAG.sub("", text)
    if "/" in text:
        text = text.rsplit("/", 1)[1]
    text = text.split("@", 1)[0]
    text = _BEDROCK_PREFIX.sub("", text)
    text = _BEDROCK_VERSION.sub("", text)
    text = _DATE_SUFFIX.sub("", text)
    if text.endswith("-latest"):
        text = text[: -len("-latest")]
    return text


def parse_model_id(model):
    """(family, (major, minor)) for a Claude model id, or None."""
    text = normalize_model_id(model)
    if not isinstance(text, str):
        return None
    match = _MODERN_ID.match(text)
    if match:
        family, major, minor = match.groups()
        return family, (int(major), int(minor or 0))
    match = _LEGACY_ID.match(text)
    if match:
        major, minor, family = match.groups()
        return family, (int(major), int(minor or 0))
    return None


# An estimate may borrow from a sibling at most this many major versions
# away. "claude-opus-6" priced like Opus 5.5 is a fair guess; "claude-opus-10"
# (or a malformed "claude-opus-99999") is not a guess anyone should see.
MAX_ESTIMATE_MAJOR_GAP = 1


def _family_estimate(model, config_data):
    """
    (config key, pricing) of the configured sibling whose rates `model` most
    plausibly shares, or None.

    The newest configured version AT OR BELOW the model's wins: a new release
    is priced like the release it replaces far more often than like one it
    predates - and prices have changed downward between generations (Opus
    went from $15 to $5 at 4.5), so borrowing from a NEWER sibling
    understates. Only when nothing older is configured does the nearest newer
    version stand in.
    """
    parsed = parse_model_id(model)
    if parsed is None:
        return None
    family, version = parsed
    older, newer = None, None
    for key, pricing in config_data.items():
        if not isinstance(pricing, dict):
            continue
        other = parse_model_id(key)
        if other is None or other[0] != family:
            continue
        candidate = (other[1], key, pricing)
        if other[1] <= version:
            if older is None or other[1] > older[0]:
                older = candidate
        elif newer is None or other[1] < newer[0]:
            newer = candidate
    best = older or newer
    if best is None or abs(best[0][0] - version[0]) > MAX_ESTIMATE_MAJOR_GAP:
        return None
    return best[1], best[2]


def resolve_pricing(model, config_data, learned=None):
    """
    Rates for `model` as a new dict, or None if it can't be priced honestly.

    The dict carries the configured fields plus `pricing_source`
    ("configured", "alias", "learned" or "estimated") and `based_on` (the
    config key or record count the rates came from, None when exact).
    """
    if not isinstance(model, str) or not model:
        return None
    config_data = config_data or {}
    pricing = config_data.get(model)
    if isinstance(pricing, dict):
        return {**pricing, "pricing_source": "configured", "based_on": None}

    normalized = normalize_model_id(model)
    parsed = parse_model_id(model)
    for key, pricing in config_data.items():
        if not isinstance(pricing, dict):
            continue
        # Same spelling once normalized, or the same family and version
        # written differently ("claude-opus-4-0" is "claude-opus-4").
        if normalize_model_id(key) == normalized or (parsed is not None and parse_model_id(key) == parsed):
            return {**pricing, "pricing_source": "alias", "based_on": key}

    estimate = _family_estimate(model, config_data)
    learned_rates = (learned or {}).get(normalized)
    if learned_rates:
        result = dict(learned_rates)
        # Claude Code's cost records carry no context window; borrow the
        # family's, which is a size, not a price.
        result.setdefault("context_window", estimate[1].get("context_window") if estimate else None)
        return result

    if estimate:
        key, pricing = estimate
        return {**pricing, "pricing_source": "estimated", "based_on": key}
    return None


def token_cost(pricing, input_tokens=0, output_tokens=0, cache_read=0,
               cache_write=0, cache_write_1h=0, web_search_requests=0):
    """
    USD cost of one usage bucket under `pricing`, additive convention.

    `cache_write` is ALL cache-creation tokens; `cache_write_1h` is the part
    of it written with a 1-hour TTL, priced at the 1h rate. The rest is
    priced at the 5-minute rate.
    """
    if not pricing:
        return None
    per = 1_000_000.0
    input_rate = pricing.get("input_cost_per_1m", 0.0) or 0.0
    cost = input_tokens * input_rate / per
    cost += output_tokens * (pricing.get("output_cost_per_1m", 0.0) or 0.0) / per
    if pricing.get("supports_caching", True):
        write_1h = min(max(cache_write_1h, 0), cache_write)
        write_5m = cache_write - write_1h
        rate_1h = pricing.get("cache_write_1h_cost_per_1m") or input_rate * CACHE_WRITE_1H_MULTIPLIER
        cost += cache_read * (pricing.get("cache_read_cost_per_1m", 0.0) or 0.0) / per
        cost += write_5m * (pricing.get("cache_write_cost_per_1m", 0.0) or 0.0) / per
        cost += write_1h * rate_1h / per
    cost += web_search_requests * pricing.get("web_search_cost_per_request", WEB_SEARCH_COST_PER_REQUEST)
    return cost


def bucket_cost(pricing, bucket):
    """token_cost() for a by-model bucket dict (input/output/cache_* keys)."""
    return token_cost(
        pricing,
        bucket.get("input", 0), bucket.get("output", 0),
        bucket.get("cache_read", 0), bucket.get("cache_write", 0),
        bucket.get("cache_write_1h", 0), bucket.get("web_search", 0),
    )


def _finite(value):
    """`value` as a finite, non-negative float, or None."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _record_numbers(usage):
    """(input, output, cache_read, cache_write, web_search, cost) or None if any is unusable."""
    keys = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens",
            "webSearchRequests", "costUSD")
    values = [_finite(usage.get(k) or 0) for k in keys]
    return None if any(v is None for v in values) else tuple(values)


def _implied_input_rate(numbers):
    """
    (rate, floor_ratio) for one record, or None.

    `rate` is the input rate that reproduces the record's cost under the
    standard multipliers with every cache write at the 1-hour price, which is
    what Claude Code writes. Some writes are 5-minute (~11% of write tokens
    on the developer's machine), and those make the true cost LOWER, so the
    true rate x satisfies  x * floor_ratio <= rate <= x,  where floor_ratio
    is what the implied rate would be if every write were 5-minute. A record
    outside that band for a candidate rate contradicts it.
    """
    inp, out, read, write, web, cost = numbers
    base = inp + OUTPUT_MULTIPLIER * out + CACHE_READ_MULTIPLIER * read
    weight_1h = base + CACHE_WRITE_1H_MULTIPLIER * write
    weight_5m = base + CACHE_WRITE_5M_MULTIPLIER * write
    token_cost_usd = cost - web * WEB_SEARCH_COST_PER_REQUEST
    if weight_1h < LEARN_MIN_WEIGHT or token_cost_usd <= 0:
        return None
    rate = token_cost_usd / (weight_1h / 1_000_000.0)
    if not math.isfinite(rate):
        return None
    return rate, weight_5m / weight_1h


def _mix_signature(numbers):
    """Token mix as proportions, so 1M/2M of the same shape count as ONE mix."""
    tokens = numbers[:4]
    total = sum(tokens)
    return tuple(round(t / total, 4) for t in tokens) if total else None


def learn_rates(cost_states):
    """
    Rates Claude Code itself charged, recovered from its `cost-state` records.

    Each record gives one equation (tokens by type -> costUSD) and a rate has
    four unknowns, so the standard multipliers are assumed and only the
    input rate is solved for. A rate is accepted only when the evidence is
    hard to get by accident:
      - records flagged `hasUnknownModelCost` are ignored (Claude Code didn't
        know the price either), as are non-finite or negative numbers;
      - the implied rate lands on a whole cent, as every published Claude
        rate does;
      - at least LEARN_MIN_AGREEING_RECORDS records with genuinely DIFFERENT
        token proportions imply that same cent - a wrong multiplier gives a
        different rate per mix, so agreement across mixes is what tests the
        assumption - and between them they include cache reads AND cache
        writes, so the cache rates emitted were actually exercised;
      - NO record of the model contradicts it (see _implied_input_rate):
        one record priced in a way the multipliers can't explain - a
        model with a special cache-read rate, say - vetoes learning, and
        the family estimate (marked "~") is used instead.
    Returns {normalized model id: pricing dict with pricing_source "learned"}.
    """
    observations = {}
    for record in cost_states or ():
        if not isinstance(record, dict) or record.get("hasUnknownModelCost"):
            continue
        model_usage = record.get("modelUsage")
        if not isinstance(model_usage, dict):
            continue
        for model, usage in model_usage.items():
            if not isinstance(model, str) or not isinstance(usage, dict):
                continue
            numbers = _record_numbers(usage)
            implied = _implied_input_rate(numbers) if numbers else None
            if implied is None:
                continue
            observations.setdefault(normalize_model_id(model), []).append((numbers, implied))

    learned = {}
    for model, records in observations.items():
        on_grid = {}
        for numbers, (rate, _floor) in records:
            cents = round(rate, 2)
            signature = _mix_signature(numbers)
            if cents > 0 and signature and abs(rate - cents) / cents <= LEARN_CENT_TOLERANCE:
                on_grid.setdefault(cents, {})[signature] = numbers
        if not on_grid:
            continue
        rate, mixes = max(on_grid.items(), key=lambda item: len(item[1]))
        if len(mixes) < LEARN_MIN_AGREEING_RECORDS:
            continue
        if not any(n[2] > 0 for n in mixes.values()) or not any(n[3] > 0 for n in mixes.values()):
            continue
        tolerance = 1 + LEARN_CENT_TOLERANCE
        if any(not (rate * floor / tolerance <= implied <= rate * tolerance)
               for _numbers, (implied, floor) in records):
            continue
        learned[model] = {
            "name": model,
            "provider": "Anthropic Claude",
            "input_cost_per_1m": rate,
            "output_cost_per_1m": round(rate * OUTPUT_MULTIPLIER, 4),
            "cache_write_cost_per_1m": round(rate * CACHE_WRITE_5M_MULTIPLIER, 4),
            "cache_write_1h_cost_per_1m": round(rate * CACHE_WRITE_1H_MULTIPLIER, 4),
            "cache_read_cost_per_1m": round(rate * CACHE_READ_MULTIPLIER, 4),
            "supports_caching": True,
            "pricing_source": "learned",
            "based_on": f"{len(mixes)} Claude Code cost records",
        }
    return learned


class PriceBook:
    """resolve_pricing() memoized per model, for loops over thousands of lines."""

    def __init__(self, config_data, learned=None):
        self.config_data = config_data or {}
        self.learned = learned or {}
        self._cache = {}

    def get(self, model):
        if model not in self._cache:
            self._cache[model] = resolve_pricing(model, self.config_data, self.learned)
        return self._cache[model]

    def cost(self, model, bucket):
        """Cost of a bucket for `model`, or None if the model can't be priced."""
        pricing = self.get(model)
        return bucket_cost(pricing, bucket) if pricing else None

    def source(self, model):
        pricing = self.get(model)
        return pricing.get("pricing_source") if pricing else None

    def is_estimated(self, model):
        return self.source(model) == "estimated"
