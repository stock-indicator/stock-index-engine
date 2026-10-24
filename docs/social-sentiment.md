# Social & Prediction-Market Sentiment Sources

Three keyless public sources feeding the `Sentiment` category. Implementation
lives in `common/social/`, indicators in `indicators/sentiment/`.

| Indicator | Slug | Source | Triggers (`high`) when |
|---|---|---|---|
| Retail Buzz Velocity | `retail_buzz_velocity` | Reddit Atom feed | posting rate ≥ 90th percentile of own history |
| Social Bull-Bear Ratio | `social_bull_bear_ratio` | StockTwits public stream | ≥ 75% of labelled messages bullish |
| Recession Odds | `recession_odds` | Polymarket Gamma API | implied probability ≥ 35% |

None of the three needs an API key, an account, or OAuth.

## The one constraint that shapes all three

**These sources serve only a live reading. There is no historical vintage.**

Reddit's search feed reaches back about a week, StockTwits serves a recent
message window, and Polymarket's Gamma API has no as-of endpoint at all. So
unlike every other indicator in this engine, these three cannot be backfilled:

- `--lookback-days 365` will **not** produce a year of history for them.
- A fresh checkout starts with a single data point.
- The series grows one row per day, from the day you first run it.

The alternative would be to record today's reading against past dates, which
puts information into a backtest that nobody could have had at the time. A
short honest series beats a long fabricated one, so backfill is not offered.

`Retail Buzz Velocity` reports `status: normal` with a "building baseline"
note until it has 30 observations, because a percentile off five readings is
not a percentile.

## Why these metrics

**Reddit — posting velocity, not post count.** A feed page is capped at 100
entries, so a count saturates exactly when the market gets interesting. The
timestamp span of that page does not: 100 posts over 2 hours is ~1200/day,
the same 100 over 12 hours is ~200/day. Ranked against its own history rather
than an absolute number, because Reddit's own traffic baseline drifts.

**StockTwits — self-labelled sentiment.** Posters tag their own messages
Bullish or Bearish, so a directional read falls out of counting labels. No
NLP, no model to drift or tune. Only a minority of messages carry a label, so
the labelled count travels with the ratio — a 100% bullish reading off four
messages is noise, and the indicator needs to tell that apart from a real one.
Fewer than 10 labelled messages is reported unavailable rather than guessed at.

**Polymarket — what money bets happens next.** Complements the macro
indicators instead of repeating them: FRED says where the economy *is*, this
says what the crowd prices to happen. Markets thinner than $10k volume are
ignored; at that size the "probability" moves on a few hundred dollars of flow.

## Failure handling

`common/social/http.py` raises `SourceUnavailable` on any network error,
non-2xx status, or oversized body. It is deliberately distinct from a fetch
that succeeded and found nothing:

> A reading we failed to take is not a reading of zero. If the two were
> collapsed, every rate-limit blip would append a permanent bearish data point.

So on an outage the indicators **return `None` from `collect_incremental`**,
leaving the stored series untouched rather than writing a row. `compute()`
then adds a staleness note once the newest reading is more than a day old.

Rate limits are handled with a single retry that honours `Retry-After`,
falling back to 60s with ±20% jitter so concurrent refreshes sharing an IP
don't retry in lockstep.

Both Reddit and StockTwits reject the generic browser User-Agent used in
`common/config.py`; `common/social/http.py` sends a descriptive project
identifier instead, which is what both services' API etiquette asks for.

## Tuning

Defaults live as class constants on each indicator and as module constants in
`common/social/`:

- subreddits — `common/social/reddit.py` → `DEFAULT_SUBREDDITS`
- symbols — `common/social/stocktwits.py` → `DEFAULT_SYMBOLS`
- prediction topic — `common/social/polymarket.py` → `DEFAULT_TOPIC`
- thresholds — `TRIGGER_PERCENTILE`, `EUPHORIA_RATIO`, `TRIGGER_PROBABILITY`

Note that the engine's summary counts only `high` as triggered, and treats
anything outside `{high, normal}` as unavailable. Capitulation and
complacency readings are therefore reported in `notes` and `pure_value`
rather than as their own status, so the indicator stays inside the summary's
available set.

## Attribution

The fetching approach — RSS over the WAF-blocked JSON endpoint, the
descriptive User-Agent, the `Retry-After` backoff, and the
failed-vs-empty distinction — follows
[TradingAgents](https://github.com/TauricResearch/TradingAgents)'
`tradingagents/dataflows/vendors/` (Apache-2.0). The metrics and the
indicator layer are this project's own.
